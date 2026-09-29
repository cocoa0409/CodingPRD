# Worklog — task_3000_athletics_priority_points_seat_allocation

## Step 1: Create task directory — 2026-09-06T04:03:42.724486565Z

Created /home/ubuntu/github/CodingPRD/tasks/task_3000_athletics_priority_points_seat_allocation and its workspace/ subdirectory. Index 3000 was pre-assigned by the orchestration prompt; no index scan performed.

## Step 2: Generate scaffold — 2026-09-06T06:29:00.265721312Z

The Step 2 subagent died mid-run from an infrastructure API error, after completing SCAFFOLD.yaml (2864 lines) and SCAFFOLD_DIFFICULTY_DESIGN.yaml (2464 lines; 9 rule_ids, 19 instances) but with SCAFFOLD_CORNER_DESIGN.yaml only 505 lines / 1 of 9 sections written. No agentId was returned, so resumption by SendMessage was impossible. Orchestrator decision (autonomous, no user available): rather than regenerate all three files from scratch (which would discard ~5 MB-equivalent of verified work and re-roll the design), spawn a second, narrowly-scoped APPEND-ONLY agent to finish only the eight missing §1.9 sections, with SCAFFOLD.yaml and SCAFFOLD_DIFFICULTY_DESIGN.yaml declared read-only and md5-verified afterwards. That agent completed successfully.

Verified after Step 2: SCAFFOLD.yaml 12 entities / 12 state machines / 12 calculations / 27 validations / 56 endpoints / 39 errors / 6 roles / 2 concurrency rules; all three files parse as valid YAML; SCAFFOLD.yaml and SCAFFOLD_DIFFICULTY_DESIGN.yaml untouched by the resume agent (md5 ba413da25f5367289ede53f94c7ee5f0 / 146fbdd18163dfb7431732b4caec2c06).

Orchestrator post-step action: the difficulty directive line "Generate task harder than expert level!" had leaked into SCAFFOLD.yaml's `scenario:` block (a known scaffold-generator behaviour). Removed that one line (plus its trailing blank) from the scenario block so it cannot reach PRD.md via the doc generator; re-validated the YAML afterwards. Nothing else in the file was changed.

Resume agent's verbatim summary:

`SCAFFOLD_CORNER_DESIGN.yaml` is complete. All nine §1.9 sections are present in the mandated order, appended only (SCAFFOLD.yaml and SCAFFOLD_DIFFICULTY_DESIGN.yaml were never opened for writing; `worklog.md` and `workspace/` are intact).

## Deliverable
`/home/ubuntu/github/CodingPRD/tasks/task_3000_athletics_priority_points_seat_allocation/SCAFFOLD_CORNER_DESIGN.yaml` — 7192 lines, 434,148 bytes.

## Per-section counts

| section | total | non-stub | stub |
|---|---|---|---|
| entities | 15 | 15 | 0 |
| state_machines | 24 | 18 | 6 |
| calculations | 19 | 14 | 5 |
| validations | 20 | 16 | 4 |
| endpoints | 8 | 8 | 0 |
| errors | 17 | 9 | 8 |
| rbac | 10 | 10 | 0 |
| cross_cutting_complexity_layers | 7 | 4 | 3 |
| consistency_model | 3 | 3 | 0 |
| **TOTAL** | **123** | **97** | **26** |

958 structured API calls, 561 assert lines.

