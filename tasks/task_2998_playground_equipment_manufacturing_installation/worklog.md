# Worklog — task_2998_playground_equipment_manufacturing_installation

## Step 1: Create task directory — 2026-09-06T04:00:06.324942439Z

Created tasks/task_2998_playground_equipment_manufacturing_installation/ and workspace/ (pre-assigned path, no index allocation).

## Step 2: Generate scaffold — 2026-09-06T06:11:53.770578967Z

All three scaffold artifacts for task 2998 are complete and pass the linter.

Files (all under tasks/task_2998_playground_equipment_manufacturing_installation/):

| File | Lines | Bytes |
|---|---|---|
| SCAFFOLD.yaml | 3189 | 162557 |
| SCAFFOLD_DIFFICULTY_DESIGN.yaml | 2593 | 174180 |
| SCAFFOLD_CORNER_DESIGN.yaml | 4209 | 290023 |

All three parse with yaml.safe_load. SCAFFOLD.yaml holds only §1.0–§1.7 keys (scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles) — no scaffold_difficulty_design / scaffold_corner_design keys. The other two each have exactly one top-level key.

Scaffold contents designed: 13 entities (12 with common_fields: true; InstallationInspection immutable) · 67 endpoints · 79 error codes · 49 validation rules (priority ladder 1→92) · 9 calculations (2 dual-variant: quote_pricing, warranty_coverage) · 16 state machines over 13 entities (4 cyclic, ManufacturingOrder with three parallel dimensions and a fork-join) · 2 concurrency_rules · 6 roles, role_model: segregation_of_duties, consistency_model: immediate, difficulty_level: expert_plus.

Instance counts:
- §1.8: 9 rule_ids / 19 instances, all with full recipes.
- §1.9: 9 sections / 65 instances — 44 with structured test_recipe, 21 excluded_because stubs. Section split: entities 10, state_machines 12, calculations 9, validations 8, endpoints 6, errors 11, rbac 3, cross_cutting_complexity_layers 5, consistency_model 1.

Verified programmatically: every stub cites a real §1.8 instance name and carries no test_recipe; no name collisions within §1.9 or against §1.8; every ${var} in a call path, payload, or as_user_id is bound by an earlier captures: (0 unbound).

Lint verdict (verbatim):
    Coverage
      §1.5 endpoints declared:    67
      §1.1 entities declared:     13
      §1.8 instances scanned:     19
      §1.9 instances scanned:     44
      Calls scanned (§1.8+§1.9):  1045

    VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.

Fixes made this pass:
- Corrected a bad assert in quote_accept_allowed_on_valid_until_date_and_refused_the_next_day: it claimed design_status == QUOTE_ACCEPTED, a state that does not exist — quote accept triggers no DesignProject transition, so it now asserts the project stays RENDERED.
- Two $.data.total_count captures on list endpoints would have tripped lint check (d) (list output requires $.data[N].field); switched to $.meta.total_count, matching the pagination convention used in the rest of the file.
- Updated a stale summary comment in SCAFFOLD.yaml's complexity_profile (it read "61 endpoints / 36 error codes / 8 calculations / 8 state machines" against actual 67/79/9/16).

Two notes for the orchestrator:
1. SCAFFOLD.yaml line 2 still contains the directive line "Generate task harder than expert level!" inside scenario: — kept because the brief required the scenario verbatim, but per the known leak hazard it should be stripped before Step 4 so it cannot reach PRD.md.
2. Cleanup: rm -rf .scratch/step2 only; .scratch/, worklog.md and workspace/ were left untouched, and nothing outside the three output files was modified.

ORCHESTRATOR ACTION (post-Step-2): per note 1 above, the orchestrator stripped the two lines "  Generate task harder than expert level!" and the following blank line from SCAFFOLD.yaml's scenario: block. Verified grep for "harder than expert" now returns 0 hits in SCAFFOLD.yaml and the file still parses with 13 top-level keys. The difficulty directive therefore cannot reach the doc generator in Step 4.

## Step 3: Copy shared files — 2026-09-06T06:11:53.777777583Z

Copied ./INSTRUCTION.md to tasks/task_2998_playground_equipment_manufacturing_installation/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-06T06:28:20.066Z

PRD.md is complete.

Deliverable: workspace/PRD.md — 492 lines, 110,478 bytes. Built in 10 bounded chunks (initial Write + 9 `cat >>` appends + one programmatic append for the two tables), so no output-cap truncation. The file ends on the final complete row of the §5 error table (`| ERR_WARRANTY_EXPIRED | 409 |`) — a clean section boundary, nothing mid-sentence, no audit footer.

Structure:
- # Playground Equipment Manufacturing & Installation API — Product Requirements Document
- ## 1. Introduction
- ## 2. Global Specifications & System-Wide Principles — 10 domain-derived subsections: 2.1 RBAC (6 roles, entity-backed InstallerOperator, both segregation-of-duties rules), 2.2 API Response Structure (verbatim block, all three sentinel literals intact), 2.3 Pagination, 2.4 Identity/Timestamps/Revision Counters (incl. the InstallationInspection no-version exception), 2.5 The Logical Plant Clock (2026-08-01T00:00:00Z startup default), 2.6 Nested Path Resolution & Referential Integrity (all 12 not-found codes), 2.7 Money/Geometry/Rounding, 2.8 Stale-Version Protection (both 412 paths), 2.9 One Governing Edition & Cascade Semantics, 2.10 Order of Rejection (16 normative priority bands)
- ## 3. Business Logic & Workflows — 9 subsections: 3.1 editions & catalogue (4-hop supersession cascade), 3.2 consultation/site/play areas, 3.3 placements, use zones, attachment DAG & validation, 3.4 renderings, community votes & revision rounds, 3.5 quoting (PROVISIONAL vs FIRM variants), 3.6 fundraising waterfall, 3.7 compliance certification, ordering & the production-floor fork-join, 3.8 installer network, installation, inspection & the 4-hop audit-failure cascade, 3.9 warranty (PRORATED vs STEP), retrofits & the 3-hop project-cancel cascade
- ## 4. Endpoint Definitions — 67-row, exactly-4-column table; descriptions rewritten to capability statements so no request/response bodies or trigger conditions leak
- ## 5. Error Code Catalogue — 79-row, exactly-2-column table

