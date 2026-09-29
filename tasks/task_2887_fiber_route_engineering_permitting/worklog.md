## Step 1: Create task directory — 2026-09-05T11:40:44.44147286Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2887_fiber_route_engineering_permitting and its workspace/ subdirectory. Index 2887 pre-assigned by the orchestrator prompt (no auto-allocation).


## Step 2: Generate scaffold — 2026-09-05T13:14:00.000Z

All three scaffold artifacts are complete and the linter is clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2887_fiber_route_engineering_permitting/`)
- `SCAFFOLD.yaml` — 2542 lines, §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1510 lines, single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4317 lines, single top-level key `scaffold_corner_design`

`worklog.md` and `workspace/` were not touched; scratch stayed in `/tmp/task_2887_fiber_scratch/`.

**Lint verdict** (`scaffold_lint.py`, final run)
```
Coverage
  §1.5 endpoints declared:    49
  §1.1 entities declared:     11
  §1.8 instances scanned:     18
  §1.9 instances scanned:     71
  Calls scanned (§1.8+§1.9):  951

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**§1.0–§1.7 envelope**: domain `fiber-route-engineering-permitting`, prefix `/`; 11 entities (Route, RouteSegment, FieldWalkout, PoleObservation, PoleAttachmentApplication, MakeReadyItem, PermitApplication, MoratoriumWindow, DesignPackage, SplicePoint, AsBuiltRecord — PoleObservation and MakeReadyItem immutable), 8 state machines, 2 OCC concurrency rules, 8 calculations, 26 ordered validations, 49 endpoints, 40 error ids, 6 roles (segregation of duties, all `identity: opaque`).

**§1.8 — 9 rule ids × 2 instances = 18**: `dual_variant_calc` 2, `combinatorial_formula` 2, `non_linear_state_machine` 2, `transitive_cascade` 2, `priority_pair_validation_conflict` 2, `boundary_precision_check` 2, `cross_entity_state_dependency` 2, `resource_temporal_overlap` 2, `compensating_invariant` 2.

**§1.9 — all 9 sections, 91 instances (71 full recipes + 20 `excluded_because` stubs)**: `entities` 12 (12+0), `state_machines` 17 (13+4), `calculations` 13 (8+5), `validations` 15 (13+2), `endpoints` 6 (6+0), `errors` 11 (4+7), `rbac` 8 (8+0), `cross_cutting_complexity_layers` 7 (5+2), `consistency_model` 2 (2+0).

**Verification beyond lint**: all 109 instance names unique across both design files; every stub's cited `difficulty_instance` resolves to a real §1.8 instance name; every `${var}` bound by an earlier `captures:` in the same recipe (custom closure scan, including asserts); every `expected_*_version` is a placeholder, never a literal; all 40 catalog error ids reachable from some instance (the six remaining 404s via one sweep instance, `ERR_SCOPE_LOCKED` / the two empty-collection ids in `errors`, `ERR_SEGREGATION_OF_DUTIES` in `rbac`, `ERR_STALE_ROUTE_VERSION` in the OCC layer); no forbidden concurrency vocabulary (one leftover "simultaneously" in the difficulty file was rewritten); no fractional-second instants; blank headers written as `""`.

Numeric literals were all computed by executing the formulas (`/tmp/task_2887_fiber_scratch/corner_calc.py`), e.g. AERIAL/URBAN_PAVED/400 ft → PRELIMINARY 630870 vs BID_READY 630872; admin-fee tier keyed on the pre-fee subtotal (500000 → 900 bp → 545000); make-ready days capped 130→120; spare ratio 192/288 → 6667 bp; MUNICIPAL_ROW RING_CLOSURE review 16 days due 2026-08-26T00:00:00Z vs RAILROAD 90 days due 2026-11-08T00:00:00Z; as-built variance exactly 500 bp accepted, 525 refused.

One design constraint worth flagging for the PRD step: validation p16 forbids overlapping MoratoriumWindows on the same (municipality_code, street_name), so the restoration calculation's severity-ranking tiebreak can never see two candidates — no corner instance claims multi-candidate ranking.

Orchestrator verification: grepped SCAFFOLD.yaml for the difficulty directive ("harder than expert level") — zero hits, so the Step-2-only difficulty instruction did not leak into the scaffold and cannot reach PRD.md.

## Step 3: Copy shared files — 2026-09-05T13:15:00.000Z

Copied ./INSTRUCTION.md to tasks/task_2887_fiber_route_engineering_permitting/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T13:28:00.000Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — **473 lines / 102,266 characters**, built with six chunked `cat >>` appends (no single giant Write).