## Verification output
- `yaml.safe_load` succeeds; sections in exact required order → `True`.
- Instance-key hygiene: no unexpected keys; no stub carries a `test_recipe`; every non-stub recipe has exactly `setup`/`setup_api_calls`/`trigger`/`assert`; every instance has `claim_type` + `grounds`.
- Names: 0 duplicates within the file, 0 collisions with the 19 difficulty-file names.
- All 26 `excluded_because.difficulty_instance` leaves resolve to real names in `SCAFFOLD_DIFFICULTY_DESIGN.yaml`.
- Placeholder closure: 0 unresolved `${var}` across all 97 recipes (every reference resolves to an earlier call's `captures`); all capture paths are `$.data…`; every call carries an `as` role.
- OCC discipline: 0 bare-literal `expected_*_version` — all are `"${var}"`.
- Every `claim_type` maps to a real claim-extraction-guide row (no invented categories).
- `SCAFFOLD.yaml` md5 `ba413da25f5367289ede53f94c7ee5f0`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` md5 `146fbdd18163dfb7431732b4caec2c06`, mtimes 05:17/05:07 vs my 06:26 write — untouched.
- Cleanup: removed the empty `.scratch/step2b` only; `.scratch/step2` (another step's) left alone.

## Scaffold gaps found while replaying chains (none fixed — SCAFFOLD.yaml untouched)
1. **§1.5 vs §1.1 `Donor.status_effective_date`** — create side-effects say it is stamped; the field declares `default: null`. Recipes never assert it on create.
2. **`INFO_REQUEST_ROUND_CAP` undeclared** in any `calculations[].constants` block despite being referenced by priority 19, `ERR_INFO_REQUEST_LIMIT_REACHED` and `info_request_rounds` (0..2).
3. **`Donor.cumulative_giving_cents` semantics** — field says "as of the last recalculation run, CERTIFIED input set", but gift create/settle increment it unconditionally. Recipes use the incremental reading and never assert it immediately after a run.
4. **Counter drift on gate-CLOSED** — `BLOCKED → DENIED` does not decrement `pending_request_count` while `AWAITING_SELECTION → DENIED` does; that assert is omitted.
5. **`Section.seat_row_count <= seat_capacity` is violable** — the inventory formula counts DECOMMISSIONED rows, so a capacity-shrinking START_RESEATING breaks the field constraint. The relevant instance asserts the formula value.
6. **`created_at` uniqueness under a parked clock** — `donor_rank_position` claims ties are impossible; two donors created at the same parked instant share `created_at`. The tie-break recipe advances the clock 1 s between creates.
7. **No `selector_policy` row in the guide** even though §1.0 lists it as an active complexity layer; covered under `calculations` via `variant_selection`, and the section header says so.
8. **`rank_at_publish` ambiguity (resolved)** — the field description plus the certify cascade prove it copies the *stored global* rank, so a restricted POSTSEASON pool can give `slot_index 0` with `rank_at_publish 2`. Stated explicitly in the instance.
9. **New this session — second concurrent hold has no declared transition.** §1.2 declares only `AVAILABLE → HELD` for a pick, yet its precondition permits "HELD with spare `max_concurrent_holds` capacity". The self-loop's inventory side-effect is undeclared (a literal reading double-decrements `seats_available` to −1). The §1.3 identity `seats_available + seats_committed_count + decommissioned_seat_count == seat_row_count` disambiguates it; the OCC instance asserts `0 + 1 + 0 == 1` and says so in `distinguishing_aspect`.
10. **New this session — supersede counter tension (resolved).** `POST /athletics/relocation-requests` side-effects say "increments `pending_request_count`" while the `AWAITING_SELECTION → SUPERSEDED` transition says "leaves it unchanged"; they compose to a net 1, which the instance asserts explicitly.
11. **Note, not a gap:** §1.6 declares `ERR_FORBIDDEN_ROLE`, not the guide's generic `ERR_UNAUTHORIZED`; the `rbac` section uses the scaffold's own code.

Also worth flagging for later steps: there is no `GET /athletics/point-transfers/{id}`, so `ERR_TRANSFER_NOT_FOUND` is reachable only through a `PointsCertifier`-exclusive action endpoint; and `DisputeAnalyst` is the one role whose GET grant is hand-enumerated rather than "every GET", which the `rbac` section tests directly.

## Step 3: Copy shared files — 2026-09-06T06:29:00.281481117Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-06T06:44:38.489270402Z

Orchestrator truncation check (the known doc-generator failure mode): PRD.md is 408 lines / 99,933 bytes and ends on the final complete row of the §5 Error Code Catalogue table, which is the document's last section — a real section boundary, not a mid-sentence cut. Also grepped PRD.md for "harder than expert", "expert level" and "SCAFFOLD": zero hits, so neither the difficulty directive nor a scaffold reference leaked into the contract the implementer reads. No regeneration needed.

Subagent summary (verbatim):

Step 4 complete. `PRD.md` is written, verified non-truncated, and all three Hard Contracts pass.

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_3000_athletics_priority_points_seat_allocation/workspace/PRD.md`
- **408 lines / 99,933 bytes**
- Built in 14 incremental `cat >>` appends (never a single giant Write), with `wc -l` + `tail` after each.

## Section list

```
# Athletics Priority Points & Seat Allocation API — Product Requirements Document
## 1. Introduction                                                     (3)
## 2. Global Specifications & System-Wide Principles                  (11)
### 2.1. Callers, Identity and Role-Based Access Control              (13)
### 2.2. API Response Structure                                       (30)
### 2.3. Pagination, Filtering and Ordering of Collections            (79)
### 2.4. Common Resource Properties and the Logical Clock             (85)
### 2.5. Version Stamps and the Rejection of Stale Writes             (91)
### 2.6. Exactness: Cents, Points and Rounding                        (97)
### 2.7. Path Resolution and Referential Integrity                   (103)
### 2.8. The Order in Which Requests Are Checked                     (109)
### 2.9. Derived Counters, Cascades and Consistency                  (141)
## 3. Business Logic & Workflows                                     (149)
### 3.1. The Donor Book and the Donor Status Machine                 (151)
### 3.2. Gifts, Settlement and the Qualifying Input Set              (163)
### 3.3. The Annual Recalculation and the Priority-Point Formula     (171)
### 3.4. Two Figures, One Communication, and the Dispute Loop        (191)
### 3.5. Certification, the Ranking, and the Staleness Cascade       (205)
### 3.6. Moving Points Between Donors                                (217)
### 3.7. Venue Inventory, Section Pricing, and the Renovation Pipeline (231)
### 3.8. Selection Events, Slot Geometry, and the Pick               (253)
### 3.9. The Two Axes of a Seat Assignment, and Moving Between Sections (281)
## 4. Endpoint Definitions                                           (301)
## 5. Error Code Catalogue                                           (364)
```

9 subsections in §2 and 9 in §3, both inside the skill's 8–12 / 5–9 bands. §2.2 verified byte-identical to `section-2.2-response-structure.md` (diff clean apart from the trailing blank separator before §2.3).

## Coverage verified against SCAFFOLD.yaml

| Item | Scaffold | In PRD |
| --- | --- | --- |
| Endpoints | 56 | 56 (table = 58 rows incl. header+separator) |
| Errors | 39 | 39 (table = 41 rows incl. header+separator) |
| Calculations | 12 | 12, all constants pinned as literals |
| Validations | 27 | 27, as an explicit ordered ladder in §2.8 |
| Roles | 6 | 6 |
| State machines / transitions | 12 / 62 | 12 / 61 distinct pairs, all in prose |
| Concurrency rules | 2 | 2 (§2.5) |

## Hard Contracts

```
Contract 1 — Field-Name Coverage
  entities[].fields:            118 required, 118 present, 0 missing   PASS
  endpoints[].request_body:      63 required,  63 present, 0 missing   PASS
  endpoints[].query_params:      36 required,  36 present, 0 missing   PASS
Contract 2 — Rule Coverage
  errors in §2/§3 prose:  39 of 39                                     PASS
  roles named in prose:    6 of 6                                      PASS
  state values:           49 of 49                                     PASS
  enum values:            86 of 86                                     PASS
Contract 3 — §3 Path Purity  (1013 backtick tokens scanned)
  tokens starting with /: 0    bare HTTP method: 0    method+path: 0   PASS
```

55 of 61 transitions also carry literal `` `FROM → TO` `` arrow notation. The 6 without it are covered in equivalent prose and reading better that way: `REQUESTED → EXCEPTION_PENDING` is a creation-time entry state, not a live edge (the scaffold's own note says "creation lands directly in EXCEPTION_PENDING"), so an arrow would misdescribe it; the RelocationRequest `→ DENIED` pair reads "from either `AWAITING_SELECTION` or `BLOCKED`"; the rest use "from `HELD` to `AVAILABLE`" phrasing.

## Scaffold defects adjudicated (worth flagging downstream)

1. **`status_effective_date`** — the field says `default: null`, but `POST /athletics/donors` side effects set it from the clock at registration. Resolved in favour of the explicit endpoint side effect.
2. **`certified_base_points`** — the field says the certify call writes it; the `DRAFT → COMPUTED` transition and the `priority_point_score` calculation both say the recalculation run writes it. Resolved in favour of the run.
3. **`INFO_REQUEST_ROUND_CAP` is referenced but never defined** in any `constants` block (used by a transition, a validation, and `ERR_INFO_REQUEST_LIMIT_REACHED`). Inferred **2** from the `info_request_rounds` `0..2` constraint plus the error's "a third information request" wording.

Cleanup: `rm -rf .scratch/step4` only. `SCAFFOLD*.yaml`, `worklog.md`, and `workspace/INSTRUCTION.md` untouched; the two withheld design files were never opened.

## Step 6: Generate implementation — 2026-09-06T07:33:16.305795060Z

Launched concurrently with Step 5 in a single orchestrator message, so the implementation generator started before test_suite/ existed on disk and was physically unable to read it.

Subagent summary (verbatim):

Done. Final state of the deliverable.

## Module layout — `/home/ubuntu/github/CodingPRD/tasks/task_3000_athletics_priority_points_seat_allocation/workspace/implementation/`

| file | lines | role |
|---|---|---|
| `start.sh` | 8 (executable) | `set -euo pipefail`, `cd "$(dirname "$0")"`, guarded flask install, `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 82 | registers 7 blueprints, `/_clock/set_current_utc`, ApiError/HTTPException/Exception envelope handlers, `app.run(host="0.0.0.0", port=$PORT or 10000)` |
| `errors.py` | 83 | `ApiError` + all 39 error ids → HTTP status |
| `clock.py` | 76 | logical clock pinned to `2026-08-01T00:00:00Z`, `iso3` (exactly 3 fractional digits), instant parsing |
| `envelope.py` | 95 | `meta`/`response_type`/`data`, `req_`+20 alnum ids, limit(1..100, default 10)/offset pagination, `has_more` |
| `store.py` | 128 | 12 in-memory dicts, `new_row`/`touch`/`order_key`, 404 map, `get_path`/`get_body_ref`/`check_version` |
| `auth.py` | 98 | `X-User-ID`/`X-User-Role`, 6 roles, owner + segregation-of-duties checks, role groups |
| `num.py` / `validation.py` / `enums.py` | 55 / 197 / 54 | Decimal ROUND_HALF_UP helpers, §2.8-ordered field validation, enum vocabularies |
| `calc.py` | 391 | all 12 calculations (score, transfer caps, requirement/handling-fee bands, reseating share, pricing posture, event pool, rank sort) |
| `derive.py` | 169 | derived counters recomputed (never incremented), no version bumps |
| `serial.py` | 236 | per-entity response serializers |
| `routes_donors.py` | 306 | donors, household links, gifts, settle, renewals |
| `routes_recalc.py` | 245 | recalculation lifecycle, ledger, retention analysis |
| `routes_disputes.py` | 162 | dispute machine incl. INFO_REQUESTED↔UNDER_REVIEW cycle |
| `routes_transfers.py` | 143 | transfers, policy decision, approve, compensating reverse |
| `routes_sections.py` | 300 | sections, seats, reprice, renovation + reseating cascade |
| `routes_events.py` | 226 | selection events, publish-slots, gate, forfeit |
| `routes_assignments.py` | 488 | pick, occupancy, billing, relocation requests/decide |

Total 3,543 lines across 19 `.py` files + `start.sh` + `requirements.txt`. Every `.py` file passes `python3 -m py_compile`.

## Coverage audit
- **Endpoints: 56/56 implemented, 0 missing, 0 extra.** Verified programmatically by diffing Flask's `url_map` (path params normalised) against the PRD §4 table — output printed `PRD endpoints: 56  implemented: 56  missing: 0`, `extra routes not in the PRD table: []`.
- **Error codes: 39/39 reachable, 0 unreachable.** Each id in `errors.ERROR_STATUS` was traced to at least one raising module (including the shared helpers `invalid`/`invalid_state`/`stale`/`referenced_missing`/`check_version`/`get_body_ref`). The 16 `ERR_*_NOT_FOUND` ids are raised from `store.get_path`'s collection map; all 23 others are raised from the route/auth modules directly.

## Smoke test
Final run was a cold boot on a random high port (32858) against a fresh process, exercising ~124 assertions across 6 sections: envelope/pagination shape, RBAC and segregation-of-duties denials, §2.8 validation-priority ordering, OCC stale-version 412s, the logical clock, donor/gift/renewal lifecycle, recalculation run→communicate→certify, disputes (review/request-info/provide-info/decide), transfers with the DIVORCE cap and policy exception, selection events (publish, overlap, overflow, gate open/close), slot pick/forfeit, occupancy and billing axes, relocation grant, and the full renovation→reseating cascade. Result: **`SMOKE: every check passed`**.

Numeric spot-checks confirmed: score 32.50 + 25 (alumnus) + 5 (streak) = 62.50; DIVORCE transfer cap 0.50 → max 31.25; reseating 700000×7/12 = 408333 rounded per row before summing; `has_more`/`total_count` consistent; slot geometry using `slot_minutes + slot_buffer_minutes` stride; closed-interval seat holds vs half-open event windows.

Three smoke expectations (not implementation defects) were corrected during the run: a POSTSEASON event legitimately returning `ERR_NO_ELIGIBLE_DONORS` because step 20 precedes step 21; a relocation onto an ASSIGNED seat legitimately returning `ERR_SEAT_NOT_AVAILABLE` (step 17 before step 23); and a dispute block that used the wrong role/parent state (decide is PolicyCommittee-only, review requires a COMMUNICATED recalculation). **No implementation bug was found by the smoke suite**; every module compiled on its first `py_compile`.

## No seeded data
`store.py` declares 12 empty dicts at import time and nothing writes to them outside request handlers. A grep for `seed|preload|prepopulate|sqlite|json.dump|open(...,'w')` across all sources matched only two docstring sentences (in `app.py` and `store.py`) stating that nothing is seeded. There is no SQLite file, no JSON dump, no `/tmp` cache, no external store — a `start.sh` relaunch starts from zero rows, which the cold-boot smoke runs demonstrated repeatedly (an earlier warm re-run failed on duplicate emails; after switching to cold boots the same script passed).

## Process hygiene
The smoke server was reaped by PID only, after `readlink /proc/<pid>/cwd` confirmed the implementation directory: `reaped 2970708`, `port 32858 released`. `start.sh` uses `exec`, so the wrapper PID *is* the python process and `pgrep -P` found no child. Post-reap checks confirmed no listener on my port, the wrap PID gone, and no children. A final residual scan flagged two PIDs that had already exited before inspection — their cwd was the task root, i.e. the audit subshell matching its own `pgrep` pattern; nothing foreign was ever signalled and no broad kill was used.

Scratch cleanup: `rm -rf .scratch/step6` only — the parent `.scratch/` and its sibling `step2/`, `step5/`, `step7/` directories are intact. The `__pycache__` created by `py_compile` was also removed, leaving exactly the 21 deliverable files.

## Step 5: Generate unit tests — 2026-09-06T09:09:32.503814581Z

Launched concurrently with Step 6 in a single orchestrator message. Orchestrator verification after exit: md5 of the whole test tree identical across a 20 s interval (so the parent did not exit ahead of a live fan-out); 19 test_suite files + 9 test_helpers files; 260 `Design:` tag lines vs 260 `def test_` definitions; `pytest --collect-only` collects exactly 260 tests with no import or collection errors; `find workspace/ -name 'test_*'` empty, so neither test directory landed under workspace/ (a known Step 5 misplacement); no syntax errors under `ast.parse`. Stale `__pycache__` trees removed.

Subagent summary (verbatim):

Step 5 is complete. All 116 non-stub design instances are translated; nothing was skipped.

## Files written (task root, not workspace/)

`test_helpers/` — 9 files, 2,662 lines
| file | lines |
|---|---|
| `__init__.py` | 1 |
| `api_client.py` | 432 |
| `api_errors.py` | 111 |
| `assertions.py` | 442 |
| `constants.py` | 374 |
| `factories.py` | 374 |
| `fixtures.py` | 539 |
| `test_users.py` | 93 |
| `types.py` | 296 |

`test_suite/` — 19 files, 11,687 lines, **260 tests**
| file | lines | tests |
|---|---|---|
| `conftest.py` | 10 | – |
| `test_01_dual_variant_point_and_price_figures.py` | 291 | 8 |
| `test_02_composed_point_and_money_formulas.py` | 338 | 10 |
| `test_03_cyclic_and_parallel_state_machines.py` | 292 | 8 |
| `test_04_transitive_cascades.py` | 367 | 10 |
| `test_05_check_order_between_competing_refusals.py` | 257 | 7 |
| `test_06_boundary_values_and_precision.py` | 252 | 7 |
| `test_07_state_of_a_neighbouring_entity.py` | 250 | 7 |
| `test_08_window_conventions_at_the_boundary.py` | 266 | 7 |
| `test_09_compensating_actions_restore_totals.py` | 335 | 7 |
| `test_10_entity_shapes_defaults_and_identity.py` | 493 | 15 |
| `test_11_state_machines.py` | 1554 | 28 |
| `test_12_calculations.py` | 1489 | 37 |
| `test_13_validations.py` | 1500 | 33 |
| `test_14_endpoints.py` | 933 | 19 |
| `test_15_errors.py` | 309 | 9 |
| `test_16_rbac.py` | 1082 | 23 |
| `test_17_cross_cutting_layers.py` | 1102 | 15 |
| `test_18_consistency_model.py` | 567 | 10 |

Files 01–09 carry the 19 §1.8 (Difficulty) instances; files 10–18 carry the 97 §1.9 (Corner) instances, one file per section (entities 15, state_machines 18, calculations 14, validations 16, endpoints 8, errors 9, rbac 10, cross_cutting_complexity_layers 4, consistency_model 3).

## Coverage
- §1.8: **19 / 19** non-stub instances translated, 0 skipped.
- §1.9: **97 / 97** non-stub instances translated, 0 skipped. The 26 `excluded_because:` stubs were not touched (verified: zero stub names appear in any tag).
- Every one of the 260 tests carries exactly one `Design:` line as the final docstring line; 260 tags over 116 distinct instances (2–3 tests per instance).

## Assertion-level omissions (no instance was weakened or dropped)
Four design assertions were not emitted because the PRD does not uniquely derive them:
1. `assigned_seat_count` on merely-`HELD` rows — §2.9 defines it as `HELD` **or** `ASSIGNED` while §3.9 says confirming *increments* it; the two readings disagree. The seat-status counters are asserted instead.
2. "`Donor.version == 2` after a gift create" — §3.2 advances the donor's version only when the gift is recorded already `RECEIVED`; a defaulted `PLEDGED` create is PRD-silent. Rewritten as relative `before + 1` deltas around the settle/renewal/run/status-change writes only.
3. "`status_effective_date` is still null" — corrected to the registration clock instant per §3.1.
4. "`certified_points_sum` is null before certification" — corrected to `0.00` per §3.3 ("starts in `DRAFT` with … `certified_points_sum` at zero").

## Final verification output
```
ast.parse OK for 28 files (no bytecode written)
tests: 260 | Design tags: 260 | distinct: 116
citations: 441 | citation failures: 0
queue A: 19 queue B: 97 | missing: [] | dangling: []
docstring tag discipline: tests with docstrings: 260  violations: 0
pyflakes: clean (only the two intentional # noqa: F401 conftest re-exports)
py_compile: all 28 files OK
```
Also confirmed: no test files under `workspace/`; money/points sent as JSON numbers (no `_cents` string literals anywhere); no date-only literals where instants are declared; blank auth headers use `""`; `.scratch/step5` removed with `step2`/`step7` left intact; `worklog.md`, `SCAFFOLD*.yaml` and `PRD.md` untouched; `workspace/implementation/` never read.

## Step 7: Run tests and iterate — 2026-09-06T09:51:41.335585874Z

Orchestrator verification, performed independently of the subagent's own report (a prior run had a Step 7 agent claim a clean sweep with no artifacts on disk): `SWEEP_DONE` = 2026-09-06T09:43:09Z; all 8 `results.$i.json` present and each reporting `passed 260 / total 260, failed 0`; a row-level re-scan keyed on the runner's real `tests[].status` field found 0 non-passing rows across all 8 rounds combined (so the clean result is not an artefact of reading the wrong key). `pytest --collect-only` still collects 260 tests, i.e. nothing was quietly dropped. Every file in workspace/implementation/ has an mtime at or before 07:16, predating the Step 7 agent's launch, which independently corroborates its claim of 0 implementation fixes. No round log contains `Terminated`, so no round was reaped by a foreground Bash return — the setsid wrapper held.

Notable: the baseline sweep failed 19 tests deterministically 8/8 with 0 setup errors, which is the healthy shape — none of the known mass-fixture-wipeout signatures (money-as-string, date-only instants, envelope double-unwrap, duplicate-kwarg TypeError) appeared, and no load-induced flakiness appeared in any of the three sweeps.

Subagent summary (verbatim):

All 8 rounds green in the same sweep, verified from raw `results.*.json`. Implementation files are all untouched (timestamps predate this session) — every failure was a test-artifact defect.

## Summary

**Iterations run:** 3 full 8-round sweeps (iteration 1: 241/260 in all 8 rounds; iteration 2: 259/260; iteration 3: 260/260).

**Tests deleted:** none. All 19 failures traced to test-artifact bugs, not to PRD silence or non-derivability. Test count stayed at 260 throughout.

**Fixes applied to `test_helpers/`:** none — the helper layer was correct. Notably `fixtures.file_relocation_request` returning a raw `Response` is intentional (test_04/test_05 need it for error assertions); the bug was at the call sites.

**Fixes applied to `test_suite/`** (all in `/home/ubuntu/github/CodingPRD/tasks/task_3000_athletics_priority_points_seat_allocation/test_suite/`):

- `test_08_window_conventions_at_the_boundary.py` — `_three_events_touching_and_overlapping` published EV3's slots before EV2 was gated, so EV2's own gate correctly collided with EV3 (PRD §2.8 step 16 reads every *other* event in `SLOTS_PUBLISHED` **or** `OPEN`). EV3 now stays `DRAFT` and each test publishes it after EV2 is `OPEN`. Fixed 3 tests; the impl's half-open overlap predicate was already right.
- `test_11_state_machines.py` — 4 fixes:
  - `_staled_event_with_a_blocked_upgrade_request` and `_two_adjacent_events_and_a_pending_request` used `file_relocation_request(...)` as a dict (`TypeError: 'Response' object is not subscriptable`); now wrapped in `validate_success(..., 201)`. Fixed 7 tests.
  - `_two_adjacent_events_and_a_pending_request` filed a default `RELOCATION` into SEC-L (200,000¢ vs SEC-K's 100,000¢); PRD §3.9 types a higher-tier move as `UPGRADE`, which the helper's own name and the consuming assertion both expect. Fixed 1 test.
  - `test_the_reactivation_loop_preserves_the_donors_giving` lapsed with `effective_date` 2026-04-02 while the clock read 2026-04-01; PRD §3.1 admits a lapse only when `effective_date` is not later than the clock. Clock now advances to 2026-04-03 first.
  - `test_settling_then_clawing_back_reconciles_giving_to_zero` asserted a donor version chain of 2/3/4; PRD §3.2 advances the donor's version only for a gift recorded *already* `RECEIVED`, so a `PLEDGED` creation leaves it at 1. Corrected to 1/2/3.
- `test_12_calculations.py` — 2 fixes:
  - `_one_seat_holder_below_a_higher_ranked_bystander` called `invoice_and_pay` and then `confirm_assignment`, which invoices again → `ERR_INVALID_STATE`. Dropped the redundant call. Fixed 3 tests.
  - `test_the_lifetime_total_is_not_narrowed_by_the_cutoff` asserted `cumulative_giving_cents == 5000000` after a run, contradicting PRD §3.3 verbatim ("refreshed by the run to the values the CERTIFIED input set produced, so those two stored fields always describe the last completed run"). Renamed to `test_the_run_refreshes_the_stored_total_from_the_certified_input_set`; it now asserts 5,000,000 *before* the run (PRD §3.2's immediate credit) and 1,000,000 after (PRD §3.3's refresh), so both sentences are exercised.
- `test_18_consistency_model.py` — `test_the_aggregate_and_the_ranks_are_still_empty_before_the_certification` asserted `certified_points_sum == 0.00` after the run, citing only PRD §3.3's *DRAFT-creation* initialiser. PRD §2.9 states the sum "is recomputed whenever the `certified_points` of any donor it scored changes", which the run does. Replaced with the §2.9 identity (sum equals the live sum over the scored pair) and renamed to `test_the_certifier_stamps_are_still_empty_before_the_certification`; the genuinely covered assertions (`donors_processed_count`, null certifier stamps, null `rank_position`) were kept.

**Fixes applied to `implementation/`:** none. Three failures initially looked like impl defects and each turned out to be the implementation following PRD verbatim: the event-gate overlap check (§2.8 step 16), the run's refresh of `cumulative_giving_cents` from the CERTIFIED input set (§3.3), and the immediate recomputation of `certified_points_sum` (§2.9).

**Final round-by-round (sweep 3, `SWEEP_DONE` = 2026-09-06T09:43:09Z, all `results.*.json` written 09:43):**

| round | passed | total |
|---|---|---|
| 1 | 260 | 260 |
| 2 | 260 | 260 |
| 3 | 260 | 260 |
| 4 | 260 | 260 |
| 5 | 260 | 260 |
| 6 | 260 | 260 |
| 7 | 260 | 260 |
| 8 | 260 | 260 |

Raw-JSON cross-check confirms `failed: 0` and all 260 `tests[].status == "passed"` in every round — no flakiness anywhere across the three sweeps (all 19 iteration-1 failures were deterministic 8/8).

## Step 8: Finalize PRD — 2026-09-06T10:03:03.131185740Z

Step 8 was NOT skipped: the skip condition requires zero iterations beyond the baseline, and Step 7 ran three sweeps with ten test_suite fixes. It is nonetheless a light step here because Step 7 applied 0 implementation fixes and 0 test deletions, so most of its diff carries no PRD signal at all.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` is 4 lines — a single revised paragraph, one sentence changed inside §3.3 — and PRD_FINALIZED.md is still 408 lines ending on the last row of the §5 error table, so nothing was truncated or restructured.

Subagent summary (verbatim):

## Result

`/home/ubuntu/github/CodingPRD/tasks/task_3000_athletics_priority_points_seat_allocation/workspace/PRD_FINALIZED.md` written: **408 lines → 408 lines (0.0% line delta; 99,933 → 100,238 bytes, +0.31%)**. Exactly one sentence revised; everything else is byte-identical to `PRD.md`.

### Change

- **§3.3 (the run) — revise — the run refreshes `certified_points_sum`** to the sum of `certified_points` across the donors it scored, so the aggregate leaves its `DRAFT` zero at the run rather than at certification — `workspace/implementation/routes_recalc.py:98-99` (`_score_all` → `derive.recompute_recalculation_sum`), `workspace/implementation/derive.py:151-155`.

### Pre-edit search log (the one edit)

- **(a) Subject:** when and to what value `certified_points_sum` is set on a recalculation.
- **(b) Impl paths enumerated** (grepped `certified_points_sum|recompute_certified_points|refresh_recalculation_sums|recompute_recalculation_sum|certified_points"] =` across all of `implementation/`, then read each hit):
  - `routes_recalc.py:49` DRAFT initialiser `Decimal("0.00")`;
  - `routes_recalc.py:82-100` `_score_all` — sets each donor's `certified_points`, then recomputes the sum for **every** recalculation in the store;
  - `routes_recalc.py:202` certify — `recompute_recalculation_sum(recalc)` before `touch`;
  - `derive.py:127-155` — `recompute_certified_points` → `refresh_recalculation_sums(donor)` (only recalcs whose scored set contains the donor) and the standalone `recompute_recalculation_sum`; scored set = donors with a `CERTIFIED` ledger row (`derive.py:51-62`); nothing in `derive.py` bumps `version`;
  - callers of `recompute_certified_points`: `routes_transfers.py:112,113,138,139` (approve/reverse), `routes_disputes.py:156` (uphold);
  - readers: `serial.py:82`, `calc.py:390` (retention analysis echoes the stored field).
- **(c) Wording adjustment:** dropped my first draft's cross-recalculation clause and any version language. The run also refreshes *other* recalculations' sums and bumps no `version` for them; §2.9 already covers that generally, so the new sentence is scoped to "the donors it scored" on the recalculation being run and stays silent on version effects — no path above is mis-described, and §3.5's certification sentence and §3.3's DRAFT-zero initialiser both remain true.

### Items deliberately **not** patched (PRD already uniquely determines them)

- **Event-gate overlap (§2.8 step 16 / §3.8):** `routes_events.py:19-21,175-185` matches PRD verbatim — self-excluded, same recalculation, `SLOTS_PUBLISHED` or `OPEN`, half-open touching allowed. Step 7's failure was fixture publish ordering.
- **`request_type` UPGRADE vs RELOCATION:** `routes_assignments.py:373` validates enum membership only; nothing in create/decide/pricing reads it (`enums.py:41`, decide always `pricing_mode = MARKET`). §3.9 already says the filing *carries* it, and §2.8's ordered check list contains no tier check and no error code exists — pure fixture/assertion bug.
- **Lapse effective-date rule:** `routes_donors.py:154-155` rejects `effective_date > clock.now()` for `LAPSED` only, mapping to §2.8 step 9 / `ERR_INVALID_STATE`; §3.1 states the rule verbatim. The test simply had its clock behind its payload.
- **Gift create and the donor's `version`:** `routes_donors.py:241-243` touches the donor only for a `RECEIVED` create; §3.2 plus §2.4 ("increases … on each mutation that the specification says advances it") already pins 1/2/3.
- **Run refreshing `cumulative_giving_cents` / `consecutive_giving_years`:** `routes_recalc.py:89-90` writes the CERTIFIED variant's `qualifying_cents`/`streak`; §3.3's closing sentence says exactly that.
- **Double-invoice → `ERR_INVALID_STATE`** (`routes_assignments.py:329-332`) and the 201 on relocation-request create (§4) are both already pinned.

No implementation, test, `PRD.md`, or worklog file was modified; `.scratch/step8` was created and removed (siblings `step2`/`step7` untouched).

## Step 9: PRD completeness scan — 2026-09-06T10:52:04.821902625Z

### Orchestrator verification and decisions

Step 9 was run as **four sequential foreground subagents over one shared output file**, not as a single pass and not concurrently. Rationale, recorded as an autonomous decision: a single subagent cannot hold PRD.md (408 lines / 100 KB) plus 3,543 lines of implementation across 19 modules in one context and still have room to write dense revisions, and concurrent passes on one file lose each other's edits. The partition was **by implementation module**, so each pass owned a disjoint slice of both the code and the PRD sections that describe it:

- Pass 1 — `app.py`, `errors.py`, `clock.py`, `envelope.py`, `store.py`, `auth.py`, `num.py`, `validation.py`, `enums.py`, `serial.py` → PRD §1, §2.1–§2.9
- Pass 2 — `derive.py`, `calc.py`, `routes_donors.py`, `routes_recalc.py`, `routes_disputes.py` → §3.1–§3.5
- Pass 3 — `routes_transfers.py`, `routes_sections.py`, `routes_events.py`, `routes_assignments.py` → §3.6–§3.9 + the §4 preamble
- Pass 4 — reconciliation only; no new territory

Only pass 1 performed the `cp PRD_FINALIZED.md PRD_COMPLETED.md` setup; passes 2–4 were explicitly forbidden from repeating it, since re-copying would have destroyed every prior hunk. All four were restricted to targeted `Edit` calls (never a wholesale `Write`, which also risks the 64k output cap), were denied `SCAFFOLD*.yaml` and `worklog.md`, were forbidden from touching `PRD.md`, `PRD_FINALIZED.md`, `implementation/`, `test_suite/` and `test_helpers/`, and were each given their own scratch subdir under `.scratch/step9/` with deletion of the parent forbidden.

**Pass 4 was necessary and was not optional.** Passes 1–3, being partitioned, could only *report* contradictions that straddled their boundaries; pass 3 handed forward seven such items. Pass 4's whole scope was closing them.

Growth of the file across the four passes, verified by me at each handoff:

| after pass | lines | chars | diff hunks vs PRD_FINALIZED.md |
|---|---|---|---|
| 1 | 409 | 104,239 | 15 |
| 2 | 409 | 109,930 | 28 |
| 3 | 409 | 128,646 | 54 |
| 4 | 411 | 133,859 | 58 |

Final independent verification (not taken from any subagent's report):

- `wc -l -c` → `PRD.md` 408 / 99,933; `PRD_FINALIZED.md` 408 / 100,238; `PRD_COMPLETED.md` **411 / 133,859**. The completed PRD is longer than its input in both lines and bytes and was never shortened at any handoff.
- `cmp -s PRD_FINALIZED.md PRD_COMPLETED.md` → differs. **58 diff hunks.** A byte-identical PRD_COMPLETED.md would have meant the scan never ran; that failure mode did not occur.
- `tail -3` → the file still ends on the last row of the §5 error-code table, `| ERR_SECTION_CAPACITY_EXCEEDED | 409 |`. Five `##` section headings intact.
- `PRD.md` (mtime 06:43) and `PRD_FINALIZED.md` (mtime 09:55, 100,238 bytes — its Step 8 size) were both untouched by all four passes.
- `find implementation/ test_suite/ test_helpers/ -newermt "2026-09-06 09:50"` → **empty**. Step 9 changed no code and no tests, as required; the 260/260 green state from Step 7 is therefore still the state of the tree.
- Survival check on eight distinctive phrases seeded by passes 1–3 (`certified_points_sum`, `rank_position`, `EXCEPTION_PENDING`, `SUPERSEDED_BY_NEW_HOLD`, `first_occupied_cycle_year`, `ERR_NOT_RESOURCE_OWNER`, `UNDERWATER`, `ERR_SEAT_DONATION_SHORTFALL`) → all present, none clobbered by pass 4's in-paragraph edits.
- I re-derived pass 4's factual claims from source rather than trusting its report: `auth.DONOR_AND_OFFICER = (DONOR, DEVELOPMENT_OFFICER)` with exactly **three** call sites (`routes_events.py` forfeit, `routes_disputes.py` create, `routes_assignments.py` relocation-request create) — so §2.1's original "a `PlatformAdmin` may also perform every development-office write" was genuinely false and pass 4 was right to narrow it, and right that pass 3's flag under-counted the exclusions at two; exactly **three** `require_owner` call sites, all `get_path`-before-ownership; every write to a section's `status` is `"OPEN"` (creation, COMPLETE, ABANDON) or `"UNDER_RENOVATION"` (SURVEY), so `CLOSED` is unwritable while remaining a member of `SECTION_STATUSES` and therefore an accepted list filter; and `RESEATING` appears in `RELEASE_REASONS` and is validated on input by `change_occupancy` but is never assigned by the service — pass 4 was correct to overrule pass 3's "never written by any code path" flag as partly wrong (a caller *can* set it) instead of documenting an unreachable value.
- Pass 4 also correctly declined two of the seven flags: §2.4 was left alone because `_certification_cascade`'s `sorted(event_ids)` iteration has no observable dependence on order (per-event work reads only its own slots, `newly_stale` is a set, no early exit, no shared counter, and `updated_at` comes from a logical clock that does not self-advance), and the §3.3/§3.5 version-stamping paragraphs were confirmed mutually consistent against `_score_all` and `_stamp_ranks`. Declining to edit on evidence is the correct outcome for those two; forcing an edit would have introduced a false statement.

Step 9's deliverable, `workspace/PRD_COMPLETED.md`, is written. This completes the pipeline.

### Subagent summary — Pass 1 of 4 (donors / recalculations core modules)

Pass 1 of 4 complete. `PRD_COMPLETED.md` was created from `PRD_FINALIZED.md` and edited only in my partition's territory.

## File state
- `PRD_FINALIZED.md`: 408 lines / 100,238 chars
- `/home/ubuntu/github/CodingPRD/tasks/task_3000_athletics_priority_points_seat_allocation/workspace/PRD_COMPLETED.md`: 409 lines / 104,239 chars (**+1 line, +4,001 chars**)
- Ends on `| ERR_SECTION_CAPACITY_EXCEEDED | 409 |`; diff shows exactly my 15 intended hunks (14 in-paragraph revisions + 1 new bullet in §2.2).

## Counts
- ambiguity-pins: **12**
- mismatch-revisions: **3** (§2.3/§3.5 `created_at` uniqueness, §2.9 eligibility scope, §2.9 sum-not-frozen)

## Changes
- **§2.2** — revise — ambiguity — `api_request_id` is `req_` + 20 uppercase-alnum chars; `api_request_timestamp` is read from the logical clock, not wall time — `envelope.py:18-26`
- **§2.2** — insert — ambiguity — unknown path / unsupported method answer the error envelope with `ERR_INVALID_REQUEST` at HTTP 404/405, explicitly carved out of §5's 400 pairing — `app.py:58-70`
- **§2.3** — revise — ambiguity — empty `limit`/`offset` values read as omitted; non-integer values are 400 — `envelope.py:68-87`
- **§2.3** — insert — mismatch — `created_at` ties (logical clock does not self-advance) are broken by write order, never by `id` — `store.py:64-76`
- **§2.3** — insert — ambiguity — empty filter value = absent; bad enum/non-numeric filter → 400; undefined query params ignored — `validation.py:156-197`
- **§2.4** — revise — ambiguity — clock endpoint answers 200 with empty `data`; accepted inbound instant forms (Z/offset/any fractional width/naive=UTC/bare date=midnight UTC), normalised to UTC, always emitted at 3 fractional digits — `clock.py:30-68`
- **§2.6** — insert — ambiguity — cents are integer JSON numbers, points/ratios/caps are JSON numbers not strings; numbers may arrive as numeric strings; >2-dp point inputs are rounded half up *before* range checks rather than rejected; fractional value where an integer is required → 400 — `num.py:45-55`, `validation.py:87-110`
- **§2.8 step 1** — revise — ambiguity — a whitespace-only header counts as empty (401) — `auth.py:50-55`
- **§2.8 step 4** — revise — ambiguity — a null comparand (unreviewed dispute) cannot fire SoD; evaluation falls through to step 9 — `auth.py:70-74`
- **§2.8 step 6** — revise — ambiguity — absent/empty body reads as `{}`; non-object body malformed; explicit JSON `null` is treated as omission — `validation.py:16-45`
- **§2.9** — insert — ambiguity — recomputing a derived counter on a resource not named at that transition does **not** advance its `version`/`updated_at` — `derive.py:1-6`
- **§2.9** — revise — mismatch — eligibility is re-judged only on `HELD`/`ASSIGNED` rows; a `RELEASED` row keeps its last `eligibility_status` — `derive.py:100-112`
- **§2.9** — revise — mismatch — "donors it scored" = donors with a `CERTIFIED` ledger generation for that recalculation, and `certified_points_sum` keeps being recomputed after certification (live, not frozen) — `derive.py:51-57,140-148`
- **§3.4** — revise — ambiguity — `info_note` added to the dispute's null-at-creation field list (it is a visible response field) — `serial.py:101`
- **§3.7** — revise — ambiguity — `reseated_donor_count` / `reseating_invoice_total_cents` open at zero and are never-null integers — `serial.py:143-144`

## Deliberately left alone (already pinned uniquely)
The 39-entry error-id → status map matches §5 exactly (`errors.py`); the 6 role names and their spelling (`auth.py:9-23`); ownership fires only for `Donor` callers; SoD compares `X-User-ID` values; `id` = bare UUID, `created_at`/`updated_at` 3-digit ISO, `version` starts at 1 and +1 per mutation, ledger entries carry neither `updated_at` nor `version` (`store.py:41-61`, `serial.py:56-68`); per-collection 404 codes vs `ERR_REFERENCED_ENTITY_NOT_FOUND` for body refs (`store.py:83-115`); OCC compares against the parent's current `version` (`store.py:123-128`); half-up rounding at 2/4 dp, `round_cents`, floor-at-zero (`num.py`); all enum vocabularies and the donor transition set (`enums.py`) match the prose verbatim; `limit` 10/1/100 and `offset` 0 defaults and bounds; `has_more`/`total_count` semantics; every serializer's field roster matches the §3 field names; section counter invariant and `pricing_posture` recompute trigger (`derive.py:68-85`); `pending_request_count` definition (`derive.py:134-137`); role-set constants in `auth.py:80-98` match every §4 table row I cross-checked against `auth.require(...)` call sites.

## Cross-partition notes for passes 2/3 (I did not edit these)
1. **`sort` grammar on `GET /athletics/donors`** (`routes_donors.py:29-70`) is entirely unpinned by §2.3: a leading `-`, or a `:`/space/comma/`_desc`/`_asc` suffix, selects descending; the sortable set is exactly 11 stored fields; an **unrecognised sort field silently falls back to `created_at` ASC** rather than returning 400; `rank_position` sorts nulls last. Worth pinning in §2.3.
2. **`GET /athletics/selection-slots`** orders by `(slot_index, created_at, write order)` (`routes_events.py:70`) — the secondary keys are unstated in §2.3.
3. `routes_recalc.py:83` scores donors in `created_at` ASC order (`by_created_at`), which fixes ledger-row and rank-stamp ordering; §3.3 does not name a scan order.
4. `calc.py:226-234` ranking uses `order_key` (created_at + write order) as its final key, consistent with my §3.5 revision — pass 2/3 should not re-introduce a "created_at is unique" claim.agentId: a671c53d6ed986e9c (use SendMessage with to: 'a671c53d6ed986e9c', summary: '<5-10 word recap>' to continue this agent)
<usage>subagent_tokens: 112437
tool_uses: 36
duration_ms: 336210</usage>

### Subagent summary — Pass 2 (recalculation ranking, disputes)

Pass 2 complete.

## File state
- `workspace/PRD_COMPLETED.md`: **409 lines / 104,239 chars → 409 lines / 109,930 chars** (+5,691). All edits are in-paragraph; no new sections, no new lines, still ends on `| ERR_SECTION_CAPACITY_EXCEEDED | 409 |`.
- `diff PRD_FINALIZED.md PRD_COMPLETED.md` = **28 hunks**: pass 1's 15 all intact (verified by grepping seven of its distinctive phrases, each present exactly once) + my 13 new hunks. Two of my edits landed inside lines pass 1 had already revised (§2.3 line 84, §3.4 line 198) and were applied as inserts around its wording.

## Counts
17 changes: **16 ambiguity-pins, 1 mismatch-revision**.

## Changes
- §2.3 — revise — ambiguity — full `sort` grammar on `GET /athletics/donors`: the 11-field sortable set, the `-`prefix / `:`,space,comma / `_desc`,`_asc` spellings, `desc`/`descending` as the only descending words, silent fallback to `created_at` ASC for an unrecognised field (not a 400), stability of ties, and `rank_position` nulls after ranked donors ASC / before them DESC; plus `min_certified_points` being inclusive — routes_donors.py:29-70, 91
- §3.1 — revise — ambiguity — donor `email` is non-blank, unbounded in length, and unique **case-insensitively**; a duplicate is `ERR_INVALID_REQUEST` — routes_donors.py:22-26, 112
- §3.1 — revise — ambiguity — status-change `reason` is required and non-blank; edge admissibility is checked before the `effective_date` and `entity_type` constraints; a future `effective_date` on a lapse is `ERR_INVALID_STATE` and lapsing is the only edge that constrains `effective_date` — routes_donors.py:147-155
- §3.1 — revise — ambiguity — dissolving an `INDIVIDUAL`/`JOINT_HOUSEHOLD` donor is `ERR_INVALID_STATE` — routes_donors.py:156-159
- §3.1 — revise — ambiguity — household-link response body is the path donor, not the partner; re-linking an already-linked pair is admitted and bumps both versions again — routes_donors.py:181-193
- §3.1 — revise — ambiguity — renewal `cycle_year` must be 1900–2100; a duplicate year is not a mutation at all (200, `version`/`updated_at` unchanged, `season_ticket_first_cycle_year` not filled) — routes_donors.py:282-290
- §3.2 — revise — ambiguity — `gift_date`'s UTC calendar year must be 1900–2100 else `ERR_INVALID_REQUEST` — routes_donors.py:226-228
- §3.2 — revise — ambiguity — a gift born `RECEIVED` or `REFUNDED` carries `settled_at` stamped at creation — routes_donors.py:229
- §3.3 — revise — ambiguity — duplicate recalculation `cycle_year` is `ERR_INVALID_REQUEST` — routes_recalc.py:37-39
- §3.3 — revise — ambiguity — the run walks the donor book in `created_at` ASC, fixing ledger append order (the cross-partition item pass 1 handed me) — routes_recalc.py:83
- §3.3 — revise — ambiguity — exactly six ledger rows per variant even at `0.00`; `PROVISIONAL` generation before `CERTIFIED`; the six entry types appended in the listed order — routes_recalc.py:65-79, calc.py:212-219
- §3.3 — revise — **mismatch** — the `CUMULATIVE_GIVING` row's `points` is the giving component **after** the loyalty multiplier (the multiplier has no row of its own, only a `basis_note` mention); `NET_TRANSFER`/`DISPUTE_ADJUSTMENT` rows are identical across both generations. PRD's "the points that component contributed" read naturally as the raw band sum — calc.py:201-209, 179-198
- §3.3 — revise — ambiguity — a run also re-judges `eligibility_status` on live assignments and recomputes the holding sections' counters/posture with no `version` bump, and refreshes `certified_points_sum` on *every* recalculation, not just the one being run — routes_recalc.py:96-99
- §3.4 — revise — ambiguity — the dispute window is the **only** gate on filing: the parent recalculation's `status` is never examined, so a `DRAFT`/`COMPUTED`/`CERTIFIED` cycle accepts a filing; and an absent/non-string `donor_id` cannot fire the ownership check — routes_disputes.py:47-59
- §3.4 — revise — ambiguity — `info_note` on request-info is required and non-blank — routes_disputes.py:100
- §3.4 — revise — ambiguity — `response_note` is required and non-blank but never persisted; `info_note` is not cleared — routes_disputes.py:120-126
- §3.4 — revise — ambiguity — an `UPHOLD` omitting `granted_points_delta` grants `0.00`; the upheld recompute cascades into assignment eligibility, section posture and every scoring recalculation's `certified_points_sum` without version bumps — routes_disputes.py:138, 148-157
- §3.5 — revise — ambiguity — rank stamping advances neither the donor's `version` nor `updated_at`, and a donor outside the pool keeps their previous `rank_position` rather than being nulled; the `scheduled_slot_count` decrement alone does not bump the event's `version` — routes_recalc.py:141-143, 164-167

## Checked and deliberately left alone (PRD already pins them uniquely)
The whole point formula and every constant (marginal bands 1.0/1.5/2.0 per 100,000c at 2,500,000/10,000,000c boundaries, loyalty ≥5 → ×1.10 applied to the already-rounded component, streak cap 20 × 5, tenure cap 30 × 3, alumni 25/15/5/0 gated on `ACTIVE`/`LAPSED`, net transfer, the assembly + floor at zero, `certified_base_points` as the pre-transfer/pre-adjustment part); the one-shot grace in the backwards streak walk; the input-set gate (`gift_date ≤ cutoff_date`, `ATHLETICS_ANNUAL`/`CAPITAL` only) and the two variants' admitted `gift_status` sets; `certified_points_value`'s derivation; the four rank keys and 1-based index; the event candidate pool including the `ASSIGNED`-seat restriction for `POSTSEASON`/`AWAY_GAME`; every retention-analysis bucket, divisor-of-1 rule, rounding width and the 8 response keys; the transfer `%` caps and `max_transferable_points`; the four basis preconditions; `underwater_ratio`/`pricing_posture` branch order and `recommended_requirement_cents`; the handling-fee bands keyed on `requirement_cents`; the reseating 7/12 round-then-sum; `HOLD_MINUTES = 4320`; `INFO_REQUEST_ROUND_CAP = 2`; all gift-settlement money effects and version bumps; the certify preconditions and its wider dispute gate vs. the re-run gate; every §4 role list in my partition (all 27 rows match `auth.py`'s sets exactly) and every 201-vs-200 status code.

## For pass 3 / the pass-4 reconciliation
1. **`calc.grandfathered_rate` (calc.py:294-299) is in my partition but its prose is in §3.8, which is yours.** It returns the **first** `requirement_history` entry matching `first_occupied_cycle_year`. `requirement_history` can legitimately hold two entries for one `cycle_year` (two reprices in the same year, or a renovation `START_RESEATING` whose recalculation year is already on file), so §3.8's "the `per_seat_requirement_cents` recorded in the section's `requirement_history` for `first_occupied_cycle_year`" is ambiguous — the **earliest appended** entry wins, not the latest. I left §3.8 untouched to avoid straying into your partition; please pin it.
2. `_certification_cascade` iterates its touched-event set with `sorted(event_ids)`, i.e. lexicographically by `id`. This is technically an id-based iteration order and thus in tension with §2.4's "no `id` value is ever an input to a ranking, ordering or tie-break", but the per-event work is independent and the logical clock does not advance mid-request, so nothing observable depends on it. I did not pin it (pinning it would contradict §2.4) and did not weaken §2.4. Flagging for pass-4 awareness only.
3. No pass-1 edit looked wrong or over-claimed to me. Its `created_at`-is-not-unique pin is exactly what `store.order_key` (created_at + `_seq`) and `calc.rank_sort_key` implement, and its §2.9 converse rule is what `derive.py`'s module docstring and its complete absence of `touch()` calls encode — I leaned on both rather than re-litigating them.
4. Cross-check for you: §3.5's cascade text I edited now says the event's `version` does not move on a bare `scheduled_slot_count` decrement. `routes_events.py`'s publish/republish paths are yours — make sure whatever you pin about `published_slot_count`/`scheduled_slot_count` there stays consistent with that.agentId: a785a2d9d3c20075e (use SendMessage with to: 'a785a2d9d3c20075e', summary: '<5-10 word recap>' to continue this agent)
<usage>subagent_tokens: 145057
tool_uses: 39
duration_ms: 491036</usage>

### Subagent summary — Pass 3 (transfers, sections, events, assignments)

Pass 3 complete.

## Counts

| | before | after |
|---|---|---|
| lines | 409 | 409 |
| chars | 109,930 | 128,646 |
| diff hunks vs `PRD_FINALIZED.md` | 28 | 54 |

All 28 pass-1/2 hunk headers still present (`51,52c51,52 … 233c234`); the four distinctive pass-1/2 phrases each still occur exactly once; file still ends on `| ERR_SECTION_CAPACITY_EXCEEDED | 409 |`. **22 ambiguity pins, 10 mismatch revisions.** No scratch files created; nothing deleted.

## Changes

- §2.3 — insert — ambiguity — slots sharing a `slot_index` fall back to `created_at` then write order — routes_events.py:70
- §3.6 — insert — ambiguity — `recipient_donor_id == source_donor_id` is 400 at step 6 *before* either ref resolves; source resolved ahead of recipient; four decision fields start null — routes_transfers.py:39-60
- §3.6 — insert — ambiguity — `note` required and non-blank; GRANT never rewrites `exception_required` — routes_transfers.py:73,79-80
- §3.6 — revise — mismatch — approval re-judges eligibility in **both** directions (recipient back to `ELIGIBLE`), recomputes section counters and `certified_points_sum`, with no version bumps of its own — routes_transfers.py:112-113
- §3.6 — revise — mismatch — reversal is symmetric, including flipping a recipient's row to `UNDERWATER`; `reason` required non-blank — routes_transfers.py:125,138-139
- §3.7 — insert — ambiguity — `section_code` compared exactly; duplicate is 400, not a state conflict — routes_sections.py:19-23,131
- §3.7 — insert — ambiguity — duplicate seat triple is 400 at step 6, ahead of the status and capacity gates — routes_sections.py:170-176
- §3.7 — insert — ambiguity — reprice has no state gate at all, accepts a duplicate `cycle_year` (appends a second entry), bounds `cycle_year` 1900–2100, and touches no assignment — routes_sections.py:196-203
- §3.7 — revise — mismatch — missing `post_renovation_*` on `REPRICE` is `ERR_INVALID_STATE` (409), not 400; the `renovation_status` gate is weighed first — routes_sections.py:267-270
- §3.7 — revise — mismatch — omitted `reseating_recalculation_id` is 409, not a missing field — routes_sections.py:277-279
- §3.7 — insert — ambiguity — all five renovation actions recompute the whole inventory block; `COMPLETE` leaves the post-renovation fields and `reseating_recalculation_id` standing — routes_sections.py:298-299
- §3.7 — revise — mismatch — each reseated row is **repriced from scratch** under its own `pricing_mode` against the new rate, and *that* figure is prorated 7/12, not the row's previous `requirement_cents` — routes_sections.py:228-232
- §3.7 — revise — mismatch — `payment_status → INVOICED` is unconditional (including terminal `WRITTEN_OFF`, and whether or not the figure changed); `total_due_cents` = new requirement + **existing** `handling_fee_cents` (never re-banded); row `version` +1; occupancy/eligibility/snapshots untouched — routes_sections.py:235-237
- §3.8 — insert — ambiguity — event creation imposes no gate on the recalculation's `status` and no clock check on the window — routes_events.py:87-110
- §3.8 — insert — ambiguity — `rank_at_publish` may be null; the staleness test is plain equality against the re-stamped rank — routes_events.py:143, routes_recalc.py:154
- §3.8 — revise — mismatch — republication **deletes** `STALE` slots (later fetch → `ERR_SELECTION_SLOT_NOT_FOUND`), spares `CONSUMED`/`FORFEITED`, overwrites `published_slot_count`, and deletes only after all preconditions pass; revived request's `version` +1 while the donor stands still — routes_events.py:135-137,151-161
- §3.8 — insert — ambiguity — `to_status` admits only `OPEN`/`CLOSED`; overlap scoped to the same recalculation; opening never reads the clock; `SLOTS_STALE` cannot be closed; forfeited slots each +1 version; `published_slot_count` survives — routes_events.py:171-195
- §3.8 — insert — ambiguity — forfeit `reason` required non-blank but never persisted; event `status` and slot window never examined; count decrement bumps no event version — routes_events.py:218-225
- §3.8 — insert — ambiguity — pick's event gate splits `ERR_INVALID_STATE` (DRAFT/SLOTS_PUBLISHED/CLOSED) from `ERR_EVENT_SLOTS_STALE` — routes_assignments.py:202-206
- §3.8 — insert — ambiguity — hold-conflict count spans only `HELD`/`ASSIGNED` rows — routes_assignments.py:35-39
- §3.8 — insert — ambiguity — supersede hits every expired `HELD` row (never `ASSIGNED`) in `created_at` order and leaves its slot at `CONSUMED` — routes_assignments.py:224-230
- §3.8 — insert — ambiguity — the event's `version`/`updated_at` stand still across a pick; response is 201 — routes_assignments.py:256-257
- §3.8 — insert — ambiguity — prior tenure judged on the stored `first_occupied_cycle_year` strictly earlier, `ASSIGNED` only, earliest row wins; **earliest appended** `requirement_history` entry for the year wins; the market fallback forces `MARKET` but keeps the inherited year — routes_assignments.py:139-166, calc.py:294-299 *(this is the cross-partition item, verified)*
- §3.8 — insert — ambiguity — years-held is never clamped, so a zero/negative exponent on 1.03 is used as-is — calc.py:308-310
- §3.9 — revise — mismatch — confirm order is version → state → money → eligibility, so a row both short and `UNDERWATER` reports the 402; `UNDERWATER` refusal is 409; `to_status: HELD` parses then 409; the section's version stands still; the matching request is the donor's earliest, one only, note untouched, old seat not released — routes_assignments.py:286-315
- §3.9 — insert — ambiguity — `DONOR_RELEASE` default applies on the `ASSIGNED` edge too; the consuming slot is untouched there; the seat is only returned to the pool from `HELD`/`ASSIGNED` — routes_assignments.py:42-60,312
- §3.9 — insert — ambiguity — billing carries no version stamp; "freeze" means it recomputes nothing; an *omitted* `amount_cents` on PAID is a 402 shortfall; the write-off role gate sits inside the transition, ahead of the `DELINQUENT` check; `UNBILLED` destination is 409 — routes_assignments.py:326-353
- §3.9 — insert — ambiguity — filing weighs only the current row's money (it may be `RELEASED` and need not belong to the donor); the target section's status is not examined; `request_type` is descriptive; the donor ownership check fires only for a string `donor_id`; ref resolution order; 201 — routes_assignments.py:365-407
- §3.9 — insert — ambiguity — **every** outstanding `AWAITING_SELECTION` row is superseded in `created_at` order, note overwritten; `BLOCKED` rows are not swept — routes_assignments.py:387-393
- §3.9 — revise — mismatch — grant target need only be neither `ASSIGNED` nor `DECOMMISSIONED`, so a `HELD` seat qualifies, stays `HELD`, and no `max_concurrent_holds`/window check runs; error order pinned; full new-row field set (fee 0, `total_due = requirement`, fresh `first_occupied_cycle_year`, 72-h hold); old row released only if `HELD`/`ASSIGNED`; answers 200 — routes_assignments.py:436-488
- §3.9 — revise — mismatch — DENY writes the note unconditionally (nulling a carried reason); a `BLOCKED` request has **three** futures, the closure one reachable only after republication; closure sweep order and pending-count effects — routes_assignments.py:420-429, routes_events.py:196-207
- §4 preamble — revise — ambiguity — 201 is keyed on the response body *being* the new resource: pick 201, publish-slots 200, relocation grant 200 — routes_events.py:163, routes_assignments.py:257,488

## Left alone (PRD already pins them correctly)

§2.8's ladder positions for all my endpoints were checked against source and are consistent (steps 11→12→14→17→18→24 for the pick; 11→17→23→24 for the grant; 27 last for seat capacity; the step-9 carve-outs for `ERR_TRANSFER_POLICY_EXCEPTION_REQUIRED` and `ERR_EVENT_SLOTS_STALE`; 10/20/21 for publish; 26 last for transfer ceilings). Every §4 role-set row for my endpoints matches `auth.py` exactly, and every error code my four modules raise is already in the §5 table — **no §4 or §5 edits were needed**. §3.5's candidate-pool definition (line 212) already matches `calc.event_pool` exactly. §3.7's `pricing_posture`/pricing-sensitivity paragraph matches `calc.py:270-291`. Slot geometry, the half-open/closed convention contrast, and the seat-retirement ordinal rule were all already exact. Pass-1/2 findings (`created_at` non-uniqueness, no version bump on a bare derived recompute, live `certified_points_sum`, money/point JSON shapes, null-comparand segregation-of-duties) were treated as settled and reused rather than re-argued.

## FLAGGED for pass-4 reconciliation (not edited)

1. **§2.1 over-claims `PlatformAdmin`.** "A `PlatformAdmin` may also perform every development-office write" is false: `forfeit_slot` (routes_events.py:214) and `create_relocation_request` (routes_assignments.py:363) are `DONOR_AND_OFFICER` — no `PlatformAdmin`. The §4 rows are correct; the §2.1 sentence is the defect.
2. **§2.8 step 3 vs step 5.** Ownership is listed before path resolution, but `pick_seat`/`forfeit_slot`/`decide` all call `get_path` first, so an unknown slot id gives 404, not 403.
3. **§2.8 has no step for the `UNDERWATER` confirm refusal.** I pinned inline in §3.9 that the 402 shortfall beats it (impl order), which reads as an exception to step 9's "state" check; pass 4 should decide whether §2.8 needs a matching clause.
4. **§2.1/§2.8 reference `Donor` ownership of *seat assignments*,** but no `Donor`-role seat-assignment endpoint exists (occupancy and billing are both `OFFICE`).
5. **Section `status` `CLOSED` is unreachable** — no code path ever writes it (only `OPEN`/`UNDER_RENOVATION`).
6. **`release_reason` `RESEATING` is never written by any code path** — the reseating cascade touches only the money axis.
7. **Awareness item confirmed, no edit:** `routes_recalc._certification_cascade` iterates `sorted(event_ids)` lexicographically; nothing observable depends on it, and §2.4 was left untouched.agentId: aff47c4756962cea5 (use SendMessage with to: 'aff47c4756962cea5', summary: '<5-10 word recap>' to continue this agent)
<usage>subagent_tokens: 116354
tool_uses: 89
duration_ms: 1289120</usage>

### Subagent summary — Pass 4 of 4 (reconciliation)

Pass 4 (reconciliation) complete. `PRD_COMPLETED.md` is the only file I touched.

## File state
- **411 lines / 133,859 chars** — up from 409 lines / 128,646 chars (+2 lines, +5,213 chars). Never shortened.
- **58 diff hunks** vs `PRD_FINALIZED.md` (was 54; my six edits produced +4 net new hunks, two landing inside paragraphs earlier passes had already revised). Not byte-identical. Still ends on `| ERR_SECTION_CAPACITY_EXCEEDED | 409 |`. Spot-checked eight distinctive phrases from passes 1–3 — all survive.
- Implementation lives at `workspace/implementation/` (not `TASK_DIR/implementation/` as the brief stated).

## Work list

**1. §2.1 `PlatformAdmin` over-claim — EDITED (flag confirmed).** `auth.DONOR_AND_OFFICER = (DONOR, DEVELOPMENT_OFFICER)` excludes `PlatformAdmin`, and **three** call sites use it, not two: `forfeit_slot` (routes_events.py:214), `create_relocation_request` (routes_assignments.py:363) and `create_dispute` (routes_disputes.py:45). §4 rows 341/358/361 are correct. Replaced the false universal with an enumeration of what `PlatformAdmin` does reach (plus its exclusive `WRITTEN_OFF` power, routes_assignments.py:345), named all three excluded writes, and pointed at §4 as the per-endpoint authority.

**2. §2.8 step 3 vs step 5 ordering — EDITED; the flag's endpoint list was wrong.** There are exactly three `require_owner` call sites — `pick_seat` (routes_assignments.py:183-184), `forfeit_slot` (routes_events.py:215-216) and `provide_dispute_info` (routes_disputes.py:117-118); no `decide` endpoint does an ownership check (`decide_dispute` uses `require_segregation`, `decide_relocation_request` is `OFFICE`). All three are uniformly `get_path` **before** ownership, so a 404 beats the 403. The other two owner-checked ops (`create_dispute`, `create_relocation_request`) have no path parameter and compare the body's claimed `donor_id` **before** field validation and reference resolution. Rewrote step 3 to describe that real two-shape variation rather than a false universal.

**3. `UNDERWATER` confirm refusal — EDITED.** routes_assignments.py:292-297: the 402 `ERR_SEAT_DONATION_SHORTFALL` is raised before the `eligibility_status` check, which is a plain `ERR_INVALID_STATE` (409). §3.9 already pinned this inline; §2.8 step 9 did not, so the two contradicted. Added a third carve-out to step 9 stating the `UNDERWATER` 409 is weighed after the step-25 money check while every other state precondition on that endpoint stays at step 9.

**4. `Donor` ownership of seat assignments — EDITED (flag confirmed).** No assignment endpoint owner-checks: occupancy and billing are `OFFICE` (donor refused at step 2), and the reads (routes_assignments.py:66/94) are `NO_ANALYST` and entirely unscoped. Dropped "seat assignment" from both the §2.1 sentence and step 3's resource list, added that a donor is refused with `ERR_FORBIDDEN_ROLE` there rather than `ERR_NOT_RESOURCE_OWNER`, and that reads are not narrowed to the caller's own rows. Left relocation-request creation (genuinely donor-owned) intact.

**5. Section `status` `CLOSED` — EDITED (flag confirmed).** Only three writes exist: `status="OPEN"` at creation (routes_sections.py:142), `UNDER_RENOVATION` on `SURVEY` (263), `OPEN` on `COMPLETE`/`ABANDON` (289/295). Added a §3.7 paragraph stating those are the only writes, so `status` oscillates between two values; kept `CLOSED` in the vocabulary and noted the list filter accepts it (it is in `SECTION_STATUSES`, so `q_enum` admits it and returns an empty page) and that the gates name it defensively and it cannot be reached to observe.

**6. `release_reason` `RESEATING` — EDITED, but the flag was partly wrong.** `RESEATING` **is** reachable: `change_occupancy` validates `release_reason` against the full enum (routes_assignments.py:287) and writes it through on the `RELEASED` branch (`reason or "DONOR_RELEASE"`, line 312), so a caller can set it. What is true is that the service never writes it itself — the reseating cascade touches only the money axis. Rewrote the sentence to distinguish caller-supplied from service-written values (`NONE` at creation, `SUPERSEDED_BY_NEW_HOLD` at line 229, `DONOR_RELEASE` as default and on the relocation grant's release at line 481) rather than declaring `RESEATING` unreachable.

**7. `sorted(event_ids)` in `_certification_cascade` — NO EDIT (independently confirmed).** routes_recalc.py:160-168: each iteration reads only its own event's slots via `recompute_scheduled_slot_count`, `newly_stale` is a set, there is no early exit, no shared counter and no raise. `touch()` takes `updated_at` from the logical clock (which never self-advances) and `_seq` is assigned only at row creation, so `updated_at`, `version` and ordering outcomes are identical under any permutation. §2.4's "no `id` is ever an input to a ranking, ordering or tie-break" remains true of every observable. Left §2.4 untouched.

**8. §3.3/§3.5 cross-pass check — NO EDIT.** No contradiction. `_score_all` does `touch(donor)` per donor and `touch(recalc)`, matching §3.3's "advances the recalculation's `version` by 1 along with the `version` of every scored donor"; `_stamp_ranks` (routes_recalc.py:141-143) writes `rank_position` with no `touch`, matching §3.5's "advances neither the donor's `version` nor their `updated_at`" and its "donor outside the pool keeps their previous `rank_position`" (the loop only assigns to pool members). §3.5's "the decrement by itself does not advance the event's `version` or `updated_at`" and §3.8's forfeit paragraph state the same rule compatibly, and both match `forfeit_slot`, which recomputes the counter without touching the event.

## Consistency sweep
Read every paragraph the three passes edited (63 changed lines) for the three named failure modes. **No contradictions or dangling references found beyond items 1–4, which the sweep independently corroborated.** Verified against source: the §2.3 donor `sort` set is exactly the eleven keys in `_SORT_FIELDS`, the null-`rank_position` placement and tie stability match `sorted(by_created_at(rows), reverse=...)`; the selection-slot `slot_index` override is real; step 13 vs step 26 ordering matches `approve_transfer` (the `EXCEPTION_PENDING` 422 precedes both the state check and the ceilings); `ERR_TRANSFER_POLICY_EXCEPTION_REQUIRED` is 422 as claimed; §2.9's "every touched resource" framing is definitional and does not clash with the "version does not move" recomputation statements in §3.5/§3.8/§3.9; §4's role lists match every `auth.require` call site I checked. All step numbers my new prose cites (2, 5, 6, 7, 25) resolve correctly.agentId: a280a7caf2585eabc (use SendMessage with to: 'a280a7caf2585eabc', summary: '<5-10 word recap>' to continue this agent)
<usage>subagent_tokens: 133140
tool_uses: 50
duration_ms: 446928</usage>