Coverage cross-check (programmatic, python3+yaml vs PRD.md):
- Endpoints: 67/67 paths present (table row count 67 exactly)
- Error codes: 79/79 present in the table and 79/79 also described in §1–§3 prose (none table-only)
- Entities 13/13, roles 6/6, calculations 9/9 (every declared output field named), state machines 16 with 52/52 distinct states and all 62 transitions narrated
- Validations: all 49 represented via their error codes

Hard Contracts:
- Contract 1 — Field-Name Coverage: PASS. 128 required identifiers (119 entity fields + endpoint inputs, deduped); 128/128 appear verbatim in backticks, and all 128 appear in §1–§3, not merely in the §4/§5 tables.
- Contract 2 — Rule Coverage: PASS. Validation priority order concentrated as the 16-band list in §2.10; both OCC rules in §2.8; all cross-entity cascades written hop-by-hop; sibling-branch symmetry given for close-review, the two prep dimensions, the four inspection outcomes and both dual-variant calculations; structured field content (color_options, use_zone_snapshot, certified_categories) specified in shape.
- Contract 3 — §3 Path Purity: PASS. Scanner over every backtick token in §3 found no token starting with / and no method+path combination. The single bare-method hit is `POST` used as the ComponentModel category enum value (posts, decks, slides…) at lines 174, 204 and 320 — never in endpoint-identifier position; endpoints in §3 are referenced only by state-transition framing, role+action verb, or capability description.

Two scaffold ambiguities resolved by judgement and worth flagging: (1) the certify state machine mentions a body standard_id while the endpoint's input is [] and its side effect names "the ACTIVE edition's id" — PRD specifies no body, resolving the single ACTIVE edition and failing ERR_NO_ACTIVE_STANDARD; (2) the lifecycle_status machine declares no state error code, so the PRD says an undeclared move is refused with HTTP 409 without inventing an identifier. Also note the scaffold's activate/supersede state machines list ManufacturerAdmin as actor while the endpoint roles list only ComplianceOfficer; §4 follows the endpoint roles (authoritative) and §3 prose says ComplianceOfficer.

Scratch dir .scratch/step4 removed; .scratch parent left in place. Nothing outside workspace/PRD.md was modified.

ORCHESTRATOR VERIFICATION (post-Step-4, anti-truncation gate): independently confirmed workspace/PRD.md is 492 lines / 110478 bytes, contains all five `## ` sections (1 Introduction, 2 Global Specifications, 3 Business Logic, 4 Endpoint Definitions, 5 Error Code Catalogue), and its last line is a complete markdown table row `| ERR_WARRANTY_EXPIRED | 409 |` — a real section boundary, not a mid-sentence cut. No regeneration needed. Also re-verified 0 occurrences of the difficulty directive string in PRD.md.

## Step 6: Generate implementation — 2026-09-06T07:10:58.583681424Z

NOTE (orchestrator): this step was killed mid-run by an infra API error ("Agent terminated early due to an API error") after ~10 modules and 30/67 endpoints, with app.py not yet created. Rather than respawning a fresh generator — which would make the implementation diverge from itself — the orchestrator computed the exact remainder (app.py missing + a normalized 37-endpoint gap, confirming 0 impl routes outside the scaffold set and all 10 existing modules parsing cleanly) and resumed THE SAME agent via SendMessage with that to-do list. The summary below is that agent's verbatim completion report.

Step 6 is complete. The implementation boots, all 67 endpoints are live, and both smoke runs passed end to end.

## Files delivered
`/home/ubuntu/github/CodingPRD/tasks/task_2998_playground_equipment_manufacturing_installation/workspace/implementation/`

| file | lines | role |
|---|---|---|
| `app.py` | 84 | Flask app, 11 blueprints, ApiError/HTTPException/Exception envelope handlers, foreground `0.0.0.0:$PORT`, reloader off |
| `store.py` | 259 | in-memory dicts, logical clock, traversals, `public()` |
| `errors.py` | 103 | all 79 PRD §5 ids + statuses |
| `envelope.py` | 56 | meta/response_type/data envelope, 204 helper |
| `auth.py` | 42 | headers, 6 roles, 401/403 |
| `validate.py` | 220 | shape checks, body-FK resolution, pagination, filters |
| `calc.py` | 383 | all 9 calculations incl. both dual variants, geometry, ledgers |
| `cascades.py` | 173 | supersession (4 hops), audit failure (4 hops), project cancel, installer revoke |
| `routes_standards.py` | 205 | 10 endpoints |
| `routes_projects.py` | 324 | 12 |
| `routes_areas.py` | 291 | 8 |
| `routes_renderings.py` | 91 | 4 |
| `routes_quotes.py` | 121 | 4 |
| `routes_pledges.py` | 69 | 3 |
| `routes_orders.py` | 153 | 7 (fork-join) |
| `routes_installers.py` | 105 | 4 |
| `routes_jobs.py` | 317 | 10 (incl. the 2 inspection endpoints added this session) |
| `routes_warranty.py` | 106 | 4 (new) |
| `routes_clock.py` | 29 | 1 (new) |
| `start.sh` / `requirements.txt` | 9 / 1 | `exec python3 app.py`, `Flask>=2.2` |

