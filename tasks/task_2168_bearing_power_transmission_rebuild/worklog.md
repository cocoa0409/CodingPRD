# Worklog — task_2168_bearing_power_transmission_rebuild

## Step 1: Create task directory — 2026-08-29T03:56:51.355Z

Created `tasks/task_2168_bearing_power_transmission_rebuild/` and `tasks/task_2168_bearing_power_transmission_rebuild/workspace/`.

## Step 2: Generate scaffold — 2026-08-29T04:50:27.857Z

All three scaffold artifacts are generated and verified.

## Files written
- `SCAFFOLD.yaml` (§1.0–§1.7 + §1.2.1)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## Counts
| Dimension | Count |
|---|---|
| Entities (§1.1) | 14 |
| State machines (§1.2) | 8 (RebuildOrder carries two parallel dimensions) |
| Concurrency rules (§1.2.1) | 3 OCC rules |
| Calculations (§1.3) | 13 |
| Validations (§1.4) | 59 rows across 15 priority tiers |
| Endpoints (§1.5) | 50 (49 business + 1 `/_clock` test-driving) |
| Errors (§1.6) | 52 |
| Roles (§1.7) | 5 (segregation_of_duties model) |
| §1.8 instances | 21 (9 rule_ids, >=2 each) |
| §1.9 instances | 51 (48 with recipes + 3 `excluded_because` stubs) across 9 taxonomy sections |

## Design shape (beyond-expert calibration)
- Profile: `workflow_orchestration` + `pricing_engine`, `graph` topology, `parallel` state-machine shape, self-referential `CoreUnit.replacement_core_unit_id`, `segregation_of_duties` RBAC, immediate consistency.
- Two multi-hop cascades from different triggers: inspection ACCEPT drives a **5-hop** ledger chain (accept -> core graded/re-valued -> provisional note voided + final posted -> customer balances -> QUOTED orders re-priced), and order cancel drives a **4-hop** bench chain (release -> minutes recompute -> queue promotion -> recompute).
- Layered calculation chains: core-credit valuation with condition tiers + per-line-rounded deduction lines (631 vs 630 divergence), warranty pro-rata with hours/calendar/goodwill variants (59938 vs 114167 vs 171250), and a pinned evaluation order for the expedite-tier -> credit-cap "circular" dependency (surcharge non-monotonic at the 100000 floor: 55000 vs 47000).
- Three validation priority conflicts across three distinct category pairs (state x referential, safety x temporal, referential x safety), plus a fourth (temporal x constraint) in §1.9.
- Two interval geometries: half-open + multi-slot bench windows vs closed, capacity-1 asset occupancy with a 24-hour changeover buffer.

## Verification performed
- `scaffold_lint.py` verdict, verbatim:
  ```
  Coverage
    §1.5 endpoints declared:    50
    §1.1 entities declared:     14
    §1.8 instances scanned:     21
    §1.9 instances scanned:     48
    Calls scanned (§1.8+§1.9):  1011

  VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  ```
- Custom audits: 0 unbound `${var}` placeholders; 72 unique instance names; all 52 errors referenced by a design instance; all `grounds:` refs resolve into §1.1–§1.7; all 50 endpoints exercised by at least one recipe call; no forbidden concurrency vocabulary; scenario text stored verbatim.
- Every formula-derived assertion literal (grades 79/88/97/75/0, credits 10800/81450/58950/631/63000/90000, quotes 160450/102750/152475/180450/154999/147000, warranty 59938/145563/171250, fractions 0.650000/0.333333/0.105556) was computed with a Python execution of the scaffold's own formulas before being written.

No sibling task directories were read at any point.

## Step 3: Copy shared files — 2026-08-29T04:50:42.948Z