Section headings: 1. Introduction / 2. Global Specifications & System-Wide Principles / 3. Business Logic & Workflows / 4. Endpoint Definitions / 5. Error Code Catalogue.
§2 subsections (11): 2.1 Personnel, Agencies and RBAC · 2.2 API Response Structure · 2.3 Pagination and Collection Ordering · 2.4 Resource Identity, Audit Fields and Version Counters · 2.5 The Logical Clock and Instant Representation · 2.6 Integer Cents, Basis Points and Rounding Discipline · 2.7 Optimistic Concurrency on the Owning Route · 2.8 Flat Addressing and Referential Resolution Order · 2.9 Validation Precedence · 2.10 Cascade Propagation and Rollup Integrity · 2.11 Conserved Quantities: The Budget Ledger and the Fiber Ledger
§3 subsections (9): 3.1 Establishing a Route and Building Its Segment Chain · 3.2 Field Walkout, Pole Condition, and the Re-Walk Cascade · 3.3 Choosing How to Build: Method Selection, Moratoria and Restoration · 3.4 Pole Attachment Applications and Make-Ready Engineering · 3.5 Right-of-Way Permitting Across Four Authorities · 3.6 Permit Denial and the Unwinding of Stamped Work · 3.7 Design Production: Fiber Allocation and Splice Placement · 3.8 Design Review, Stamping and Segregation of Duties · 3.9 As-Built Documentation and Closing the Network Records

Coverage confirmation: 11/11 entities (incl. explicit note that PoleObservation and MakeReadyItem carry only id/created_at); 49/49 endpoints in the §4 table (51 rows = 49 + header + separator); 8/8 state machines with all 40 from/to pairs incl. four cyclic loops (SCOPE_LOCKED→PLANNING, REJECTED→OPEN, REVISION_REQUESTED→SUBMITTED/→UNDER_REVIEW, STAMPED→DRAFT, METHOD_SELECTED self-loop); 8/8 calculations with pinned evaluation order and rounding sites (both scaffold worked examples re-derived and matching: bid-ready 394,295 vs preliminary 394,294; planned index 2500, live index 3208); 26/26 validations as a normative precedence list in §2.9; 40/40 error ids in §5 plus all 40 in §2/§3 prose beside their trigger conditions; 6/6 roles with identity: opaque translated and segregation of duties keyed on X-User-ID not role; 3/3 cascades hop-by-hop (re-walk depth 5, permit-denial depth 5, attachment-withdrawal depth 4); 2/2 concurrency_rules in §2.7 framed purely as stale-version.

Hard Contract reports: Field coverage PASS (105/105 entity fields, 55/55 request bodies, 10/10 query params, all enum values, 40/40 error ids, 6/6 roles). Rule coverage PASS (26/26 validations, 2/2 OCC rejections, 40/40 transitions, 8/8 calculations, 49/49 side_effects, 105/105 structured field content, 6/6 sibling-branch symmetry groups equal-density). Path purity PASS (748 backtick tokens scanned in §3; 0 paths, 0 bare methods).

Tail-boundary verification: file ends on the final error-table row `| ERR_BUDGET_EXCEEDED | 402 |`, byte-terminated with a clean `|\n` — no mid-sentence truncation. No "Hard Contract" section left in the file.

Constraints honored: neither design yaml opened/grepped/referenced; no sibling task read; scratch confined to /tmp/task_2887_fiber_prd/; nothing written outside workspace/; worklog.md untouched.

Orchestrator verification (guarding the known doc-generator truncation failure): independently ran `wc -l -c`, `grep -n '^## '` (all 5 sections present, monotonic line numbers) and `tail -6` — the file ends at a real section boundary (complete markdown table row), so no regeneration was needed. Also grepped PRD.md for "expert level": 0 hits, confirming the Step-2-only difficulty directive did not reach the PRD.

## Step 6: Generate implementation — 2026-09-05T14:02:00.000Z

Implementation complete and verified.

## Files written

All under `workspace/implementation/` — 13 modules, 2971 Python lines, plus `start.sh` (14) and `requirements.txt` (1, `Flask==3.0.3`):

| lines | file | role |
|---|---|---|
| 461 | `domain.py` | lookups, rollup recomputation, the 3 cascades |
| 367 | `api_field.py` | walkouts, pole observations, pole-attachment apps, make-ready |
| 351 | `api_route.py` | routes, segments, budget, lock-scope, method, bid-ready |
| 335 | `api_design.py` | design packages, splice points, as-builts |
| 275 | `calc.py` | all rate tables, enums, integer arithmetic |
| 266 | `api_permit.py` | permits, moratorium windows, `/_clock/set_current_utc` |
| 221 | `validate.py` | body-shape/type/enum/date primitives |
| 194 | `serialize.py` | 11 per-resource serializers |
| 137 | `envelope.py` | success/error envelopes, pagination |
| 134 | `store.py` | in-memory dicts, logical clock, `touch()` versioning |
| 102 | `errors.py` | 40-entry error-id → HTTP status map |
| 65 | `auth.py` | `X-User-ID`/`X-User-Role`, role gate decorator |
| 63 | `app.py` | app factory, 4 blueprints, error handlers |