3131 lines of Python; every file passes `ast.parse`. No `__pycache__`, no seeded data, no disk/SQLite/tmp writes (grep-verified).

## Endpoint cross-check — 67/67, exact match
`grep @bp.route` totals 67 (standards 10, projects 12, areas 8, renderings 4, quotes 4, pledges 3, orders 7, installers 4, jobs 10, warranty 4, clock 1). I extracted the 67 rows of PRD §4's endpoint table and diffed them against the decorators normalised to `{id}`: **`ROUTE SETS IDENTICAL`**. A runtime check of `app.url_map` also counts exactly 67 method+path pairs across 11 blueprints.

## Smoke results (deep happy path + negatives)
Full chain on `PORT=51987`: standard->activate->model->certify->project->consultation->play-area->placement->validate->rendering->votes(25)->close-review->certify-compliance->FIRM quote->accept->pledge->collect->order->start-production->kitting->bagging(join)->ship->installer->book->reschedule->start->complete->install inspection PASS->audit PASS->warranty claim->decide->retrofit, plus all 14 list endpoints. **No failures.** Spot-verified derived values against the PRD prose: area cfh 120 / required depth 15 (POURED_RUBBER base 5, CLAY +3, floor 15); quote subtotal 535000 (2x250000 + 7 % colour uplift), freight 50500, discount 0, total 585500; allocation waterfall 50500 / 107000 / 428000 / 0 summing exactly to funds; join -> `READY_TO_SHIP` with `instruction_package_revision` = rendering round 1 and **one** version bump for prep+join; PRORATED claim elapsed 0 -> 100 % -> 500000 cents.

Negatives all returned the right id/status: 401 missing + unknown role, 403 `ERR_FORBIDDEN_ROLE` / `ERR_NOT_JOB_OWNER` / both `ERR_SEGREGATION_OF_DUTIES` paths, 412 `ERR_STALE_PROJECT_VERSION` and `ERR_STALE_INSTALLER_VERSION`, 409 `ERR_JOB_NOT_YET_STARTABLE` / `ERR_CLAIM_INVALID_STATE`, 422 `ERR_SURFACING_DEPTH_INSUFFICIENT` / `ERR_CLOCK_REWIND_FORBIDDEN` / `ERR_INVALID_FAILURE_DATE` / `ERR_INVALID_PAGINATION` (offset -1, limit abc, limit 101) / `ERR_INVALID_REQUEST` (malformed JSON, array body, missing field, bad instant), 404 unknown route, unknown path id, unknown body FK (`ERR_MODEL_NOT_FOUND`), DELETE placement -> **204 with empty body**, 405 wrong method. Inspection records were confirmed to expose neither `version` nor `updated_at`. Envelope verified verbatim, e.g. `{"meta":{"api_request_id":"req_H5EEQGRDPT7H4MELTPC2","api_request_timestamp":"2026-09-06T07:02:34.507Z","limit":5,"offset":0,"total_count":0,"has_more":false},"response_type":"array","data":[]}`. A second fresh process listed `total_count: 0`, confirming state is wiped per launch.

**Reaping:** `start.sh` uses `exec`, so each launch is a single pid. Ports 51987 / 51991 / 51993 were each killed by their own captured pid only (no `pkill`), `ss -ltnp` reported all three released, and a `/proc/<pid>/cwd` scan found no stray process under `task_2998`. `.scratch/step6` removed; `.scratch/step5` and the two top-level scratch files left untouched.

## PRD ambiguities resolved (additions from this session)
Beyond the 24 judgement calls already recorded (§2.10 as master rejection order, per-row version increments, wall-clock `created_at`, etc.), the ones decided here:

1. **Clock rewind** is judged at date granularity: refused when the requested instant's UTC **date** is strictly earlier than any recorded `installed_on`; a later instant on the same day is allowed. `current_utc` is echoed verbatim as supplied.
2. **Audit-SoD placement**: `ERR_SEGREGATION_OF_DUTIES` needs both the path row and the body `kind`, so it runs after path existence + shape but before every state check — unobservable, since no request can violate both tiers.
3. **Install-inspection surfacing gate applies to FAIL as well as PASS** (PRD §3.8 prose beats the scaffold, which lists it only on the PASS transition), and the ceiling is the **max** `required_surfacing_depth_cm` across the project's areas.
4. **Idempotent project hops on re-inspection**: a passing install inspection moves the project only from `ORDERED`, so a post-rework second pass does not re-bump an already-`INSTALLED` project; a passing audit sets `AUDITED`/`COMPLIANT` unconditionally (the compliance axis is a real change).
5. **Warranty claim ordering** follows §2.10 tier 14 exactly: `ERR_WARRANTY_PLACEMENT_MISMATCH` -> `ERR_PROJECT_NOT_INSTALLED` -> `ERR_INVALID_FAILURE_DATE`, with the FK pair resolved `project_id` then `placement_id` beforehand. Ownership is tested by walking placement->area->project.
6. **Claim decisions**: `ERR_CLAIM_INVALID_STATE` (state, tier 7) precedes `ERR_WARRANTY_EXPIRED` (fiscal, tier 15), and `DENIED` is available at 0 % coverage while `APPROVED` is not.
7. **Unmatched route/method** returns the standard error envelope with `ERR_INVALID_REQUEST` at HTTP 404/405 respectively; an unexpected internal fault returns `ERR_INTERNAL_ERROR` at 500 (a deliberately distinct id rather than mislabelling a bug as a client error), with the traceback on stderr.