Copied `INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-29T05:01:49.263Z

The PRD is complete and verified.

**Output:** `workspace/PRD.md` — **417 lines**, built incrementally in 7 append operations (never a single large write), ending at §5 with no audit footer.

**Structure:** §1 Introduction (3 paragraphs) · §2 with 9 domain-derived subsections (2.2 emitted byte-verbatim from `section-2.2-response-structure.md`) · §3 with 9 workflow subsections · §4 endpoint table (4 columns) · §5 error table (2 columns).

**Verification counts (script-checked against SCAFFOLD.yaml):**

| Category | Scaffold | Present | Missing |
|---|---|---|---|
| Entities (all fields of each) | 14 | 14 | 0 |
| State machines (state_field + every from/to state) | 8 | 8 | 0 |
| Calculations (keyword-probed: constants, variants, precision) | 13 | 13 | 0 |
| Validation rows (error_id reachable in prose) | 59 | 59 | 0 |
| Validation ladder priorities (1–15, explicitly ordered in §2.8) | 15 | 15 | 0 |
| Endpoints (method+path in §4 table) | 50 | 50 | 0 |
| Error ids (in §5 table with correct HTTP status) | 52 | 52 | 0 |
| Error ids also referenced in §1–§4 narrative | 52 | 52 | 0 |
| Roles | 5 | 5 | 0 |

**Hard Contract reports:**

```
Field coverage check:
- entities[].fields: 118 required, 118 present, 0 missing
- endpoints[].input/request_body/query_params/path_params: 75 required, 75 present, 0 missing
- derived shape identifiers (feature_bands members, quote-view fields, clock echo,
  common props): 15 required, 15 present, 0 missing
  (union required set = 142; one repair pass added `inspection_id` to §3.4)
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 59 checked, 59 expressed in prose (§2.8 states the full
  1–15 ladder plus the two counter-intuitive orderings: OCC-before-state, buffer-before-occupancy,
  and §3.8 notes approval-before-staleness), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (expected_order_version /
  expected_customer_version / expected_asset_version each named with its write endpoint,
  parent version comparison, ERR_STALE_VERSION and HTTP 412), 0 missing
- state_machines[].transitions: 57 checked across 8 machines, 57 expressed with from/to
  pairs, preconditions paired to error ids, and side effects, 0 missing
- calculations[]: 13 checked, 13 fully expressed in prose (no operator syntax; nested
  per-line rounding in core valuation, floor-vs-half-up split, pinned quote waterfall
  order, pinned cause-code ladder, governing-measurement tie-break all stated), 0 missing
- validations[] conditions: 59 checked, 59 matchable to error_id, 0 missing
- endpoints[].side_effects / applies_to: 50 endpoints checked, all side-effect bullets
  expressed; CASCADE A (5 hops), B (4 hops), C (3 hops), D (3 hops) each stated hop by hop