## Endpoints: 49/49

Exactly the 49 the PRD declares (29 POST, 20 GET) — verified by enumerating the route table.

## Structure

- **State machines** are inline guards at the top of each action handler (`status not in (...)` → the resource's own `ERR_INVALID_*_STATE`), with transition side effects delegated to `domain.py`. RouteSegment's two parallel dimensions (`engineering_status` × `permit_status`) are advanced independently; `try_clear_segment_permit` (>=1 APPROVED and 0 outstanding) and `try_advance_route_to_construction_ready` (PERMITTING and all CLEARED and >=1 STAMPED) are the two derived promotions.
- **Calculations** live only in `calc.py` as pure functions over integer cents / basis points / centipoints, built on `div_round_half_up` and `div_ceil` — no float, no Decimal. Both costing variants are separate functions (`preliminary_cost_cents` single-rounding vs `bid_ready_construction_subtotal` per-100-ft-block rounding), as are planned vs live complexity index.
- **Validations** follow the 26-level precedence positionally: `auth.py`'s decorator (401 -> 403), then `v.check_body`/typed getters (400/422 shape), then path-FK `domain.get_*` 404s, then body-FK 404s, then business rules. No handler calls `touch()` before all of its validation has passed, so error paths never leak a mutation.
- **OCC** is `expected_route_version` on the two declared endpoints only (`construction-method`, `design-packages` create), compared against `Route.version` -> `ERR_STALE_ROUTE_VERSION` 412.
- **Cascades** are three functions in `domain.py` (`rewalk_rejection_cascade` depth 5, `permit_denial_cascade` depth 5, `attachment_withdrawal_cascade` depth 4). Idempotent per-record versioning is guaranteed by `store.touch()`, which dedupes on object identity in a per-request `g.touched_records` bucket, so a record reached by several hops is bumped exactly once.
- **Storage** is a single module-level `Store` of 11 dicts + logical clock (`2026-08-01T00:00:00Z`) + monotonic `_seq`. Nothing is seeded, nothing is written to disk — confirmed by a directory scan finding no `.db`/`.sqlite`/`.json`/`__pycache__` artifacts, and by a fresh boot answering `total_count: 0` on every collection.

## Verification

- `python3 -m py_compile *.py` — OK for all 13 modules; the generated `__pycache__` was removed.
- Two smoke suites (~123 assertions) run against `start.sh` on port 51887, both **FAILURES: 0**, the second suite run on a freshly restarted process to prove per-test-server isolation. Coverage: the full happy path through RECORDS_UPDATED; all three cascades including their compensating arithmetic (exact budget release on withdrawal, stamp voiding with `stamped_by_user_id` retained, live complexity index deliberately *not* reset by a rewalk); deemed decisions on both sides of the deadline instant (`ERR_REVIEW_WINDOW_OPEN` at exactly the due instant, municipal lapse -> APPROVED/`deemed`, waterway lapse -> DENIED); moratorium containment and open-cut veto; two-permits-one-segment clearing; SoD 403s; and the PRD's own worked numbers (preliminary 394,294 vs block-wise 394,295, make-ready 95,200/54 days, expedited `review_days` 16, planned index 1000/2500, live index 250/3208, spare ratio 8958/2917, variance 2000->40 bp).
- One real bug was found and fixed by the smoke run: `object_response(serialize.x(rec))` evaluated the serializer before the deferred version bump, so responses carried pre-bump `version`/`updated_at` — fatal for an OCC token clients must read back. The bump now lands inside `touch()`.
- The smoke server was killed by PID 2809341 resolved from `ss -ltnp | grep ':51887'`; port 51887 confirmed free afterwards. No broad `pkill` was ever issued.

Hard isolation was maintained throughout: `test_helpers/` and `test_suite/` were never read, listed, or grepped, and no sibling task directory was touched. Scratch stayed in `/tmp/task_2887_fiber_impl/`.

Orchestrator note: Steps 5 and 6 were launched as background agents; Step 6 returned first while Step 5 was still emitting test files. Isolation held — the impl agent never read test_helpers/ or test_suite/.

## Step 5: Generate unit tests — 2026-09-05T14:56:00.000Z

Stage 1 + Stage 2 generation for task 2887 is complete and fully verified.

## Files written (24 files, 9,205 lines)

`test_helpers/` — `__init__.py` 162, `api_client.py` 331, `api_errors.py` 98, `assertions.py` 453, `constants.py` 190, `factories.py` 301, `fixtures.py` 677, `test_users.py` 116, `types.py` 431.

`test_suite/` — `conftest.py` 98 (16 header fixtures + `api`), `test_01_route_definition_and_budget_ledger.py` 384, `test_02_segment_chain_and_scope_lock.py` 581, `test_03_field_walkout_and_pole_condition.py` 591, `test_04_construction_method_and_moratoria.py` 478, `test_05_segment_cost_variants.py` 336, `test_06_pole_attachment_make_ready.py` 544, `test_07_permit_filing_and_review_schedule.py` 731, `test_08_permit_denial_and_lapsed_windows.py` 369, `test_09_design_fiber_allocation_and_splicing.py` 511, `test_10_design_stamping_and_segregation_of_duties.py` 490, `test_11_route_complexity_indices.py` 405, `test_12_as_built_records_and_closeout.py` 264, `test_13_access_control_and_authentication.py` 400, `test_14_request_shape_and_collection_contracts.py` 264.

## Test counts

**108 tests total — Difficulty 37 / Corner 71**, 87 unique design tags, every tag matching a verbatim `name:` in its source yaml (0 unmatched).

Difficulty (18 instances, 0 stubs, every one carrying >=2 tests): boundary_precision_check 5, combinatorial_formula 4, compensating_invariant 4, cross_entity_state_dependency 4, dual_variant_calc 4, non_linear_state_machine 4, priority_pair_validation_conflict 4, resource_temporal_overlap 4, transitive_cascade 4.

Corner (91 instances, 20 `excluded_because:` stubs left untested, 69 of 71 live instances covered): state_machines 14, entities 13, validations 13, calculations 8, rbac 8, cross_cutting_complexity_layers 5, endpoints 4, errors 4, consistency_model 2.

## Skipped design instances (both fail condition 2 — PRD does not uniquely derive the asserted outcome)

- `Corner/endpoints/segment_listing_combines_the_engineering_status_filter_with_pagination` — PRD §4 declares no `engineering_status` or `permit_status` query filter on `GET /routes/{id}/segments`, and the instance places the pagination fields inside `data` whereas §2.3 puts them in `meta`.
- `Corner/endpoints/make_ready_items_listing_filters_by_work_class` — PRD declares no `work_class` filter on `GET /pole-attachment-applications/{id}/make-ready-items`.

## Accommodations where the design digest contradicted the PRD (PRD won)

1. Three corner instances specify `enclosure_type: "VAULT"`; PRD §3.7 declares only `HANDHOLE`, `AERIAL_SNOWSHOE`, `CABINET`. Substituted `CABINET` — every asserted figure (handhole_count, spare_ratio_bp, reserve, splice_point_count) preserved exactly.
2. One instance asserts a deemed decision records `decided_by_user_id` as the acting `X-User-ID`; PRD line 306 says the deemed path "leaves `decided_by_user_id` null, since no person decided anything". Asserted null.
3. `Corner/entities/pole_observation_is_immutable_and_exposes_no_version_field` asserts no `created_at`; PRD §2.4 says a `PoleObservation` carries "only `id` and `created_at`". The test asserts absence of `version` and `updated_at` and keeps `created_at`, and drops the instance's `requires_make_ready` listing-filter sub-assertion (no such filter is declared).

## Verification results (all green)

- `ast.parse` clean on all 24 files; `python3 -m py_compile` OK; `__pycache__` removed.
- `pyflakes` clean on all of `test_suite/*.py`; the only warnings anywhere are the intentional re-export "imported but unused" lines in `test_helpers/__init__.py`.
- Docstring tags: 108/108 have exactly one `Design:` line and it is the last line (0 problems, 0 dual tags, 0 dangling tags).
- PRD citations: 108/108 quoted sentences are verbatim whitespace-normalised substrings of `workspace/PRD.md`, all >=8 words.
- Scans clean for `scaffold` / `§` / `rule_id` / `design index` / `queue A|B` wording and for `pytest.mark.skip|skipif|xfail`.
- All 16 conftest fixtures resolve for every test signature (0 missing fixtures); every `fx.`/`api.` call verified against the real helper signatures.
- Output location: `ls -d test_helpers test_suite` OK; `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation` — nothing leaked there, and `workspace/implementation/` was never read, listed, or written. Server and pytest were never run.

Orchestrator verification: confirmed test_helpers/ and test_suite/ live at the task root (not under workspace/) and that no stray workspace/test_* directories exist.

## Step 7: Run tests and iterate — 2026-09-05T15:10:00.000Z

Iteration 1's sweep came back fully clean, so no diagnostic protocol steps were needed. Here is the summary.

## Summary

**Iterations run:** 1 (a single 8-round parallel sweep; it passed clean, so no fix/rerun cycles were required).

**Tests deleted:** none. No test failed in any round, so no PRD-coverage or unique-derivability adjudication was triggered.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

**Final sweep evidence** (all from `workspace/implementation/`):

| file | passed/total | failed | errors | skipped | duration |
|---|---|---|---|---|---|
| results.1.json | 108/108 | 0 | 0 | 0 | 189s |
| results.2.json | 108/108 | 0 | 0 | 0 | 190s |
| results.3.json | 108/108 | 0 | 0 | 0 | 189s |
| results.4.json | 108/108 | 0 | 0 | 0 | 190s |
| results.5.json | 108/108 | 0 | 0 | 0 | 189s |
| results.6.json | 108/108 | 0 | 0 | 0 | 189s |
| results.7.json | 108/108 | 0 | 0 | 0 | 189s |
| results.8.json | 108/108 | 0 | 0 | 0 | 189s |

Union of non-passing tests across all 8 rounds: empty. No flakiness signal — the same 108 tests passed in every round.

**Integrity checks I ran to confirm the clean sweep is not an artifact:**
- 108 distinct test names in the results exactly matches the 108 `def test_*` functions in `test_suite/` — nothing silently uncollected.
- `skipped == 0` in all 8 rounds, and zero `skip`/`xfail` occurrences anywhere in `test_suite/` or `test_helpers/` — no test was neutralized to pass.
- `implementation/` has no `sqlite`, `pickle`, `shelve`, `json.dump`, write-mode `open()`, or `/tmp` path anywhere. `implementation/store.py` is a plain in-memory `Store` of Python dicts whose `reset()` starts empty, with the logical clock initialized to the PRD's `2026-08-01T00:00:00Z` epoch and no entity seeded, preloaded or hardcoded. Combined with `--isolation per-test-server`, every test boots on wiped state.
- `implementation/start.sh` installs Flask only when missing, which is why 8 concurrent rounds of per-test reboots did not produce boot-contention timeouts.

Nothing in the sweep showed the setsid-reaping signature (no `Terminated` server logs, no rounds dying at a common wall-clock instant), and no round exhibited load-induced connection failures.

I did not touch `worklog.md`, and I did not read the SCAFFOLD files.

### Orchestrator independent verification of the clean sweep

Because a Step 7 agent has previously claimed a clean sweep while leaving no results files behind, the orchestrator re-verified from disk rather than trusting the report:
- All 8 `workspace/implementation/results.$i.json` exist (~33 KB each, same mtime cohort) and each parses to `passed=108 total=108 failed=0 errors=0 skipped=0`.
- `grep -rh "^def test_" test_suite/ | wc -l` = 108, matching `total` exactly — no silently uncollected tests.
- `grep -rn "pytest.mark.skip\|xfail" test_suite/ test_helpers/ | wc -l` = 0 — nothing was neutralized to reach green.
The sweep was launched via the prepared `workspace/sweep.sh` under `setsid nohup` (script file rather than an inline one-liner, to avoid the `--start-command` quoting bug that kills all 8 rounds at t=0).

## Step 8: Finalize PRD — SKIPPED — 2026-09-05T15:12:00.000Z

Step 8 is skipped per the skill's explicit skip condition. Step 7 exited on its FIRST 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes — zero iterations beyond the baseline. There is therefore no `<step_7_diff>` to hand off: no site where PRD.md failed to determine a behavior the implementation had already chosen was revealed by any test failure, so a minimal PRD_FINALIZED.md patch would have nothing to patch. No subagent was spawned and `workspace/PRD_FINALIZED.md` is deliberately absent.

Consequence for Step 9: its source file is `workspace/PRD.md` (not PRD_FINALIZED.md). Step 9 still runs in full — the residual silences the implementation resolved at generation time were never surfaced by test failures precisely because the suite passed first time, so the exhaustive PRD-vs-implementation scan is the only thing that can find them.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-05T16:05:00.000Z

Run as THREE SEQUENTIAL module-partitioned passes over one shared `workspace/PRD_COMPLETED.md` (a single-agent scan of a 473-line PRD against a 13-module implementation reliably under-scans and risks emitting a file byte-identical to its source). Pass 1 did the `cp` from `PRD.md` (Step 8 legitimately skipped, so no PRD_FINALIZED.md existed); passes 2 and 3 edited in place and were explicitly forbidden from re-copying. Partition: pass 1 = app/envelope/auth/errors/store/validate/serialize/api_route; pass 2 = api_field/api_permit + calc's cost, make-ready and permit-review functions; pass 3 = api_design/domain + calc's fiber, complexity and variance functions. Each pass received the previous pass's unresolved hand-offs as explicit to-dos.

### Cumulative result

| stage | lines | chars |
|---|---|---|
| PRD.md (source) | 473 | 102,266 |
| after pass 1 | 473 | 108,071 |
| after pass 2 | 473 | 113,281 |
| after pass 3 (final) | 473 | 121,904 |

Net **+19,638 chars (+19.2%)**, line count unchanged — every one of the 54 changes is an in-paragraph insert or revision. No new sections, no restructuring, nothing lost.

**Totals: 45 ambiguity-pins, 9 mismatch-revisions** (pass 1: 15 + 1; pass 2: 11 + 4; pass 3: 19 + 4).

### Pass 1 — infrastructure and route (15 pins, 1 mismatch)
- §2.1 — insert — ambiguity — role names matched exactly/case-sensitively, whitespace-only header = blank, `X-User-ID` unconstrained and recorded verbatim (untrimmed); plus the routing-level exception to "auth precedes everything": unrouted path -> `ERR_NOT_FOUND` 404, undeclared method -> `ERR_METHOD_NOT_ALLOWED` 405, even with no headers — auth.py:29-38, app.py:36-49
- §2.2 — insert — ambiguity — `api_request_id` = `req_` + exactly 20 chars from `A-Z0-9` — envelope.py:12,21-22
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the host real-time clock, not the logical clock, always 3 fractional digits — envelope.py:25-27
- §2.2 — insert — ambiguity — the four pagination keys are absent from single-resource envelopes; envelope key order not significant — envelope.py:30-60
- §2.2 — revise — ambiguity — error envelope covers 4xx and 5xx — app.py:49-53
- §2.3 — insert — ambiguity — `limit`/`offset` parsing: whitespace tolerated, explicit `+`/`-` accepted, empty value malformed; `offset` unbounded above; undeclared query params ignored — envelope.py:79-111
- §2.3 — insert — ambiguity — `created_at` ties broken by server insertion order, never by id — store.py:133-134
- §2.3 — insert — ambiguity — filter values exact case-sensitive strings, unvalidated (unknown value -> empty page); enumerated the filter set for the 9 route/segment listings; parent path param resolves before paging params — envelope.py:121-125, api_route.py:63-71,128-293
- §2.4 — insert — ambiguity — a record's `version` advances by exactly 1 per request regardless of how many direct writes + cascade hops touch it, and the bump lands before serialization — store.py:103-127
- §2.4 — insert — ambiguity — apart from `PoleObservation`/`MakeReadyItem`'s two omissions, every declared field is always present, `null` when empty (never omitted) — serialize.py:9-194
- §2.5 — revise — MISMATCH — instant input accepts 1-6 fractional-second digits and discards them (truncate to whole seconds); missing `Z`, `+00:00`, date-only still rejected. PRD had said only the no-fraction form is accepted — validate.py:17,178-194, store.py:65-67
- §2.9 (priority 3) — insert — ambiguity — absent/empty/`null` body -> `{}`; non-object JSON body malformed; explicit `null` on an optional field = omission vs shape error when required; booleans rejected for integers; strict calendar-date validity; unknown field rejected on name alone — validate.py:26-141,155-175
- §3.1 — insert — ambiguity — scope lock with `budget_authorized_cents` < 1 reports `ERR_BUDGET_EXCEEDED` (402); lock-scope declares no body fields — api_route.py:104,115-117
- §3.4 — insert — ambiguity — budget adjustment: `reason` required but may be blank, `delta_cents` may be 0/negative, zero delta still bumps `version`, and there is no route-status gate — api_route.py:82-98
- §4 — insert — ambiguity — every path matches with or without a trailing slash — app.py:23
- §5 — insert — ambiguity — three uncatalogued envelope-level identifiers: `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500 — errors.py:53-55, app.py:36-53

`errors.py`'s 40 catalogued status codes were cross-checked one by one against the §5 table: all 40 already agree (incl. the 402/412/422 oddities). No change needed there.

### Pass 2 — field and permit (11 pins, 4 mismatches)
- §2.3 — insert — ambiguity — filter sets for the three listings pass 1 left uncovered (`/walkouts/{id}/pole-observations` -> `requires_make_ready` only; `/pole-attachment-applications/{id}/make-ready-items` -> `work_class` only; `/moratorium-windows` -> `municipality_code` + `street_name` only), plus boolean-filter parsing: strip+lowercase, only `true`/`false` understood, any other value silently ignored leaving the listing unfiltered — api_field.py:74,216; api_permit.py:245-250; envelope.py:128-137
- §2.5 — revise — ambiguity — clock endpoint contract: `to_iso8601` the only declared and required body field; HTTP 200 with single-key `{"current_utc": ...}`; supplied fractional part truncated, not echoed or rounded — api_permit.py:259-266, store.py:66
- §2.9 (priority 3) — insert — ambiguity — required string fields must be non-blank (except where §3 explicitly allows blank, i.e. budget-adjustment `reason`), optional free-text accepts empty/whitespace verbatim; conditionally-required fields (`rejection_reason`) evaluated at shape priority, so 400 precedes 404 and the status gate — validate.py:60-80, api_field.py:141-146
- §3.2 — revise — MISMATCH — `POST /pole-observations` has no walkout-status gate; observations are accepted at `OPEN`/`SUBMITTED`/`ACCEPTED`/`REJECTED`, always recomputing rollups and bumping the walkout's version, but a late observation re-copies nothing onto the segment — api_field.py:80-113
- §3.2 — insert — ambiguity — walkout acceptance advances the segment `DRAFT -> WALKED` only from `DRAFT`; a segment already at `WALKED`/`METHOD_SELECTED`/`DESIGN_LOCKED` keeps its status while field data still refreshes — api_field.py:155-157
- §3.2 — insert — ambiguity — newest-`ACCEPTED`-walkout tie-break: on equal `created_at` the later-created walkout wins — domain.py:204-208
- §3.2 — insert — ambiguity — `rejection_reason` sent with an `ACCEPTED` decision is ignored, and an earlier rejection's reason survives a later acceptance — api_field.py:138-158
- §3.4 — insert — ambiguity — omitted/`null` `owner_note` leaves the existing note intact — api_field.py:270-271
- §3.4 — revise — ambiguity — `make_ready_items` elements: exactly three fields, non-blank `pole_tag`, `quantity` >= 1, non-object/extra-key/missing-key -> `ERR_INVALID_REQUEST`; the array is validated only on `ESTIMATED` and otherwise ignored however malformed — api_field.py:241-254,264
- §3.4 — revise — MISMATCH — `make_ready_days` is the SUM of the two considerations then capped, not "the larger of" — calc.py:235-238
- §3.4 — revise — ambiguity — grade-D rule scans EVERY `ACCEPTED` walkout on the segment (not just the newest); observations on `OPEN`/`SUBMITTED`/`REJECTED` walkouts ignored — domain.py:221-228
- §3.4 — insert — MISMATCH — on make-ready acceptance the segment's `version` advances only when the bid-ready re-derivation actually changes the stored figure (application and route always advance) — api_field.py:343-344, domain.py:255-265
- §3.4 — insert — ambiguity — withdrawal's `reason` is accepted and discarded — api_field.py:354-355
- §3.4 — insert — ambiguity — withdrawal cascade hop 3 touches the segment only when the re-derived figure differs — domain.py:456-458
- §3.5 — revise — MISMATCH — permit filing bumps permit + route versions unconditionally but the segment's only when the filing actually moved its permit dimension — api_permit.py:121-123
- §3.5 — insert — ambiguity — omitted/`null` `decision_note` leaves the existing note intact — api_permit.py:149-150
- §3.5 — insert — ambiguity — segment clearing runs out of `PENDING` only: a `BLOCKED` segment is not rescued by a later approval, a `CLEARED` one is left alone — domain.py:343-354

Pass 2 also settled a pass-1 open question: `envelope.bool_filter` is NOT dead code — `api_field.py:74` calls it for the `requires_make_ready` filter, the API's only boolean filter.

### Pass 3 — design, cascades and design-side calc (19 pins, 4 mismatches)
- §2.3 — insert — ambiguity — `/design-packages/{id}/splice-points` accepts `status` and `enclosure_type` and no others — api_design.py:89-90
- §2.9 (priority 3) — insert — ambiguity — the `station_feet` ceiling is the one shape rule that reads a body FK's target, so it is evaluated only when `segment_id` resolves — api_design.py:190-194
- §2.10 — revise — MISMATCH — hop sequences are the full chains, not the chains that always run; a failed condition silently skips that hop and its dependents — domain.py:381,413,419,428,444
- §3.1 — insert — ambiguity — planned index has exactly one rounding, at the end (contrast with the live index) — calc.py:193-197
- §3.2 — revise — MISMATCH — BOTH copied fields come from the newest-created accepted walkout, not the walkout just reviewed; `existing_conduit_available` is never reset — domain.py:211-219
- §3.2 — revise — MISMATCH — replaced "every hop is mandatory" with the `WALKED`/`METHOD_SELECTED`/`DESIGN_LOCKED` gate; a `DRAFT` segment stops the cascade after hop 1 — domain.py:381-383
- §3.2 hop 3 — insert — ambiguity — the five erased fields are the whole erasure (`accepted_obstruction_count`, `existing_conduit_available`, `permit_status` survive); segment touched unconditionally — domain.py:385-392
- §3.2 hop 4 — insert — ambiguity — route touched unconditionally, whether or not a rollup moved or hop 5 fires — domain.py:396-397
- §3.2 hop 5 — revise — ambiguity — a route already at `PLANNING` keeps its status/`scope_locked_at`/`planned_complexity_index`, yet hop 4 already advanced its `version` — domain.py:399-402
- §3.5 — insert — ambiguity — live index is 0 when `segment_count` is 0; the divisor is tested before the division — domain.py:180-182
- §3.6 hop 2 — insert — ambiguity — `NOT_REQUIRED` or already-`BLOCKED` segments are not touched at all, so a second denial does not bump the segment — domain.py:413-415
- §3.6 hop 4 — insert — ambiguity — strictly conditional on hop 3 having released `DESIGN_LOCKED`; otherwise a `STAMPED` package with `PLACED` work there keeps its stamp and hop 5 cannot fire — domain.py:428
- §3.7 — insert — ambiguity — `expected_route_version` has no integer floor; the 412 comparison precedes the route-status 409 — api_design.py:39,45-50
- §3.7 — insert — ambiguity — new package served at `version` 1 despite opening rollups — api_design.py:71-72
- §3.7 — insert — ambiguity — the design's route and the segment's route are never checked against each other; no coherence error — api_design.py:196-197
- §3.7 — insert — ambiguity — placement/voiding touch only the splice point and design package; segment and route untouched; new splice point at `version` 1 — api_design.py:221-224
- §3.7 — insert — ambiguity — splice-status gate reads before design-status gate — api_design.py:234-239
- §3.8 — insert — ambiguity — neither submit-for-review nor return-to-draft touches route or segment — api_design.py:167-171
- §3.8 — insert — ambiguity — `submitted_by_user_id` retained, `return_note` never cleared — api_design.py:138-142
- §3.8 — revise — ambiguity — route `version` advances unconditionally even when the status does not move — api_design.py:151-152
- §3.8 — insert — ambiguity — each demoted (superseded) package is touched; stamp identity retained — api_design.py:144-149
- §3.9 — insert — ambiguity — filing touches nothing else (route unmoved, record at `version` 1); no uniqueness rule on as-built records — api_design.py:275-291
- §3.9 — insert — ambiguity — `splice_point_count_field_verified` is never compared against `splice_point_count` — api_design.py:263,320
- §3.9 — revise — MISMATCH — the `RECORDS_UPDATED` hop is conditional on the route still standing at `CONSTRUCTION_READY`; a denial-demoted route is left untouched — api_design.py:329-333

Pass 3 resolved the asymmetry hand-off by pinning only the reachable half: `recompute_segment_walkout_fields`'s `walkout is None` arm is unreachable through the API (the recompute runs only on an acceptance, which guarantees an accepted walkout), so the PRD pins that both fields track the newest-created accepted walkout and that `existing_conduit_available` is never reset. It also checked the remaining cascades' "only when changed" conditionals and found them to run the OTHER way from make-ready acceptance: the re-walk cascade's hops 3 and 4 touch segment and route unconditionally, while `permit_denial_cascade` hop 2 is the one that no-ops.

### Orchestrator final verification

- `wc -l -c`: PRD.md 473 / 102,266 vs PRD_COMPLETED.md 473 / 121,904 — grew by 19,638 chars, lost nothing.
- `cmp -s PRD.md PRD_COMPLETED.md` -> DIFFERENT. This is the check that matters most: a byte-identical PRD_COMPLETED.md would mean the scan never ran.
- `grep -c '^## '` = 5, and `diff <(grep '^#' PRD.md) <(grep '^#' PRD_COMPLETED.md)` is empty — every heading and subheading survived, none added.
- `tail -3` ends on the complete final error-catalogue row `| ERR_BUDGET_EXCEEDED | 402 |` — a real boundary, not mid-sentence.
- No stray `workspace/worklog.md` was created by any subagent; the single append-only worklog lives at the task root.

Pipeline complete: Step 9 has written `workspace/PRD_COMPLETED.md`.