ORCHESTRATOR VERIFICATION (post-Step-6): independently confirmed 67 `@bp.route` decorators across the 19 impl modules, all 19 files parse with ast.parse, 3131 total lines, and a grep for sqlite3 / open(...,'w') / json.dump / /tmp/ / pickle returns no hits (in-memory only, no seeded data). Booted the server myself on an unrelated private port 52771 via `bash start.sh`: it came up and returned the exact PRD envelope for GET /playground/standards?limit=2 with `total_count: 0` (proving no seeded data), then reaped by captured pid with a /proc/<pid>/cwd-verified stray scan; `ss -ltnp` confirms port 52771 released.

## Step 5: Generate unit tests — 2026-09-06T07:21:13.917896129Z

(Logged after Step 6 because Steps 5 and 6 ran concurrently in a single message and Step 6 returned first; entries are append-only, so the file order is chronological by completion, not by step number.)

Step 5 is complete. Both output directories are at the task root (nothing under `workspace/`), and `.scratch/step5` has been removed while the two sibling scratch files (`impl_routes.txt`, `missing_endpoints.txt`) were left untouched.

## Files written

**`test_helpers/`** — 3,306 lines

| file | lines |
|---|---|
| `__init__.py` | 124 |
| `types.py` | 427 |
| `api_client.py` | 398 (76 endpoint methods + `raw_get`/`raw_post`) |
| `api_errors.py` | 179 (79 error ids, scraped from the PRD table, registered via `set_error_http_status_map`) |
| `constants.py` | 128 |
| `test_users.py` | 101 |
| `factories.py` | 434 |
| `assertions.py` | 585 |
| `fixtures.py` | 930 (51 primitives + 5 tiers of composites) |

**`test_suite/`** — 7,812 lines, 18 test files + `conftest.py` (73 lines)

`test_01_quote_variant_pricing` 264 / 7 tests · `test_02_warranty_and_retrofit_pricing` 335 / 7 · `test_03_surfacing_depth_derivation` 209 / 4 · `test_04_design_and_installation_cycles` 401 / 8 · `test_05_supersession_and_audit_cascades` 439 / 13 · `test_06_validation_priority_conflicts` 325 / 6 · `test_07_boundary_precision` 331 / 6 · `test_08_cross_entity_state_gates` 338 / 6 · `test_09_temporal_overlap_and_travel` 392 / 9 · `test_10_conservation_invariants` 477 / 10 · `test_11_entity_crud_and_defaults` 383 / 11 · `test_12_state_machine_transitions` 668 / 12 · `test_13_pricing_and_allocation_calculations` 410 / 4 · `test_14_validation_boundaries` 469 / 5 · `test_15_endpoint_behaviours` 473 / 9 · `test_16_error_catalogue` 498 / 13 · `test_17_role_access_control` 588 / 11 · `test_18_cross_cutting_layers` 739 / 6

## Coverage

- **147 test functions**, 174 collected cases after parametrization, 147 `Design:` tags (exactly one per test).
- **19 / 19** difficulty instances translated, each with >=2 tests (range 3-7). **Zero skipped.**
- **44 / 44** non-stub corner instances translated, each with >=1 test. **Zero skipped.**
- All **21** corner stubs' `excluded_because.difficulty_instance` cross-references resolve to real difficulty instance names; no placeholders emitted.

## Verification performed

A scripted audit confirmed: no shortfall against either queue; every tag resolves to a non-stub instance; every docstring **ends** with its tag; every docstring carries a PRD citation whose >=8-word window survives a literal grep of `PRD.md`; zero `skip`/`skipif`/`xfail`; zero scaffold vocabulary. A static sweep proved all 18 files' `fx.`/`a.`/`f.`/`api_client.`/`ApiErrorId.`/`TEST_USERS[...]` references resolve against the real Stage 1 modules (0 unresolved). All 18 modules plus `conftest.py` import cleanly; `pytest --collect-only` collects 174 tests with no errors. Fixture-bug checklist clean: no string/float cents, no date-only clock instants, no whitespace-only headers, no envelope double-unwrap. Every out-of-set uppercase literal was traced to either an open-set PRD field (`color_options`, `code`) or a deliberate invalid-enum probe.

## Three fixes I applied after the authors finished

1. Two `test_01` docstrings and one `test_09` docstring cited PRD sentences under the 8-word verbatim threshold — replaced with longer verbatim spans (the freight formula, and the numbered booking-check sentence plus the order-of-rejection clause).
2. A `fixtures.py` comment read "project scaffolding"; renamed to "project preconditions" to keep scaffold vocabulary out of emitted code.

## Adjudications worth relaying to Steps 6-9

Authors resolved several recipe-vs-PRD conflicts **PRD-first**; the implementation must match the PRD, not the recipes:

- `ERR_INSTALLER_BOOKING_CONFLICT` and `ERR_USE_ZONE_OVERLAP` are asserted at **409** (PRD §3.8/§3.3 and the error catalogue), not the 422 the recipes claimed.
- `critical_fall_height_cm` includes **`DRAFT` as well as `VALIDATED`** placements (PRD line 212), so three recipe assertions of `0` for DRAFT-only areas were dropped rather than encoded.
- `fall_height_limit_is_per_age_band...` and `accessible_route_check_fires_only_when_the_project_flag_is_set` had **unreachable** recipe triggers (the PRD refuses the required precondition earlier); both were re-anchored to where the PRD makes the same rule reachable and unambiguous. Notably, the PRD states the `ERR_AGE_GROUP_MISMATCH` vs `ERR_FALL_HEIGHT_EXCEEDS_STANDARD` precedence **two contradictory ways** (§3.3 prose vs §2.10 item 12) — a latent PRD ambiguity Step 8/9 may want to close.
- One absolute version literal (`proj_ver_stale == 3`) contradicted §3.2's project-version bump on play-area create; only the normative `+1` relations are asserted.

ORCHESTRATOR VERIFICATION (post-Step-5): independently confirmed test_suite/ holds 19 .py files (18 test modules + conftest.py) and test_helpers/ holds 9, both at the TASK ROOT with no test_helpers/ or test_suite/ under workspace/. `python3 -m pytest test_suite --collect-only -q` collects 174 tests with no collection errors. grep counts 147 `Design:` tags and 0 occurrences of pytest.mark.skip / xfail across both directories.

## Step 7: Run tests and iterate — 2026-09-06T07:42:41.877597127Z

Clean sweep achieved. Exactly one file changed; `worklog.md` untouched (mtime still 07:21), pre-existing sibling scratch artifacts left intact.

## Summary

**Iterations run:** 2 (sweep -> one fix -> sweep).

**Tests deleted:** none. The single failure was a test-artifact arithmetic bug, not a PRD-coverage or derivability failure.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:**
- `test_suite/test_12_state_machine_transitions.py`, `test_cancelling_an_ordered_project_cascades_across_the_chain` — corrected the four *pre-cancellation* allocation-bucket expectations from `54250 / 66779 / 267115 / 11856` to `0 / 0 / 0 / 400000`, and replaced the docstring's cited PRD sentence with the no-quote branch it actually exercises.

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful.

**Diagnosis (the one real defect):** the test asserted the waterfall's *targeted-fill* branch, but the shared fixture `setup_ordered_project` (`test_helpers/fixtures.py:619`) collects the pledge **before** the quote is issued. PRD §3.6 recomputes the buckets only "on every collection and every refund" — quote issuance is not a recompute trigger — so at collection time the project had no `ISSUED`/`ACCEPTED` quote, and PRD's explicit branch applies: *"When no such quote exists, all three targeted buckets are zero and `alloc_contingency_cents` absorbs the entire collected amount."* Contingency legitimately held all 400000 cents.

Two independent checks confirmed the implementation rather than the fixture was right, so I deliberately did **not** reorder the shared fixture (which would have rippled across 11 setups and was not itself PRD-violating):
- `calc.recompute_fundraising` is called from exactly three sites — pledge collect, pledge refund, and project cancellation — matching PRD §2.9/§3.6/§3.9 precisely.
- `test_18_cross_cutting_layers.py::test_funds_and_allocation_buckets_reconcile_across_two_collects_and_a_refund` issues its quote *before* collecting and asserts the fill branch (`51750 / 6450 / 1800 / 0`); it passed in all rounds both before and after the fix, pinning the same semantics from the opposite direction.

The test's actual subject — the cancellation cascade (order cancelled, job cancelled, crew ledger to 0, pledge refunded, all four buckets to 0, accepted quote not expired, area stays LOCKED) — was untouched and still asserted exactly.

**Final sweep evidence:** rounds 1-8 all `passed=174/174`, union of failing tests 0, zero flakiness across rounds.

ORCHESTRATOR VERIFICATION (post-Step-7): ran {TASK}/summarize.py myself against workspace/implementation/results.{1..8}.json — all 8 rounds report passed=174/174 with listed_failures=0 and the union of failing tests is 0, and the summarizer's key cross-check (bad-count vs total-passed) raised no schema warning. Confirmed the results are from the POST-fix sweep, not a stale pre-fix one: test_suite/test_12_state_machine_transitions.py has mtime 07:30:13 while all 8 results files and workspace/SWEEP_DONE are 07:35:29. Confirmed workspace/implementation/ was not modified during Step 7 (newest impl mtime is app.py at 06:59:18, from Step 6), corroborating the "0 implementation fixes" claim. grep confirms 0 pytest.mark.skip / xfail across test_suite/ and test_helpers/, and the suite still collects 174 tests — nothing was dodged or deleted.

ORCHESTRATOR NOTE on Step 8 scope: the skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 impl fixes) is NOT met — there was 1 test_suite fix — so Step 8 runs. Its step_7_diff is that single item. Since there were 0 implementation fixes, a byte-identical PRD_FINALIZED.md would be a legitimate outcome here; only Step 9 must not be identical.

## Step 8: Finalize PRD — 2026-09-06T07:45:51.104115182Z

## Result

`workspace/PRD_FINALIZED.md` was created as a byte-identical copy of `workspace/PRD.md` (492 lines each, md5 `b36b0ebbda227a8a63ab6fd2efc96e80`, **0.0% delta**). **I made no edits** — the single Step 7 item was a test-side arithmetic bug over behavior the PRD already pins verbatim.

## Change list

None.

## Investigation of the one diff item

**Subject:** the fundraising allocation waterfall — (a) the set of recompute triggers, (b) targeted-fill vs. no-quote contingency-absorb branch selection.