- entities[].fields[] structured content: 118 checked, defaults / initial values /
  computed-vs-system sourcing reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 groups checked (provisional vs final core credit, COMPOSITE
  vs CONSERVATIVE life score, HOURS/CALENDAR/GOODWILL warranty bases, APPROVE vs DENY
  adjudication, HELD vs QUEUED admission, the three RELEASE sources, the two expedite
  branches, the 8 approval-rollup transitions, RECEIVED vs GRADED return-as-is),
  0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 820
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- markdown tables in §3: 0; bullet/field lists in §3: 0
Status: PASS
```

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced at any point.

**Orchestrator verification:** 417 lines, 5 top-level sections present (§1 line 3, §2 line 11, §3 line 161, §4 line 303, §5 line 360), 52 unique ERR_ ids, file ends inside the §5 table — no truncation.

## Step 6: Generate implementation — 2026-08-29T05:20:00.671Z

The Step 6 subagent terminated with an upstream API error immediately after writing its final file (`app.py`), so it never emitted its own summary or boot verification. The orchestrator verified the deliverables directly instead:

**Files written** (18 files, 3168 lines of Python + `start.sh` + `requirements.txt`):
`app.py` 80 · `auth.py` 88 · `bench_ops.py` 40 · `calc.py` 500 · `errors.py` 68 · `ledger.py` 59 · `response.py` 49 · `routes_bench.py` 112 · `routes_core.py` 192 · `routes_inspect.py` 352 · `routes_orders.py` 408 · `routes_ref.py` 359 · `routes_service.py` 309 · `store.py` 161 · `validate.py` 210 · `views.py` 172 · `start.sh` 8 · `requirements.txt` 1

**Endpoint coverage:** 50 unique `@bp.<method>("<path>")` declarations — matches the 50 endpoints in §1.5 / PRD §4. All six route blueprints are registered in `app.py`.

**Boot verification (orchestrator-run):** `PORT=18779 bash start.sh` boots clean on a fresh process; root path returns a well-formed JSON error envelope (404 with `response_type`/`meta`/`data`); auth rejects a missing `X-User-ID` with `ERR_UNAUTHENTICATED`; `POST /_clock/set_current_utc` reaches its handler and validates its body. Storage is in-memory only; no seeded entities.

**Orchestrator fix:** removed an untraced `GET /health` endpoint from `app.py` — it appears in neither PRD nor SCAFFOLD, and the local runner's readiness probe accepts any HTTP response on the root URL (`lifecycle.py:_poll_until_ready`), so no harness dependency existed. Re-verified boot after removal.

## Step 5: Generate unit tests — 2026-08-29T05:28:32.656Z

Done. Test infrastructure and suite are complete for `task_2168_bearing_power_transmission_rebuild`.

## Files written

**`test_helpers/`** (Stage 1, 9 files, ~1,600 lines)
- `types.py` — 18 status/enum classes + 14 entity TypedDicts. `Measurement` and `VibrationReading` are declared `common_fields: false` and deliberately omit `updated_at`/`version`.
- `api_client.py` — `ApiClient(GenericApiClient)`, one method per PRD §4 endpoint (all 50 plus `/_clock/set_current_utc`).
- `api_errors.py` — all 52 error ids + HTTP map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions, plus `assert_customer_ledger_invariants`, `assert_ledger_matches_notes`, `assert_quoted_order_arithmetic`.
- `factories.py`, `constants.py`, `test_users.py` (opaque-role constants + `make_customer_headers(customer_id)` for the entity-backed `Customer` role, threaded through every ownership-gated fixture call).
- `fixtures.py` — five tiers: single-record creators/reads, state-progression helpers, `setup_shop`/`setup_canonical_shop`, lifecycle shortcuts (`quote_order`, `inspect_order`, `schedule_order`, `run_order_to`, `setup_delivered_pipeline`), and in-service/warranty builders (`setup_installed_unit`, `setup_failed_installation`, `setup_claimed_installation`).

**`test_suite/`** — `conftest.py` + 10 domain-named files (`test_01_reference_data_and_receipt.py` … `test_10_access_control_and_envelopes.py`), 90 tests, ~3,500 lines.

## Coverage

- **Queue A (Difficulty): 42 tests** — all 21 instances, each with exactly 2 tests.
- **Queue B (Corner): 48 tests** — all 48 non-stub instances, 1 test each.
- **Skipped: none.** Every instance passed the PRD-first two-condition filter; no `skip`/`skipif`/`xfail` anywhere.
- The 3 `excluded_because:` stubs (`cascading_side_effects_layer_end_to_end`, `dual_variant_calculation_layer_divergence`, `rate_threshold_trigger_at_the_expedite_tier_floor`) were **not** translated; their `difficulty_instance` cross-references were verified to resolve to real §1.8 names.

## Verification performed

- Automated citation audit: all 90 docstrings carry >=1 `PRD §x.y: "…"` citation whose whitespace-normalised text is a verbatim substring of `PRD.md`; every docstring ends with exactly one `Design:` line; 69 distinct tags = 21 + 48, all resolving to real instance names.
- `pytest --collect-only` collects 90 tests cleanly (so every `from test_helpers import …` resolves); `pyflakes` clean apart from barrel-export star warnings.

## Notes worth flagging

- Where a design assert cited a PRD sentence containing embedded quotes (e.g. the `"superseded by bench grading"` void reason), the citation was re-anchored to an equivalent quote-free PRD sentence (§2.9's issue-then-void rule) rather than truncated.
- Em dashes and `§` were preserved exactly as the PRD renders them — several early citations failed the verbatim grep until they were restored.
- All literal expected values (10800 / 81450 / 58950 / 631 / 62675 / 93570 / 152475 / 59938 / 145563 / 171250 / 63000 / 55000 / 47000 …) were copied from the design yamls, not recomputed; each was independently arithmetic-checked against the PRD's stated rounding order before emission.

**Orchestrator verification:** 5096 lines across test_helpers/ + test_suite/; 90 `def test_` functions; 90 `Design:` tags resolving to 69 unique instances (21 depth + 48 breadth).


## Step 7: Run tests and iterate — 2026-08-29T05:38:00.768Z

The task is complete. All 90 tests pass in all 8 parallel rounds, verified twice, with a mutation test proving the sweep is genuine.

## Summary

**Iterations run:** 1 sweep iteration (plus one mutation-validation round and one confirming sweep). The very first 8-round parallel sweep came back 90/90 in all 8 rounds — no failing tests, no flakiness, so the diagnostic protocol (STEPs 0–3) was never triggered.

**Tests deleted:** none. No test failed, so no test was subjected to the PRD-coverage / unique-derivability check, and no deletion criterion was ever met.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

### Why I did not stop at the first green sweep

A green first sweep is indistinguishable from a vacuous or leak-tuned one, so I ran three independent checks before exiting:

1. **Endpoint surface audit** — enumerated the Flask URL map: exactly **50 routes**, each matching a row of PRD §4, no extras (the `GET /health` the orchestrator removed has not returned). Storage is confirmed in-memory only (`store.db` is a dict-of-dicts, empty at import, no seeding anywhere in `app.py` or the blueprints).

2. **Mutation test** — I injected 7 deliberate bugs across independent subsystems (GRADE_B multiplier 0.75→0.70, expedite mid-tier 22%→20%, ISO zone-C floor 2.80→3.00, credit cap 40%→50%, changeover buffer 24h→12h, rebuild penalty 6→4, and widening the Inspector-only `SUBMIT` action to `ShopAdmin`). The suite dropped to **72/90 — 18 tests killed**, hitting every mutated area: zone banding, conservative-vs-composite grading, the core-credit cascade, the surcharge tiers and cap floor, the changeover-buffer edges, and both RBAC layers. The suite is genuinely coupled to the implementation; the green sweep is not vacuous.

3. **Confirming sweep** — reverted both mutated files from pre-mutation backups, verified every constant byte-for-byte, deleted the stale `results.*.json`, and re-ran the full 8-round parallel sweep against the exact shipping tree. **All 8 rounds: passed=90, total=90, failed=0, errors=0, skipped=0.**

**Deliverables in place:** `workspace/implementation/results.{1..8}.json`, all reporting 90/90, generated by the current tree. Scratch artifacts (`sweep.*.log`, `mutant.json`, `mutant.log`, `__pycache__`) were cleaned up; the implementation source is unmodified from the state it was handed to me in.

One note for the caller: because nothing failed, this run produced no evidence about the PRD-fairness of any individual test. The 18 tests the mutation exercised are demonstrably load-bearing, but the remaining 72 were only ever observed passing — if you want assurance that none of them is a tautology, that would need a broader mutation matrix rather than another stability sweep.

**Orchestrator verification:** all 8 `results.*.json` re-read independently — each `passed=90 total=90 failed=0 errors=0 skipped=0`. `test_suite/` still holds 90 `def test_` functions, so no test was quietly removed.

**Orchestrator leak audit (why a green first sweep is credible here):** parsed the Step 4 and Step 6 subagent transcripts programmatically, extracting only tool-call *inputs* (never transcript content). Neither agent's 33 / 44 tool calls ever names `SCAFFOLD_DIFFICULTY_DESIGN`, `SCAFFOLD_CORNER_DESIGN`, `test_suite`, or `test_helpers`, and neither issued a wildcard read (`SCAFFOLD*`, `*.yaml`, `tasks/*`) that could have swept the withheld design indices in. The withhold constraints held on both steps, so the clean first sweep reflects a PRD complete enough for the implementer to derive the designed behaviors — not an index leak.

## Step 8: Finalize PRD — SKIPPED

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. No `PRD_FINALIZED.md` is produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-08-29T05:45:49.902Z

Done. `workspace/PRD_COMPLETED.md` produced as a minimal in-paragraph patch over `workspace/PRD.md`.

## Integrity
- **Lines:** 417 → 417 (no section added, no line split). **Chars:** 84,447 → 90,400 (**+5,953**).
- **§5 error table intact:** 52 `ERR_*` rows, file still ends on `| ERR_CREDIT_CAP_EXCEEDED | 422 |`. **§4 endpoint table intact:** 50 rows. All 26 headings unchanged.
- 27 of 417 lines touched (54 diff sides).

## Counts
- **36 changes** across 27 paragraphs: **34 ambiguity-pins**, **2 mismatch-revisions**.

## Changes
- §2.1 — insert — ambiguity — ownerless reference data (standards, benches) is outside `Customer` read confinement; hanging lists still filter and `total_count` counts post-filter — `views.py:138-141,168-172`, `routes_ref.py:245-249,282-300`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` is also `ERR_INVALID_REQUEST` — `validate.py:184-197`
- §2.3 — insert — ambiguity — `created_at` ties broken by ascending insertion order — `store.py:136-137`
- §2.4 — insert — ambiguity — `created_at`/`updated_at`/`api_request_timestamp` come from real wall-clock, not the logical clock; client-supplied instants echoed verbatim — `store.py:106,117`, `response.py:20`, `routes_inspect.py:52`, `routes_bench.py:56-57`
- §2.4 — insert — ambiguity — clock endpoint answers 200, echoes `to_iso8601` verbatim, rejects unparseable with `ERR_INVALID_REQUEST` — `routes_ref.py:352-359`
- §2.8 — insert — ambiguity — step 3 only fires on a recognised discriminator; unknown/absent `action` falls to step 5 — `auth.py:38`
- **§2.9 — revise — mismatch — repricing of `QUOTED` orders happens on note *voiding* only; pure postings (core receipt, manual adjustment, warranty issue-credit) recompute balances but leave order figures alone** — `routes_core.py:80`, `routes_ref.py:157`, `routes_service.py:284` vs `routes_inspect.py:352`, `routes_ref.py:345`, `ledger.py:45-59`
- §2.9 — insert — ambiguity — a repriced order's `version` bumps whether or not either figure moves — `calc.py:395-400`
- §3.1 — revise — ambiguity — `duty_class` is mandatory on asset registration — `routes_ref.py:95`
- §3.1 — insert — ambiguity — band members `rework_extension_um`/`deduction_pct`/`weight` optional with defaults 0/0/1; duplicate `feature_code` in `feature_bands` is `ERR_INVALID_REQUEST` — `routes_ref.py:174-185`
- §3.1 — insert — ambiguity — manual-adjustment `memo` is mandatory — `routes_ref.py:146`
- §3.2 — insert — ambiguity — provisional note `memo` is exactly `"provisional exchange-core credit"`; receipt does not reprice — `routes_core.py:76-80`
- §3.3 — insert — ambiguity — `reading_at` is mandatory and must parse as ISO 8601 — `routes_inspect.py:40`
- §3.4 — insert — ambiguity — inspection creation never fails on core/order state; only the core transition is skipped — `routes_inspect.py:128-133`
- §3.4 — insert — ambiguity — a `linked_vibration_reading_id` on any other advance action is still resolved (404) and asset-checked but changes nothing — `routes_inspect.py:231-235,258-261`
- §3.4 — insert — ambiguity — `measured_um` accepts any whole number including negatives — `routes_inspect.py:171`
- §3.4 — insert — ambiguity — `sequence_no` is existing-count + 1 and is never reset by a reopen — `routes_inspect.py:185`
- §3.5 — **revise — mismatch — `return_reason` on RETURN is optional, recorded as null when omitted** — `routes_inspect.py:229,267`
- §3.5 — insert — ambiguity — reopen leaves measurements, linked reading, override, `return_reason` and `accepted_by_user_id` untouched — `routes_inspect.py:269-278`
- §3.6 — revise — ambiguity — acceptance writes core `status` to `GRADED` from wherever it stood; core state is not a precondition — `routes_inspect.py:337-338`
- §3.6 — revise — ambiguity — re-inspection returns *every* `ACCEPTED` inspection on *every* order referencing the core — `routes_core.py:145-150`
- §3.7 — insert — ambiguity — REVISE's five rewritable fields keep current values when omitted/null; waiver cannot be cleared; aftermarket guard uses post-rewrite values — `routes_orders.py:350-379`
- §3.7 — insert — ambiguity — parent-order state tested before the line's own status; same gate guards REVISE — `routes_orders.py:358-366`
- §3.7 — insert — ambiguity — a decision omitting `decision_note` writes null over the prior note — `routes_orders.py:396,405`
- §3.8 — insert — ambiguity — quote view before first quote: all money fields, `quoted_part_revision` and `credit_cap_cents` null, `quote_stale` true — `routes_orders.py:127-143`
- §3.8 — insert — ambiguity — hand-releasing a `CONFIRMED` window under an `IN_PROGRESS` order is `ERR_RESERVATION_INVALID_STATE` (409), tested after the status check — `routes_bench.py:102-108`
- §3.8 — insert — ambiguity — `committed_minutes` writes back only on a real change, so CONFIRM and a `QUEUED` creation leave bench `updated_at`/`version` alone — `calc.py:421-423`
- §3.8 — revise — ambiguity — queue-promotion final tie-break is earlier insertion order — `calc.py:469-472`
- §3.9 — insert — ambiguity — `ERR_CORE_SCRAPPED` on START in practice only catches the `SCRAP` condition grade; no `ACCEPTED` inspection satisfies the clearance gate vacuously — `routes_orders.py:195-204`
- §3.9 — insert — ambiguity — on installation, the scrap test precedes `ERR_UNIT_NOT_DELIVERED`, and covers `condition_grade == SCRAP` — `routes_service.py:67-73`
- §3.9 — insert — ambiguity — `covered_base_cents_snapshot` copied as-is, null when the order was never quoted — `routes_service.py:98`
- §3.9 — insert — ambiguity — `run_hours_delta` need not be a whole number — `routes_service.py:140`
- §3.9 — insert — ambiguity — RESUBMIT/REQUEST_INFO write null over `info_note` when omitted — `routes_service.py:244,256,261`
- §3.9 — insert — ambiguity — `adjudication_note` written null when omitted; `adjudicated_by_user_id` recorded on both APPROVE and DENY — `routes_service.py:294,306-307`
- §3.9 — insert — ambiguity — issuing a warranty credit posts without voiding, so it reprices nothing — `routes_service.py:284`

**The two mismatches worth flagging to the user:** the §2.9 repricing rule (PRD said "posts *or* voids", implementation reprices only on voids) and RETURN's `return_reason` (PRD read as required, implementation treats it as optional). Both were pinned to the implementation, per the alignment target.

**Orchestrator verification:** 417 → 417 lines, 84,447 → 90,400 chars (+5,953), 52 `ERR_` rows in §5, 5 top-level sections, file ends on the final error row — no truncation.

---

# Pipeline complete

All 9 steps done (Step 8 skipped by its own skip condition). Final state: 90/90 tests passing across 8 parallel per-test-server rounds, mutation-validated, with `PRD_COMPLETED.md` closing 36 PRD/implementation gaps.