**Impl paths enumerated** (all call sites and readers, not just the Step 7 site):
- `implementation/calc.py:227-259` — `recompute_fundraising`: sums `COLLECTED` pledges; `candidates = [q for q in store.project_quotes(...) if q["status"] in ("ISSUED","ACCEPTED")]`; `quote = candidates[-1] if candidates else None`; on `None` all three targets are 0, so `remaining` (= `collected`) lands entirely in `alloc_contingency_cents`.
- Grep for `recompute_fundraising` across all of `implementation/` -> exactly 3 call sites: `routes_pledges.py:45` (collect), `routes_pledges.py:67` (refund, guarded by `was_collected`), `cascades.py:157` (`cancel_project`).
- Grep for `alloc_`/`funds_collected` across all of `implementation/` -> only `routes_projects.py:71-75` (zero-init at creation) and `routes_orders.py:47` (read-only funding gate). No read-time re-derivation anywhere; the buckets are stored fields.
- `routes_quotes.py:43-118` (issue + accept) — confirmed neither path calls `recompute_fundraising`; issuance expires siblings and bumps the project version, acceptance bumps only quote versions.
- `cascades.py:120-157` (`cancel_project`) — refunds all `PLEDGED`/`COLLECTED` pledges, expires `ISSUED`-only quotes, then recomputes.
- `test_helpers/fixtures.py:619 setup_ordered_project` — confirmed the collect-then-issue ordering that produced the failure.

**Verbatim PRD sentences that already pin this (why no edit was needed):**
- §2.9 (line 137): "A project's `funds_collected_cents` and its four allocation buckets are re-derived from the project's collected pledges **on every collection and every refund**." Note the deliberate contrast in the same paragraph: the installer ledger gets the open-ended "on every event that could change it", the buckets get a closed two-item list.
- §3.6 (line 266): "**The allocation waterfall** is recomputed in full on every collection and every refund, never patched incrementally... **When no such quote exists, all three targeted buckets are zero and `alloc_contingency_cents` absorbs the entire collected amount.**"
- §3.5 (line 254 / 256) enumerate exactly what issuance and acceptance do — freeze the money fields, expire siblings, bump versions — and neither mentions the buckets, closing the "does issuing a quote re-run the waterfall?" question negatively.
- §3.6 collect/refund version rules ("both the pledge's and the project's `version` are incremented"; a merely-`PLEDGED` refund bumps only the pledge) confirm the buckets are stored and mutated at those events, not derived at read time — which is precisely the fork the failing test took.
- §3.9 (line 332) supplies the third trigger explicitly: pledges "move to `REFUNDED`, after which `funds_collected_cents` and all four allocation buckets are recomputed and therefore all become 0".

`cancel_project` recomputes *after* expiring quotes while §3.9 narrates it before — behaviorally identical, since every `PLEDGED`/`COLLECTED` pledge is refunded first, so `collected` is always 0 and all four buckets are 0 regardless of which quote is selected. Not a mismatch.

## Observation for Step 9 (deliberately not edited — outside this diff item)

`calc.py:237` selects the waterfall quote as `candidates[-1]` (store insertion order) whereas PRD §3.6 says "order the candidates by `created_at` ascending and take the last one". Two candidates can coexist (an `ACCEPTED` quote survives a later issuance, since issuance only expires `ISSUED` siblings), and with the logical clock two quotes can share a `created_at`, leaving PRD's ordering under-determined for ties while impl resolves by insertion order. Step 7 never exercised this, so it is out of Step 8's hard scope; flagging it for the full Step 9 scan.

ORCHESTRATOR VERIFICATION (post-Step-8): confirmed md5 of workspace/PRD.md and workspace/PRD_FINALIZED.md both b36b0ebbda227a8a63ab6fd2efc96e80 at 492 lines each. A byte-identical PRD_FINALIZED.md is the correct outcome here because Step 7 applied 0 implementation fixes and 0 deletions — there was no impl-pinned choice for Step 8 to write down. This identity is legitimate for Step 8 only; Step 9's PRD_COMPLETED.md must NOT be identical to its source, since an identical Step 9 output would mean the full scan never ran.

ORCHESTRATOR NOTE — two known PRD-internal issues carried into Step 9 as explicit targets (neither is in the Step 7 diff, so both were correctly out of Step 8's scope):
1. From Step 8: calc.py:237 picks the waterfall quote by store insertion order (`candidates[-1]`) while PRD §3.6 says to order by `created_at` ascending and take the last — under-determined for ties, which the logical clock makes reachable.
2. From Step 5's adjudication report: PRD states the ERR_AGE_GROUP_MISMATCH vs ERR_FALL_HEIGHT_EXCEEDS_STANDARD precedence two contradictory ways (§3.3 prose vs §2.10 item 12) — a PRD-internal self-contradiction that must be resolved to whichever order implementation/ actually applies.

## Step 9: Complete PRD — 2026-09-06T08:25:09.327690953Z

ORCHESTRATOR NOTE on method: because Step 8 emitted a byte-identical PRD_FINALIZED.md (Step 7 needed 0 implementation fixes), essentially ALL completeness work fell to Step 9. Rather than one subagent scanning 19 impl modules against a 492-line PRD in a single context, Step 9 was run as FOUR SEQUENTIAL passes over one shared PRD_COMPLETED.md, partitioned by implementation module, with pass 1 owning the `cp` and passes 2-4 forbidden from copying. A 4th reconciliation pass was added because module-partitioned passes cannot see each other's edits and therefore report cross-pass contradictions instead of fixing them. 65 edits from passes 1-3, then 7 reconciling revisions in pass 4.

Pass slices:
- Pass 1: app.py, store.py, errors.py, envelope.py, auth.py, validate.py, routes_standards.py, routes_projects.py, routes_areas.py
- Pass 2: calc.py, cascades.py, routes_renderings.py, routes_quotes.py, routes_pledges.py
- Pass 3: routes_orders.py, routes_installers.py, routes_jobs.py, routes_warranty.py, routes_clock.py
- Pass 4: reconciliation only (no new module audit)

### Pass 1 — 496 lines / 124,304 bytes (from 492 / 110,478), md5 f2faed25d39531fd9ac1e06e38cc7d8f
24 ambiguity-pins, 7 mismatch-revisions across 31 edits. Highlights: api_request_id pinned to `req_` + 20 chars of [A-Z0-9]; api_request_timestamp pinned to ...SS.mmmZ and sourced from WALL clock not the logical clock; response_type third value "error"; the 204 case corrected to a completely empty body with no envelope (was "empty data object" — a mismatch); unmatched route 404 / wrong method 405 both ERR_INVALID_REQUEST; 500 ERR_INTERNAL_ERROR deliberately outside the §5 catalogue; pagination integer-parsing, limit-before-offset order, offset>=total legality, has_more formula, exact/case-sensitive filter matching; created_at/updated_at read wall-clock UTC so moving the logical clock moves neither; multi-FK body resolution order (component_model_id before attached_to_placement_id); null==absent and booleans-are-not-integers; §2.9's ACTIVE-edition-resolver list corrected to include start-consultation; §2.10 item 14 carve-out for compliance certification; model certification settles certifiability BEFORE looking for an ACTIVE edition (mismatch); lifecycle inadmissible transition pinned to ERR_MODEL_NOT_CERTIFIABLE (PRD had only "HTTP 409"); cross-area separation evaluated BEFORE in-area overlap (mismatch); the 305 cm ceiling enforced ONLY on placement creation, never on recomputes (mismatch); conditional vs unconditional area version bumps; retrofit gate order rewritten.

**The named PRD self-contradiction is resolved.** Implementation applies FALL HEIGHT FIRST: routes_areas.py:69-70 raises ERR_FALL_HEIGHT_EXCEEDS_STANDARD (band ceiling), :72-73 again for the 305 cm ceiling, and only at :74-75 does it raise ERR_AGE_GROUP_MISMATCH; the retrofit path corroborates (:254-255 before :256-257). So §2.10 item 12 was ALREADY correct and unchanged; the wrong sites were the §3.3 prose AND a third site the brief did not name — the §3.9 retrofit prose. Both were revised to put fall height first with an explicit normative precedence statement cross-referencing §2.10 item 12. All three sites now agree; no half-fix remains.

### Pass 2 — 496 lines / 128,967 bytes (+4,663), md5 d0480ce0e56e0fd4c6b06d670b4fc544
8 ambiguity-pins, 7 mismatch-revisions across 15 edits. Highlights: §2.9's opportunistic-ACTIVE-edition readers corrected from two to three (FIRM quote issuance falls back to the project's accessible_route_required rather than raising ERR_NO_ACTIVE_STANDARD); buckets re-derived on every collection and on every refund OF A COLLECTED PLEDGE (mismatch — a PLEDGED refund runs no recompute at all, so buckets keep stale stored values); §3.1 hop prose corrected to the NON-RAISING recompute so no hop can fail on the 305 cm ceiling and no cascade fails partway, plus hop-3 projects and hop-2 areas bumped unconditionally; vote-batch response body is the rendering and the project version moves even when design_status was already COMMUNITY_REVIEW; close-review compares the STORED already-1dp-rounded community_approval_pct so an exact 59.95% stores 60.0 and approves; no lower bound on valid_until at issue time; quote acceptance gates re-ordered to the enforced order (quote ISSUED -> rendering ISSUED -> valid_until -> variant FIRM, so a PROVISIONAL-and-expired quote reports ERR_QUOTE_EXPIRED); issuance sibling sweep exempts the new row by identifier and spares ACCEPTED rows.

**The §3.6 candidates[-1] item is resolved, and the original diagnosis was refined rather than accepted.** store.all() (store.py:177) sorts by (created_at, _seq) and project_quotes goes through where()->all(), so candidates[-1] is NOT raw insertion order — it is created_at ascending with insertion sequence as tie-break. created_at is real wall-clock at ms resolution, so ties ARE reachable, and two candidates genuinely coexist because both sweeps spare ACCEPTED rows. The PRD sentence was correct but under-determined exactly at the tie; §3.6 now pins the tie-break to insertion order and states the governing quote is the latest-inserted survivor, never the ACCEPTED one merely for being accepted.

Verdicts on pass-1 handoffs: supersession hop status sets CONFIRMED correct against cascades.py (only the unconditional bumps and non-raising-recompute silence needed fixing); expire_issued_quotes self-exclusion made explicit; recompute_area_geometry_quiet never-raise property stated in §3.1 too; §2.10 item 14 order-creation use left to pass 3 as instructed.

### Pass 3 — 496 lines / 139,204 bytes (+10,237), md5 1d6ad6db34d49cec45ed4552c95e8887
16 ambiguity-pins, 3 mismatch-revisions across 19 edits. Highlights: clock-set response holds ONLY current_utc, echoed VERBATIM not normalized; rewind refusal at calendar-DATE granularity against installed_on alone, so a same-day earlier instant is accepted; order creation checks EVERY placement of the project, not just the subset the quote priced (mismatch), with the project derived from the quote's own project_id and no agreement check; start-production tests the order's axis before the project's, so a READY_TO_SHIP order reports ERR_ORDER_NOT_IN_PRODUCTION on a repeat prep advance; kit_line_count counts VALIDATED placement ROWS regardless of quantity; the join rides on the SAME single version increment (two prep advances = exactly two bumps, never three); shipping's only precondition is READY_TO_SHIP; booking admission checks reordered to ACTIVE -> booking conflict -> crew capacity -> CATEGORY LAST (mismatch; PRD had category second, impl and §2.10 item 13 put it last); installer version bumped unconditionally on reschedule and cancel; revocation does NOT zero the crew ledger (it reaches 0 only when every job is AUDIT_PASSED/AUDIT_FAILED/CANCELLED); surfacing gate is the MAX across areas, applies to FAIL as well as PASS, and never to a POST_INSTALL_AUDIT; branch asymmetry pinned — the install-pass project write is GUARDED on ORDERED while the audit-pass write is UNGUARDED and re-bumps; last_failed_inspection_kind is NOT cleared by a completed rework.

Handoff verdicts: (1) the kit_line_count/hardware_bag_total frozen-scope claim CONFIRMED falsifiable and fixed — ORDERED is in HOP2_PROJECT_STATUSES so a post-order supersession demotes a placement out of both counts and a retrofit restores it under a different model with a different hardware_bag_count; §3.7 now states the live-read rule instead of the false identity. (2) The order-creation ERR_PLACEMENTS_NOT_VALIDATED still matches item 14's original position, so pass 1's carve-out was correctly NOT extended. (3) Both clock findings confirmed and pinned.

### Pass 4 (reconciliation) — 496 lines / 140,414 bytes (+1,210), md5 7c2645f9330b9db1583979e4e20e42d8
7 targeted reconciling revisions.
- A1: chose to SOFTEN §2.9's global "examined but unchanged rows are not bumped" rather than patch locally, because the code has SIX unconditional-bump sites, not the three reported — supersession hop-3 projects (cascades.py:84) and hop-2 areas (:98-103), audit-failure hop-2 project (:164-165), installer on reschedule (routes_jobs.py:137) and cancel (:214), audit-pass project+installer (:289-296), and retrofit placement/area/project (routes_areas.py:280,283,288). No local carve-out list could stay true. Also rewrote §3.1's false uniqueness claim ("the one place where §2.9 gives way").
- A2: code decides — cascades.py:168-170 sets SUSPENDED with NO check of current status, while routes_installers.py MEMBERSHIP_TRANSITIONS has no `REVOKED ->` entry at all. So REVOKED is terminal to CLIENT calls only; §3.8's flat "terminal" clause now names the audit-failure cascade exception at the point a reader meets it.
- A3: verified routes_jobs.py:224-233 shape-checks the whole body before the segregation check; added the reciprocal note to §2.10 item 5 so items 3 and 5 are no longer one-sided.
- A4: §3.7's rendering selection omitted the tie-break; given §3.6's exact phrasing. Every other "most recent"/"latest" in the document was checked and is last-write-wins or max-of-integer, not a store-ordering selection.

JOB B — two further inconsistencies neither slice pass could see:
- §3.7's accessible-route test omitted the DRAFT-or-VALIDATED qualifier that §3.4 and §3.5 both state for the SAME helper (calc.py:151-163); added, with a clause noting the preceding all-validated gate makes it moot there.
- §2.10 item 8 attached ERR_PROJECT_NOT_EDITABLE to rendering issuance while routes_projects.py:174-175 raises ERR_PROJECT_INVALID_STATE (§3.4 was already correct); disambiguated inside item 8.
Checked and found consistent, no edit needed: all 79 catalogue HTTP statuses against errors.py (exact match) and all 31 inline "(HTTP nnn)" prose claims against the catalogue (zero mismatches); booking order vs item 13; rendering-issuance gate order vs items 11/12; the legitimately-different pledge-creation vs pledge-collection ERR_PROJECT_NOT_FUNDABLE trigger sets; the reschedule stale-version position; §3.3's conditional area bump; §3.6's acceptance rationale.
Incidental, not a doc defect: calc.recompute_area_geometry (the raising variant) is dead code — the 305 cm ceiling is enforced inline at routes_areas.py:72-73, which is what §3.3 describes.

### Final deliverable
workspace/PRD_COMPLETED.md — 496 lines / 140,414 bytes, md5 7c2645f9330b9db1583979e4e20e42d8. Net growth over PRD.md: +4 lines / +29,936 bytes (+27.1%), all of it in-paragraph pins.

ORCHESTRATOR VERIFICATION (post-Step-9, final integrity gate — checked independently, not taken from the subagents):
- md5 PRD.md = PRD_FINALIZED.md = b36b0ebbda227a8a63ab6fd2efc96e80; PRD_COMPLETED.md = 7c2645f9330b9db1583979e4e20e42d8. PRD_COMPLETED.md is NOT byte-identical to its source, so the scan demonstrably ran.
- Structure intact: exactly 5 top-level `## ` sections; §4 endpoint table 67 data rows; §5 error table 79 data rows. No table row was mangled by the 72 edits.
- Terminates cleanly on the complete final row `| ERR_WARRANTY_EXPIRED | 409 |` — not mid-sentence.
- Case-insensitive leak grep on the final deliverable: scaffold=0, test_recipe=0, difficulty=0, corner_design=0, expert=0. The Step 2 difficulty directive never reached any PRD artifact.
- `find` over workspace/implementation/, test_suite/ and test_helpers/ for anything modified after the 07:35:29 green sweep returns NOTHING — the implementation and test suite are frozen exactly as the clean 8-round sweep validated them, so the recorded 8x174/174 result still describes the shipped code. Step 9 touched only PRD_COMPLETED.md.

PIPELINE COMPLETE.
