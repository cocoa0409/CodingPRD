# Worklog — task_2820_pizza_delivery_zone_mapping_driver_reimbursement

## Step 1: Create task directory — 2026-09-05T02:24:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2820_pizza_delivery_zone_mapping_driver_reimbursement` and its `workspace/` subdirectory. Index 2820 was pre-assigned by the orchestrating prompt; no scan of `./tasks/` was performed (concurrent pipelines on this host).

## Step 2: Generate Scaffold — 2026-09-05T04:30:00.000Z

All three scaffold artifacts are complete and the lint is clean. Final verdict block, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2820_pizza_delivery_zone_mapping_driver_reimbursement/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2820_pizza_delivery_zone_mapping_driver_reimbursement/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2820_pizza_delivery_zone_mapping_driver_reimbursement/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    61
  §1.1 entities declared:     14
  §1.8 instances scanned:     24
  §1.9 instances scanned:     80
  Calls scanned (§1.8+§1.9):  1595

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Output (`/home/ubuntu/github/CodingPRD/tasks/task_2820_pizza_delivery_zone_mapping_driver_reimbursement/`)

| file | lines |
|---|---|
| `SCAFFOLD.yaml` | 3453 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 3207 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 6650 |

- **SCAFFOLD.yaml** (§1.0–§1.7, no design keys): 14 entities, 8 state machines (parallel Order dimensions), 2 §1.2.1 concurrency rules, 11 calculations, 41 ordered validations, **61 endpoints**, 64 errors, 5 roles (`segregation_of_duties`, two entity-backed). `domain_name: pizza-delivery-zone-reimbursement`, `api_prefix: /store-ops`, `difficulty_level: expert_plus`; the "Generate task harder than expert level!" directive line is **stripped** from `scenario:` (verified: no "harder"/"expert" substring in it).
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml**: **9 rules / 24 instances** (unchanged this session).
- **SCAFFOLD_CORNER_DESIGN.yaml**: **9 sections / 100 instances** — 80 full recipes + 20 `excluded_because` stubs: entities 12, state_machines 14 (2 stubs), calculations 18 (5), validations 33 (8), endpoints 7 (2), errors 5, rbac 3, cross_cutting_complexity_layers 6 (3), consistency_model 2.

## Verification beyond the lint
- **Error coverage**: all **64** §1.6 error ids are now triggered somewhere in §1.8+§1.9 (the last 16 gaps were closed by the errors/rbac/cross-cutting sections — e.g. the 10 type-scoped 404s, `ERR_INVALID_STOP_STATE`, `ERR_INVALID_COMPLAINT_STATE`, `ERR_INVALID_SAFE_DROP_STATE`, `ERR_FORBIDDEN_DRIVER_SCOPE`, and both `ERR_STALE_*_VERSION` OCC rules).
- **Placeholder closure**: 0 unbound `${var}` in either design file (independent checker over payloads, paths, `as_user_id` and asserts).
- **Stub integrity**: every `excluded_because.difficulty_instance` resolves to a real `rule_id / name` pair in §1.8; no stub carries a `test_recipe`; no duplicate names within §1.9 and no collisions with §1.8.
- **Grounds**: all resolve to declared §1.1–§1.7 elements. Two were wrong and were fixed (`ServiceAddress.fields.zone_version_id` → `evaluated_zone_version_number`; `rbac.role_model` → `complexity_profile.role_model`), plus two stub rule_ids (`compensating_inverse` → `compensating_invariant`, `idempotent_recompute` → `non_linear_state_machine`).
- No forbidden concurrency vocabulary in any of the three files; each design file has exactly its one top-level key and `SCAFFOLD.yaml` has neither.

## One hazard worth flagging for future runs
Emitting §1.9 sections with `yaml.dump` per section produced **duplicate YAML anchors** (`polygon: &id001` / `*id001` restarting at `id001` in each appended dump), which made the combined file unparseable by `yaml.safe_load` while `scaffold_lint.py` still reported clean at the time. I expanded all aliases to literal vertex lists; the file now parses (9 sections). Generator scripts live in `/tmp/t2820/` (`frag.py`, `gen_val.py`, `gen_ep.py`, `gen_err.py`, `gen_rbac.py`, `gen_cross.py`) — any future emitter should pass `default_flow_style` plus an `Dumper` with `ignore_aliases` or post-expand.

**Orchestrator verification:** all three files exist; all three parse under `yaml.safe_load`; top-level keys correct (SCAFFOLD.yaml has neither design key; each design file has exactly its own single key). Grep for the difficulty-directive phrasing in SCAFFOLD.yaml returned no hits, so no strip-after-Step-2 patch was needed.

## Step 3: Copy Shared Files — 2026-09-05T04:30:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T04:50:00.000Z

**Orchestrator note — first attempt died.** The initial Step 4 subagent was terminated early by an infrastructure API error after writing only §1–§2.10 (187 lines, no entity/endpoint/calculation sections). Per the skill's anti-truncation guidance the partial was NOT hand-patched: it was stashed to `/tmp/t2820_orch/PRD.partial.attempt1.md`, removed from `workspace/`, and a fresh doc-generator subagent regenerated PRD.md from scratch under stricter chunked-append discipline. The summary below is that second (successful) run, verbatim.

Done. `/home/ubuntu/github/CodingPRD/tasks/task_2820_pizza_delivery_zone_mapping_driver_reimbursement/workspace/PRD.md` is complete at **479 lines / 116,827 bytes**, written entirely through small heredoc appends with absolute paths (19 appends total, each verified by `wc -l`).

**Section list**
- `# Pizza Delivery Zone Reimbursement API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Actors, Identity Headers and RBAC · 2.2 API Response Structure · 2.3 Pagination and Collection Reads · 2.4 Common Resource Properties, Timestamps and the Logical Clock · 2.5 Path Resolution and Nested Reads · 2.6 Arithmetic Discipline: Cents, Micro-Degrees, Miles and Minutes · 2.7 Publishing Against a Parent Record That May Have Moved · 2.8 The Order of Refusal · 2.9 Cascade Discipline and Derived Values · 2.10 Window and Interval Conventions
- `## 3. Business Logic & Workflows` — 3.1 Standing Up a Store and Publishing a Delivery Area · 3.2 Classifying a Street Address · 3.3 Arguing the Edge: Disputes and the Override Window · 3.4 Taking the Order, Pricing the Ticket, and Disclosing the Fee · 3.5 Dispositioning the Order and the Make Line · 3.6 Putting a Driver on the Road · 3.7 Publishing Reimbursement Schedules and Building a Route · 3.8 Committing the Route: Capacity, Route Duration and the Mileage Waterfall · 3.9 Out of the Door: Departure, the Handoff, and the Order-to-Door Stopwatch · 3.10 Cash on Hand and the Safe-Drop Procedure · 3.11 Closing the Route: Settlement, Recall, and the Reimbursement Ledger · 3.12 Service Recovery: Remakes, Complaints and Clawbacks
- `## 4. Endpoint Definitions` (status-code paragraph + 61-row, 4-column table)
- `## 5. Error Code Catalogue` (64-row, 2-column table)

**Coverage verification (scripted against SCAFFOLD.yaml)**
- Endpoints: **61/61** present as exact `| METHOD | `path` |` rows in §4. None missing.
- Errors: **64/64** present with the scaffold's exact HTTP status; every error id also appears in the §2.8/§3 prose.
- Entities 14/14, state machines 8/8 (every `from`/`to` state of all 46 transitions appears in backticks), calculations 11/11, validations 41/41 numbered in strict priority order 1–41 in §2.8.

**Hard Contracts**
- Contract 1 (Field-Name Coverage) — **PASS**, run twice with two independent extractors (Python fence-stripped regex, then `grep -o`). Required set = 149 unique identifiers (140 entity field names + all `input` keys with the optional-marker `?` stripped + 14 path params + the 4 common fields). Missing set empty both times.
- Contract 2 (Rule Coverage) — **PASS**. Both OCC rules carry write endpoint + `expected_store_version`/`expected_driver_version` + `ERR_STALE_STORE_VERSION`/`ERR_STALE_DRIVER_VERSION` + 412; all 11 calculation formulas are reconstructible step-for-step with their worked numbers; every validation condition is matched to its error id; field types, defaults and initial values are stated; sibling branches (fee tiers, LATE remedy tiers, the four complaint categories, the two reimbursement variants, the half-open vs closed intervals) are symmetric.
- Contract 3 (§3 Path Purity) — **PASS**. 339 distinct backticked tokens in §3, zero starting with `/`, zero bare HTTP methods, zero method+path combinations. Paths appear only at line 9 (`/store-ops` mount), lines 112/114 (the two OCC write endpoints in §2.7), and the §4 table.

**Tail intact:** the file ends at a real boundary — the final line is the last §5 table row `| `ERR_REMEDY_EXCEEDS_TOTAL` | 422 |`, no mid-sentence truncation and no audit footer. No meta-difficulty language, no scaffold-internal references (`§1.x`, `common_fields`, `entity_backed`, `calculations.*`, bootstrap notes), no pseudocode or operator syntax, no fuzzy hedging.

One content fix applied during this pass: the stale forward reference in §3.5 that pointed the remake cycle at "§3.9" now correctly reads §3.12. Read restrictions were honoured — only SKILL.md, section-2.2-response-structure.md and SCAFFOLD.yaml were opened; neither design index nor any sibling task directory was read or grepped.

**Orchestrator verification:** `wc -l` = 479; tail is the complete final error-table row (no mid-sentence cut); 30 headings present including §3, §4, §5, so the trailing-section truncation failure mode did not occur. Grep for `harder|expert_plus|difficulty` returns one hit only — the phrase "makes the next route's commitment harder" in §3.8 domain prose — so the Step 2 difficulty directive did not leak.

## Step 6: Generate Implementation — 2026-09-05T05:25:00.000Z

(Launched concurrently with Step 5; the implementation was written blind to `test_suite/` and `test_helpers/` and to both design indices.)

The implementation is complete.

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_2820_pizza_delivery_zone_mapping_driver_reimbursement/workspace/implementation/`

| File | Bytes | Lines |
| --- | --- | --- |
| `app.py` | 2058 | 73 |
| `auth.py` | 5161 | 141 |
| `calc.py` | 7318 | 208 |
| `cascade.py` | 1874 | 56 |
| `clock.py` | 1885 | 71 |
| `db.py` | 2851 | 112 |
| `derive.py` | 5984 | 193 |
| `errors.py` | 3094 | 89 |
| `listing.py` | 511 | 15 |
| `response.py` | 1370 | 50 |
| `serialize.py` | 11789 | 295 |
| `validate.py` | 6438 | 188 |
| `requirements.txt` | 13 | — (`Flask==3.0.3`) |
| `start.sh` | 398 | — (mode 775, executable) |
| `routes/__init__.py` | 0 | 0 |
| `routes/stores.py` | 3960 | 110 |
| `routes/zones.py` | 13539 | 323 |
| `routes/drivers.py` | 9461 | 222 |
| `routes/fleet.py` | 6360 | 162 |
| `routes/orders.py` | 11493 | 284 |
| `routes/dispatches.py` | 23647 | 533 |
| `routes/complaints.py` | 7059 | 184 |
| `routes/clock_routes.py` | 453 | 18 |

3327 lines of Python total; 124 KB on disk. No `__pycache__`, no data files, no scratch left behind.

## Module layout

- **Kernel**: `clock.py` (logical clock, default `2026-08-01T00:00:00Z`, ISO with exactly 3 fractional digits), `db.py` (14 in-memory dicts + `insert`/`touch`/`ordered` with a monotonic `_seq` tiebreaker for stable list ordering), `errors.py` (64-entry error→status table), `response.py` (envelope with `req_` + 20 uppercase-alnum request id), `validate.py` (rule-8 schema layer + pagination/filters), `auth.py` (refusal rules 1-7, scope evaluated before the 404s), `calc.py` (11 calculations: integer micro-degree geometry, ray-casting point-in-polygon with on-edge = inside, tiered pricing, route model, two-tier cumulative mileage waterfall, stopwatch, remedy formula), `derive.py` (all re-derived-on-read fields), `serialize.py`, `cascade.py`, `listing.py`.
- **Routes** (8 blueprints): stores, zones (+ addresses, disputes), drivers (+ MVR, insurance, qualification), fleet (cost models, safe drops), orders, dispatches (+ stops, reimbursement lines), complaints, clock.

## Self-check: 61/61 endpoints routed

I extracted the 61 rows of PRD §4's endpoint table and diffed them against Flask's live `url_map`: **exact match, no extras, no gaps** (`diff` clean). Method/path breakdown: 33 POST, 26 GET, 1 PATCH, 1 DELETE.

## start.sh

Reads `$PORT` (via `app.py`'s `os.environ["PORT"]`), binds `0.0.0.0`, and runs in the foreground through `exec python3 app.py`. Flask is installed only when missing, so per-test reboots don't contend on pip. Cold boot to first served request measured at **0.62 s**, and a fresh process serves empty collections (`total_count: 0`) — nothing is seeded.

## Smoke test (PORT=39820, killed by pid/port afterwards; port now free)

Full happy path passed end to end: clock set → store → zone version → activate → address (`IN_ZONE`, grid 3.00, drive 15) → order (fee 399 → 200, exercising the 199.5 → 200 half-up example) → zone-decision → disclose-fee → production START/READY → driver → MVR → insurance → qualify → cost model → dispatch → stop → lock (estimated 286) → depart → door-arrival (cash 2700, provisional line 286) → return → settle (actual 354 = 100 + round(4.10 × 62)) → complaint LATE at 50 gross vs 30 promise → propose 2400 → approve with clawback → driver accrued nets to 0 → safe drop → void inside window → cash conservation identity `2700 = 0 + 2700` holds at every step. Negative paths spot-checked: `ERR_MISSING_USER_ID` 401, `ERR_INVALID_ROLE` 401, `ERR_UNAUTHORIZED` 403 on an agent attempting `GRANT`, `ERR_FORBIDDEN_STORE_SCOPE` / `ERR_FORBIDDEN_DRIVER_SCOPE` 403, `ERR_ORDER_NOT_FOUND` 404, `ERR_INVALID_SAFE_DROP_STATE` 409, unknown endpoint 404 and wrong method 405 both returned in envelope form. Clock moves flipped `effective_zone_state` `IN_ZONE` → `EDGE` on override lapse without any write, confirming derive-on-read.

Two notes for later steps: (1) mileage inputs (`tier1_cap_miles`, `actual_miles`) are strictly JSON numbers and `_cents` fields strictly JSON integers, matching the scaffold's declared types — if a Step 7 sweep shows a mass setup failure naming those fields, it is the known fixture string-typing bug, not an implementation defect; (2) three PRD/scaffold conflicts were resolved in favour of the PRD's explicit sentences — qualification-decisions answers 201, `DELETE` stop returns the parent Dispatch, and `POST /store-ops/dispatches` does apply the priority-7 body-FK check on `driver_id` per the scaffold's `applies_to`.

I did not read `test_suite/`, `test_helpers/`, either design YAML, or any sibling task directory, and `worklog.md` is untouched (timestamp still 04:49).

## Step 5: Generate Unit Tests — 2026-09-05T05:45:00.000Z

(Launched concurrently with Step 6.)

Test suite generation for task 2820 is complete and verified.

## Output directories (both at the TASK ROOT; neither exists under `workspace/`)

`.../test_helpers/` — 9 files, 105,638 bytes, 2,812 lines

| bytes | lines | file |
|---|---|---|
| 1,208 | 47 | `__init__.py` |
| 13,254 | 268 | `api_client.py` |
| 7,123 | 144 | `api_errors.py` |
| 27,580 | 632 | `assertions.py` |
| 7,083 | 220 | `constants.py` |
| 8,194 | 255 | `factories.py` |
| 26,884 | 677 | `fixtures.py` |
| 3,174 | 73 | `test_users.py` |
| 11,138 | 496 | `types.py` |

`.../test_suite/` — 12 files, 387,902 bytes, 8,445 lines

| bytes | lines | tests | file |
|---|---|---|---|
| 1,312 | 46 | — | `conftest.py` |
| 29,032 | 627 | 15 | `test_01_entities_and_consistency.py` |
| 29,034 | 637 | 15 | `test_02_state_machines.py` |
| 36,404 | 718 | 20 | `test_03_calculations.py` |
| 37,745 | 837 | 22 | `test_04_validations_intake_and_routing.py` |
| 40,676 | 911 | 22 | `test_05_validations_fiscal_and_recovery.py` |
| 41,685 | 916 | 29 | `test_06_endpoints_and_errors.py` |
| 30,542 | 678 | 13 | `test_07_rbac_and_cross_cutting.py` |
| 40,961 | 916 | 24 | `test_08_dual_variant_and_boundaries.py` |
| 36,293 | 831 | 12 | `test_09_state_depth_and_cascades.py` |
| 30,461 | 599 | 15 | `test_10_refusal_order_and_cross_entity.py` |
| 33,757 | 729 | 13 | `test_11_temporal_overlap_and_invariants.py` |

## Counts

- **11 test files** (plus `conftest.py`), **200 test functions**
- **Queue A (Difficulty): 24 / 24 instances translated**, every one with >=2 tests
- **Queue B (Corner): 79 / 80 instances translated**
- **1 instance SKIPPED**

## The one skip

`Corner/validations/second_remake_of_the_same_order_is_rejected` — category **`OUTCOME_NOT_UNIQUELY_DERIVED`**. I independently confirmed the subagent's reasoning against the PRD: the first remake drives the order's settlement dimension `CHARGED → ADJUSTED` (§3.12 line 334), and no documented action returns `ADJUSTED` to `DISCLOSED`/`CHARGED` (disclose-fee requires exactly `UNDISCLOSED`, §3.4 line 240). §2.8 rule 29 then refuses to lock any route carrying that order with `ERR_FEE_NOT_DISCLOSED`, and rule 27 blocks stacking the order on a second concurrent route, so the order can never reach `DELIVERED` a second time. Because the remake action is only declared from `DELIVERED` and rule 12 outranks rule 30, a retry reports `ERR_INVALID_ORDER_STATE`, never `ERR_REMAKE_LIMIT_REACHED`. The PRD asserts the refusal exists (line 332) but its own Order of Refusal makes it unreachable, so the outcome is not uniquely derivable — gap left as a gap, no weakened test, no xfail. All other 10 skip logs are empty.

## Verification performed

- Every one of the 200 test functions carries exactly one `Design:` tag, and it is the last docstring line — 0 untagged, 0 dual-tagged, 0 misplaced, 0 dangling tags (all 200 resolve to a real `name:` in the design indices).
- All 200 `PRD: "..."` citations verified byte-for-byte present in `workspace/PRD.md` (0 non-verbatim).
- `compileall` clean; every test module imported in a fresh interpreter, so all fixture/assertion/error-id symbols resolve.
- Zero `skip`/`skipif`/`xfail`/`pytest.mark` occurrences anywhere.
- Zero occurrences of `scaffold`/`corner`/`difficulty`/`instance` outside the mandated `Design:` lines.
- No cents value emitted as a JSON string, no date-only string anywhere (both mass-wipeout fixture bugs pre-empted).
- Directory placement re-verified: task root holds `test_helpers/` and `test_suite/`; `workspace/` holds only `INSTRUCTION.md`, `PRD.md`, `implementation/`. `worklog.md` untouched by me; `workspace/implementation/` never read.

## Two findings worth passing on

1. **Fixed an infrastructure bug** that three slice agents independently flagged: `test_helpers/fixtures.py:486` `list_route_lines()` defaulted to `DISPATCHER_HEADERS`, but PRD §4 authorizes `GET /store-ops/reimbursement-lines` only for `StoreManager`/`Driver`/`ComplianceOfficer` — the three default-header call sites in `test_09` would have 403'd. Default is now `COMPLIANCE_HEADERS`. I then audited all 43 `api_client` call sites in `fixtures.py` against the full §4 role table; every remaining default is role-legal.
2. **PRD internal inconsistency (§3.4, pricing worked example)**: "Drop the food to 1900 cents and the waiver becomes 0, the fee stays 399 and the total is 2299" silently omits the 500-cent tip the preceding sentence establishes; the stated rule `total = food + delivery_fee + tip` gives 2799. All five other examples in that paragraph reconcile exactly. Agents were instructed never to assert 2299 for a tipped order, so no test depends on the erroneous figure — but an implementation that hard-codes the example will disagree with the suite.

**Orchestrator verification:** both `test_helpers/` and `test_suite/` are at the task root; `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/` (no stray test dirs to relocate). Stale `__pycache__` dirs left by the generator's import checks were removed before the first sweep.

## Step 7: Run Tests and Iterate — 2026-09-05T06:12:00.000Z

Clean 8-round sweep achieved. Report below.

## Summary

**Iterations run:** 2

**Iteration 1 baseline:** all 8 rounds 196/200, with the *same* 4 failures in every round (no flakiness — fully deterministic).

**Tests deleted:** none. All 4 failing assertions traced to verbatim PRD sentences and survived the STEP 1a/1b coverage + unique-derivability check.

**Fixes applied to `test_helpers/`:** none. The fixture/factory layer was correct — no shared setup error, no money-as-string or date-only issue, no ISO-precision problem in `api_client`.

**Fixes applied to `test_suite/`** (STEP 2 — test bugs, both made the test *more* faithful to PRD):

1. `test_suite/test_05_validations_fiscal_and_recovery.py` — `test_committing_a_route_that_leaves_after_the_certificate_lapses_is_refused` asserted `after["committed_hot_bag_slots"] == 0` on a **STACKED** route holding one 1-slot stop (`assert 1 == 0`). PRD §3.7: *"Insertion raises the route's `committed_hot_bag_slots` by the stop's `hot_bag_slots` and raises `stop_count`"* — so the pre-lock total is 1, and the refused lock must leave it at 1. Changed to `== dispatch["committed_hot_bag_slots"] == 1`, which is what the rest of the suite asserts in 20+ other places (test_04:485/497/542, test_11:108/251). Outlier test bug, not an implementation defect.
2. `test_suite/test_08_dual_variant_and_boundaries.py` — `test_commitment_models_the_two_quarter_mile_stops_as_a_fifteen_minute_round_trip` compared the response field `expected_return_at` (`...12:15:00.000Z`) directly against `a.instant_plus(...)`, whose `format_instant` is documented as rendering *"the shorter ...Z form the API accepts on input"*. PRD §2.4 requires three fractional digits in responses, so the implementation was right. Wrapped both sides in `a.parse_instant`, matching the pattern every other `instant_plus` comparison in the suite already uses. The `.000Z` format is still asserted on the two adjacent lines (`== "2026-08-05T12:15:00.000Z"` and `a.assert_iso_millis`), so no coverage was lost.

**Fixes applied to `implementation/`** (STEP 3 — 2 tests, one real defect):

`test_qualifying_a_driver_carrying_exactly_five_violation_points_is_accepted` and `test_a_second_officer_signs_the_same_qualification_successfully` both died on `KeyError: 'decision'`: `POST /drivers/{id}/qualification-decisions` returned the **driver** record with 201. PRD §4 states verbatim that *"An endpoint that brings a brand-new resource into existence answers with HTTP 201 and returns that new resource in the `data` field; this includes the action endpoints that create a record as their principal effect, such as ... signing a qualification decision ..."*, while §4's other branch sends every state transition to 200 — so the 201 is only coherent if a new decision record is created and returned. §3.6 names its fields: *"Qualification itself is a signed decision, carrying a `decision` of `QUALIFY`, `SUSPEND`, `REINSTATE` or `DISQUALIFY` plus an optional `reason`."* Returning the driver contradicts "that new resource", so the outcome is uniquely determined.

- `workspace/implementation/db.py` — added the `qualification_decisions` dict (in-memory only, kept outside `COLLECTIONS` because the record has no path variable, no not-found id and no read endpoint per §2.5/§4/§5) plus its `reset()` clear.
- `workspace/implementation/serialize.py` — new `qualification_decision()` emitting only `driver_id`, `decision`, `reason` and the four §2.4 common properties. No field added that PRD does not name.
- `workspace/implementation/routes/drivers.py` — `qualification_decision()` now inserts the record **after** every refusal gate and the driver mutation, and returns it. Driver-side effects (`qualification_status`, `qualified_by_user_id`, version bump, disqualify cascade) are unchanged.

**Verified, not assumed, per the two orchestrator notes:**
- PRD §3.4's worked example *is* internally inconsistent (the 1900-cent variant reports total 2299, omitting the established 500-cent tip; the stated rule gives 2799). No test or helper references 2299 or 2799, so neither side was built on the bad example — both follow the stated rule `total = food + delivery_fee + tip`, confirmed by the passing 2900 / 3275 / 3700 / 2275 / 499 pricing tests. Nothing to fix.
- The deliberately-skipped second-remake design instance was left alone; no test was added for it.

**Final sweep evidence** (all 8 rounds, iteration 2 — 0 failed, 0 errors, 0 skipped in every round):

| results file | passed / total |
| --- | --- |
| results.1.json | 200 / 200 |
| results.2.json | 200 / 200 |
| results.3.json | 200 / 200 |
| results.4.json | 200 / 200 |
| results.5.json | 200 / 200 |
| results.6.json | 200 / 200 |
| results.7.json | 200 / 200 |
| results.8.json | 200 / 200 |

`worklog.md` was not touched (mtime unchanged at 05:39). Scratch files were confined to `/tmp/t2820_step7/`; the one smoke server was booted on the task-specific port 28201 and killed by its own pid — no broad pattern kill was ever issued. The `__pycache__` directories left by my syntax check were removed.

**Orchestrator verification:** re-read all 8 `results.$i.json` independently — every file reports `passed=200, failed=0, errors=0, skipped=0, total=200`, and all 8 carry a fresh 06:02 mtime (i.e. genuine artifacts of the final sweep, not stale files from the baseline round). Step 8 therefore does NOT meet the skip condition: Step 7 applied 2 `test_suite/` fixes and 3 `implementation/` file fixes.

## Step 8: Finalize PRD — 2026-09-05T06:23:00.000Z

Done. Both PRD edits applied; `PRD_FINALIZED.md` differs from `PRD.md` on exactly 2 lines.

## Line counts
- `PRD.md`: 479 lines — `PRD_FINALIZED.md`: 479 lines (0 line delta; 2 of 479 lines revised = 0.42% of lines touched).

## Changes
- **§3.4 (pricing worked example)** — revise — the 1900-cent variant's stated total corrected from `2299` to `2799`, with a short clause noting the 500-cent tip is still part of the ticket — `implementation/calc.py:122` (`total_charge_cents = food_subtotal_cents + charged + tip_cents`).
- **§3.6 (qualification decision)** — insert — two sentences pinning that signing a decision creates a decision record of its own carrying `driver_id`, `decision`, `reason` (null when omitted) plus the four §2.4 common properties; that this record — not the driver — is what the 201 returns in `data`; and that it has no path identifier, no not-found error, no filter set and no read/list endpoint — `implementation/routes/drivers.py:156-158`, `implementation/serialize.py:113-123`, `implementation/db.py:32,34-66,77-88,118`.

## Per-edit pre-edit search log

**Edit 1 — §3.4 total figure**
- (a) Subject: `total_charge_cents` — its formula, where it is computed, and every downstream consumer of it and of `delivery_fee_cents`.
- (b) Enumerated (grepped `total_charge_cents|price_order|delivery_fee_cents` across all of `implementation/`, then read the hits): `calc.py:112-123` (`price_order`, the single site that computes it: food + charged fee + tip); `routes/orders.py:83` (only callsite — order creation; never re-priced, no recompute anywhere else); `routes/orders.py:191` (`fee_disclosure_accurate` compares against `delivery_fee_cents`); `routes/dispatches.py:293,311,325` (cash door-arrival equality gate, stop cash, order cash); `routes/complaints.py:126` (remaining refundable balance); `calc.py:185,199,207` (LATE fee refund, FEE_DISCLOSURE base, proposal cap); `routes/stores.py:19` (store default 399); `serialize.py:182-185`.
- (c) No wording adjustment needed — every enumerated path reads the same stored, once-computed `total_charge_cents`, and the corrected 2799 is exactly what `calc.py:122` yields. The appended clause names only the tip, which is a term the formula already contains, so it adds no claim about the fee/waiver ordering that the surrounding examples pin. The other five worked-example totals (2900/3275/3700/2275/499) were re-verified against the formula and left verbatim.

**Edit 2 — §3.6 qualification-decision record**
- (a) Subject: the qualification-decision resource — its existence, its field set, its common properties, the 201 response body, and its (non-)appearance in path resolution / not-found / filters / reads.
- (b) Enumerated (grepped `qualification_decision|qualification-decisions` across all of `implementation/`, plus read the surrounding modules): `routes/drivers.py:121-158` (the only route; ComplianceOfficer-only; record inserted after every gate and after the driver mutation, returned via `response.created`); `serialize.py:113-123` (emits exactly `driver_id`, `decision`, `reason` + `_common`); `db.py:32` (`qualification_decisions` dict), `db.py:34-49` (`COLLECTIONS` — absent), `db.py:51-66` (`NOT_FOUND` — absent, so no 404 identifier and no `auth`/path resolution entry), `db.py:77-88` (`insert(versioned=True)` stamps `id`, `created_at`, `updated_at`, `version=1`), `db.py:109-118` (`lookup` cannot reach it; `reset` clears it); `response.py:30-31` (201); `cascade.py:43-56` (`disqualify_driver` — the driver-side effects my sentence defers to the driver read); parallel 201/parent-path creators checked so the "unlike the other records created beneath a parent path" contrast stays true — `mvr-checks`, `insurance-verifications`, `safe-drops` and `dispatch-stops` all do have GET-one and GET-list routes; also re-read §2.3 filters, §2.4 common properties and §2.5 nested-read prose for consistency.
- (c) Two adjustments made before committing: (i) the exception clause was scoped as "unlike the other records created beneath a parent path" rather than a flat "has no read endpoint", so it visibly overrides §2.5's general "resources created under a parent path are read back at their own flat collection URL" instead of silently contradicting it; (ii) the driver-side outcome was phrased as "the driver's own state change is observed by reading the driver" rather than enumerating driver effects, so the sentence makes no claim about `qualification_status` / `qualified_by_user_id` / version bump / disqualify cascade that the following (verbatim, untouched) sentences and `cascade.py` already own.

Items intentionally **not** patched: the two `test_suite/` fixes. `committed_hot_bag_slots` after a refused lock is already fixed by §3.7 ("Insertion raises the route's `committed_hot_bag_slots` …") plus §2.8 ("no side effect of any kind is applied"), and `derive.committed_hot_bag_slots` (`derive.py:183-186`) sums counted stops, which yields 1 for that fixture — no silence. The `expected_return_at` `.000Z` rendering is already pinned by §2.4 ("exactly three fractional-second digits … All datetime fields in requests and responses use that same format") and `clock.iso`; the failure was a helper-format comparison in the test, not a PRD gap. `test_helpers/` had no fixes.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` is non-empty — exactly 2 changed lines (8 diff lines), matching the reported edits at §3.4 (2299 → 2799) and §3.6 (qualification-decision resource). Step 8 therefore genuinely ran rather than copying the file through.

## Step 9 (pass 1 of 3): Complete PRD — kernel/store/clock partition — 2026-09-05T06:35:00.000Z

**Orchestrator note:** Step 9 was deliberately split into three sequential file-partitioned passes over ONE shared `workspace/PRD_COMPLETED.md`. A single subagent cannot hold 3,300 lines of implementation plus a 479-line PRD and still scan exhaustively; the known failure mode is a byte-identical PRD_COMPLETED.md, i.e. the scan silently not happening. Pass 1 performs the `cp` from PRD_FINALIZED.md; passes 2 and 3 are forbidden from copying and only Edit the existing file. Partition: pass 1 = kernel + store + clock; pass 2 = zone + order domain; pass 3 = driver + fleet + dispatch + service recovery.

Pass 1 complete.

**Copy confirmed:** `cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` was performed by me (PRD_FINALIZED.md existed). PRD_FINALIZED.md = 479 lines / 117,467 chars; PRD_COMPLETED.md after my edits = 479 lines / 121,709 chars (**+4,242 chars**, no line-count change — every edit is in-paragraph). Only PRD_COMPLETED.md was touched.

**Counts: 11 ambiguity-pins, 1 mismatch-revision** (across 10 edited lines).

- §2.1 — revise — ambiguity — `X-User-ID` that is whitespace-only counts as empty (`ERR_MISSING_USER_ID`); the five role names are matched exactly, so a differently-cased or whitespace-padded role is an unrecognised role — auth.py:34-39
- §2.1 — insert — ambiguity — MVR pulls and insurance verifications carry no store reference directly or transitively, so no store-scope check applies and any `StoreManager` may read any of them — auth.py:73-74
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case-letter/digit characters — response.py:11-12
- §2.2 — insert — ambiguity — `api_request_timestamp` is envelope metadata taken from the **host wall clock**, not the logical clock; moving the clock does not change it — response.py:15-18
- §2.3 — revise — ambiguity — `limit`/`offset` must be base-10 integer literals; out-of-range values are refused, never clamped, and `meta` echoes the applied values; equal-`created_at` records order by creation sequence (earliest first; latest first when descending), and that tie-break governs every ordered traversal including §2.9 cascades — validate.py:147-172, db.py:101-106
- §2.4 — revise — ambiguity — emitted datetimes truncate the fraction to milliseconds; on input `T`/`t`/space separator, omitted seconds/fraction, `Z`/`z`/numeric offset (normalised to UTC)/no designator (read as UTC) are all accepted, while a bare calendar date is a rule-8 violation — clock.py:13-57
- §2.4 — insert — ambiguity — the clock setter answers 200 with a `data` object whose single field is `current_utc`, and the clock may be wound backwards as freely as forwards — routes/clock_routes.py:12-18
- §2.6 — insert — ambiguity — supplied mileage is quantised half up to two decimals **on intake**, and the quantised value is what is stored/echoed/paid — validate.py:105-123 (calc.q2)
- §2.6 — revise — **mismatch** — elapsed minutes truncate toward zero, not downward: a negative difference (only reachable by winding the clock back) truncates upward toward zero — clock.py:65-71
- §2.8 rule 8 — insert — ambiguity — JSON `null` counts as absent (required→missing, optional→default); required strings must be non-empty; booleans accept only `true`/`false` and integer fields reject booleans; a non-object or unparseable body violates rule 8, while an absent body is read as `{}` — validate.py:14-102
- §3.1 — revise — ambiguity — a `store_number` edit re-supplying the store's own number is not a collision; coordinates supplied on an edit are ignored, not rejected; the edit bumps `version`/`updated_at` unconditionally, so an edit carrying no editable field still counts as a mutation — routes/stores.py:28-32, 63-85
- §4 — insert — ambiguity — undeclared path → `ERR_NOT_FOUND` (404) with trailing slashes tolerated on declared paths; declared path with an unsupported method → `ERR_METHOD_NOT_ALLOWED` (405); these are the only two error ids outside the §5 catalogue — app.py:28, 48-55

**Verified-already-pinned (no change):** the §5 catalogue is byte-exact against `errors.py` (64 ids, 64 statuses, zero divergence); the success/error envelope shapes and `has_more`; the 201-vs-200 convention for `POST /stores` and the clock setter; the §2.5 left-to-right path resolution with the broken-chain short-circuit and the stop-belongs-to-another-route-is-404 rule; the §2.8 4→5→6→7 precedence (scope on resolved ancestors before the first 404); MVR pulls as the single `id`+`created_at`-only resource; every §3.1 store field, default and minimum, plus the cash-reconciliation payload; §2.9/§3.6/§3.11 cascade semantics in `cascade.py`.

**Files audited:** app.py, clock.py, db.py, errors.py, response.py, validate.py, auth.py, listing.py, cascade.py, routes/clock_routes.py, routes/stores.py (read-only cross-checks: routes/drivers.py, routes/dispatches.py, routes/zones.py, routes/fleet.py, calc.py `q2`, test_suite envelope assertions).

## Step 9 (pass 2 of 3): Complete PRD — zone/order partition — 2026-09-05T06:45:00.000Z

Pass 2 complete.

## File size (PRD_COMPLETED.md)
- **Before:** 479 lines / 121,709 chars — **After:** 479 lines / 127,695 chars (+5,986 chars, no new paragraphs or sections)
- **Pass 1 preserved:** confirmed — the `api_request_timestamp` host-wall-clock insert is present, as are pass 1's other markers (mileage "quantised half up on intake", the `earliest-created first` sequence tie-break, the whitespace-only `X-User-ID` rule, the MVR/insurance no-store-reference clause, the 404/405 preamble).

## Counts
- **Ambiguity-pins: 11**
- **Mismatch-revisions: 2**

## Changes
- §2.1 — insert — ambiguity — collection reads apply the ownership test as a silent narrowing (before the published filters, so `total_count` reflects it) rather than a 403; managers narrow on every store-referencing collection, `Driver` narrows on the five driver-referencing ones, the other three roles never narrow — `routes/zones.py:125,188,313`, `routes/orders.py:274` (verified globally against `drivers.py:175`, `fleet.py:82,154`, `dispatches.py:457,484,516`, `complaints.py:174`)
- §3.1 — insert — ambiguity — the polygon ring is stored/echoed in exactly the supplied vertex order and each vertex is reduced to its two coordinate fields, extra keys silently dropped — `validate.py:139-144`, `serialize.py:42`
- §3.2 — insert — ambiguity — filing an address (and opening a dispute, and taking an order) does not bump the parent's `version`/`updated_at` — `routes/zones.py:171,222`, `routes/orders.py:121`
- §3.2 — insert — ambiguity — the two override fields are consulted only as a pair, and §2.3's `zone_state` filter matches the stored field, never `effective_zone_state` — `derive.py:55-59`, `routes/zones.py:192-193`
- §3.3 — revise — ambiguity — dispute birth list now includes `granted_until` null — `routes/zones.py:211-221`
- §3.3 — insert — ambiguity — the action-reservation gate reads the raw `action` before path resolution, so an unrecognised action (or an unreadable body) trips no reservation and falls through to rule 8; `note` may be empty — `routes/zones.py:229-237`, `auth.py:45-51`
- §3.3 — revise — ambiguity — `DENY` still validates but ignores a supplied `granted_until` and leaves the dispute's own null; `GRANT` records the instant on the dispute as well as the address; `WITHDRAW` changes only `status`, leaving the other four fields null — `routes/zones.py:238-275`
- §3.4 — insert — ambiguity — body FKs resolve `store_id` then `service_address_id` (so both-missing reports the store), plus the complete order birth-value list, notably `driver_tip_notice_given` = `false` not null and the six counters at 0 — `routes/orders.py:65-72,86-115`
- §3.4 — insert — ambiguity — `CARRYOUT_ONLY` is the only posture that short-circuits intake: a `CLOSED` store's order is born `PLACED`/`UNDISCLOSED`, and intake never consults the destination's zone state or the store's in-force area — `routes/orders.py:117-120`
- §3.4 — insert — ambiguity — `disclosed_fee_cents`/`disclosed_tip_cents` are required but carry no lower bound, so a negative quote is recorded as inaccurate rather than rejected — `routes/orders.py:180-181`
- §3.5 — **revise — mismatch** — the `ERR_NO_ACTIVE_ZONE_VERSION` precondition was written as a `CLEAR`-only guard; impl applies it to all four zone-decision actions after the state check (and §2.8 rule 17 already said "on the order zone decision"). Moved to the section's opening paragraph as a common precondition — `routes/orders.py:139-140`
- §3.5 — **revise — mismatch** — the `CLEAR` guards were described posture-first; impl (and §2.8 rules 18 → 34) check the address before the posture. Reordered, and pinned that the accrual is additive and leaves `zone_held_at` standing on every path that performs it — `routes/orders.py:142-158`, `routes/zones.py:291-297`
- §3.5 — insert — ambiguity — `START` leaves `ready_at` alone, so a remake's second `READY` overwrites the first pass's value — `routes/orders.py:207-215`

## Audited
`routes/zones.py` (all 9 endpoints incl. `_apply_grant`), `routes/orders.py` (`take_order`, `zone_decision`, `disclose_fee`, `production`, reads/list), `calc.py` (`q2`/`cents`/`ceil_minutes`/`miles_out`, `grid_miles`, `drive_time_estimate`, `point_inside_ring`, `zone_state`, `fee_tier`, `fee_waiver_pct`, `price_order`), `derive.py` (`zone_window_contains`, `in_force_zone_version`, `active_zone_version_number`, `effective_zone_state`, `unassigned_order_count`), `serialize.py` (`zone_version`, `service_address`, `address_dispute`, `order`). Read-only cross-references: `auth.py`, `validate.py`, `clock.py`, `db.py`, `listing.py`, `response.py`, `errors.py`, and the list handlers in `drivers.py`/`fleet.py`/`dispatches.py`/`complaints.py`.

Two notes for the parent: verified-correct-as-written (no edit needed) items were the ray-casting prose, the grid-mileage and drive-time worked examples, the five drive-time model defaults/minimums, the supersession selection rule, and every pricing example in §3.4. I deliberately did **not** touch `remake` / §3.12 — it lives in `orders.py` but the partition assigned §3.12 remedies to pass 3, so **the `remake` endpoint (`routes/orders.py:220-256`) is the one behavior in my files left unaudited**; pass 3 should confirm it covers the remake credit, the `remake_hold_minutes` accrual, the nulling of `door_arrival_at`/`order_to_door_*`, and the `DELIVERED → REMADE` stop cascade.

**Orchestrator note:** pass 3's prompt was amended to explicitly claim the deferred `remake` endpoint (`routes/orders.py:220-256`) so it does not fall between the two partitions.

## Step 9 (pass 3 of 3): Complete PRD — driver/fleet/dispatch/recovery partition — 2026-09-05T06:55:00.000Z

Pass 3 complete. Only `workspace/PRD_COMPLETED.md` was modified.

## File metrics

| | lines | chars |
|---|---|---|
| before pass 3 | 479 | 127,695 |
| after pass 3 | 479 | 133,023 |

All edits were in-paragraph inserts/revisions — no new lines, no new sections, no headings touched (24 `###` before and after).

**Earlier passes verified intact:** pass 1's `api_request_timestamp` host-wall-clock insert is present; pass 2's "`CARRYOUT_ONLY` is the only posture that short-circuits anything" clause is present. `diff PRD_FINALIZED.md PRD_COMPLETED.md` now shows 42 changed lines, of which 19 are mine and 23 carry passes 1–2's work (§2.1–§2.6, §2.8 rule 8, §3.1–§3.5, §4 preamble all still show as modified).

## Counts
- **Ambiguity pins: 13**
- **Mismatch revisions: 6**

## Changes

- **§2.5 (body-FK resolution)** — insert — mismatch — added *route creation* to the list of operations whose body foreign keys are resolved; `POST /dispatches` resolves `driver_id` and was omitted — `routes/dispatches.py:76`
- **§2.8 rule 7** — insert — mismatch — same omission in the refusal ladder; added "route creation (whose `driver_id` reports `ERR_DRIVER_NOT_FOUND`)" — `routes/dispatches.py:73-77`
- **§2.9 (re-derived fields)** — insert — ambiguity — a route's `committed_hot_bag_slots` is never stored: recomputed per read as the sum over counted stops, 0 once `RETURNED`/`SETTLED`/`RECALLED`/`CANCELLED` — `derive.py:183-186`, `serialize.py:215`
- **§3.6 (MVR pull)** — insert — ambiguity — a `CLEAR`/`MINOR_VIOLATIONS` pull leaves any non-`APPLICANT` status alone; a pull against an already-`DISQUALIFIED` driver is stored and still bumps the driver's `version` but drives no transition or cascade whatever its result, and `disqualified_reason` is preserved — `routes/drivers.py:77-82`
- **§3.6 (insurance filing)** — revise — ambiguity — *every* previous certificate is rewritten to `SUPERSEDED` whatever status it held (including one already superseded), each incurring its own `version` increment, walked `created_at` ascending — `routes/drivers.py:100-103`
- **§3.6 (QUALIFY)** — revise — mismatch — the "newest pull must be `CLEAR`/`MINOR_VIOLATIONS`" demand has no error identifier and is not separately tested: a `FAILED` pull has already made the driver terminally `DISQUALIFIED`, so the state check enforces it (three of the four demands are reportable) — `routes/drivers.py:135-145`
- **§3.6 (DISQUALIFY)** — insert — ambiguity — the cascaded routes' `recalled_reason` is the fixed literal `DRIVER_DISQUALIFIED`, never the officer's supplied `reason` — `cascade.py:56`
- **§3.7 (schedule publication)** — revise — ambiguity — retirement is **strictly** earlier `effective_from`, set walked `created_at` ascending; an equal-`effective_from` schedule stays `ACTIVE` (two `ACTIVE` schedules per vehicle class are legal, resolved by the selector's creation-time tie-break); later and already-`RETIRED` ones untouched — `routes/fleet.py:40-51`
- **§3.7 (stop insertion)** — insert — ambiguity — with no version in force, `planned_drive_minutes` falls back to the version named by the address's `evaluated_zone_version_number` (any status), then to 0 minutes per mile → 0; stacking is never refused for want of a delivery area — `derive.py:45-50`, `routes/dispatches.py:126-135`
- **§3.8 (lock insurance gate)** — revise — ambiguity — it is the driver's **newest certificate outright**, which must itself be `VERIFIED` (equivalently `insurance_status` reads `VERIFIED`); a superseded still-covering certificate counts for nothing — `derive.py:132-136`
- **§3.8 (route model)** — insert — mismatch — `minutes_per_mile` is re-read from the version in force *at commitment*, not the insertion-time snapshot (an activation between the two re-times the route); with none in force each leg falls back to the stop's stored `planned_drive_minutes`, read as 0 when null — `routes/dispatches.py:33-45`
- **§3.9 (departure)** — revise — ambiguity — same newest-certificate-outright clarification at the departure gate — `routes/dispatches.py:263`
- **§3.9 (door arrival)** — insert — ambiguity — the three rule-12 state checks have a fixed order: stop (last path parameter), then route, then order; a `LOCKED` route with a `PENDING` stop and an `ASSIGNED` order reports `ERR_INVALID_DISPATCH_STATE`, never `ERR_INVALID_ORDER_STATE` — `routes/dispatches.py:300-305`
- **§3.11 (recall)** — insert — ambiguity — recall does not touch `stop_count`; it stands while `committed_hot_bag_slots` re-derives to 0 — `cascade.py:34-40`
- **§3.12 (remake)** — insert — ambiguity — an order already `ADJUSTED` by an earlier approved complaint stays `ADJUSTED` rather than being refused — `routes/orders.py:245-246`
- **§3.12 (complaint logging)** — insert — mismatch — logging imposes no state gate at all (contra §4's "against a delivered order"); the door-reached test is deferred to the proposal — `routes/complaints.py:47-72`
- **§3.12 (propose remedy)** — insert — ambiguity — a disallowed order status is `ERR_INVALID_ORDER_STATE`, tested after the complaint's own status per rule 12 — `routes/complaints.py:79-87`
- **§3.12 (LATE formula)** — insert — ambiguity — a null `order_to_door_gross_minutes` (exactly the `REMAKE_QUEUED` case) reads as 0, so the overage is negative and the percentage 0 — `calc.py:181-182`
- **§3.12 (approval guards)** — revise — mismatch — the clawback condition is evaluated **above** the balance test per §2.8 (so an approval violating both reports the clawback); the settling route is the one carrying the most recently created `DELIVERED`/`REMADE` stop of the order, so a merely-`RELEASED` stop's route is never consulted; also corrected "guarded twice" → "three times" — `routes/complaints.py:22-33, 122-128`
- **§3.12 (clawback amount)** — insert — ambiguity — the negated `ACTUAL_STOP` line is the most recently created such line for the order — `routes/complaints.py:36-44`

## Audited surface

Fully walked: `routes/drivers.py` (all 8 endpoints), `routes/fleet.py` (all 6), `routes/dispatches.py` (all 14), `routes/complaints.py` (all 5); `calc.py` `route_minutes` / `waterfall` / `order_to_door` / `complaint_remedy`; `cascade.py` `release_pending_stops` / `void_provisional_lines` / `recall_dispatch` / `disqualify_driver`; `derive.py` driver-, dispatch- and cash-side functions (`driver_*`, `newest_mvr_check`, `newest_insurance`, `insurance_covers`, `dispatch_stops`, `counted_stops`, `committed_hot_bag_slots`, `dispatch_store`); `serialize.py` for driver, qualification_decision, vehicle_cost_model, mvr_check, insurance_verification, dispatch, dispatch_stop, reimbursement_line, safe_drop, complaint. Cross-read `validate.py`, `clock.py`, `listing.py`, `auth.py`, `db.py` for the rules those routes depend on.

**The `remake` endpoint was covered** (`routes/orders.py:219-256`): the `remake_credit_cents` accrual by `food_subtotal_cents`, the `remake_hold_minutes` accrual, the nulling of `door_arrival_at` and both `order_to_door_*` figures, and the `DELIVERED → REMADE` stop cascade are all already pinned by §3.12; the one silence found there (the `ADJUSTED → ADJUSTED` settlement self-loop) is patched above.

One observation I deliberately did **not** change, since PRD and implementation already agree: lock's `ERR_FEE_NOT_DISCLOSED` gate accepts only `DISCLOSED` or `CHARGED`, while a remake leaves the order `ADJUSTED` — so a remade order can never be re-locked, making §3.12's "travelling the delivery path again" unreachable past commitment. Both §2.8 rule 29 and §3.8 pin the gate as implemented, so there is no ambiguity to resolve; flagging it only in case it is a design question worth raising elsewhere.

## Step 9 aggregate — 2026-09-05T06:56:00.000Z

Three passes, 44 total edits: **35 ambiguity-pins + 9 mismatch-revisions**.

**Orchestrator verification of the final artifact:**
- `workspace/PRD_COMPLETED.md` exists: 479 lines / 133,023 chars (source `PRD_FINALIZED.md` was 479 lines / 117,467 chars → **+15,556 chars**, 0 line delta since every edit is in-paragraph).
- `cmp PRD_FINALIZED.md PRD_COMPLETED.md` → **differs**, so the known "scan silently never ran" failure mode (byte-identical output) did not occur. `diff` reports 42 changed lines, consistent with the three passes' own tallies.
- Marker greps confirm all three passes' work survives in the shared file: `api_request_timestamp` ×4 (pass 1), `CARRYOUT_ONLY` ×3 (pass 2), `committed_hot_bag_slots` ×7 (passes 2+3).
- Tail is intact: the file still ends at the final §5 error-catalogue row `| ERR_REMEDY_EXCEEDS_TOTAL | 422 |` — no truncation from the chunked editing.
- `find` over `workspace/implementation/`, `test_suite/` and `test_helpers/` for anything newer than `results.1.json` returns **nothing**, so Steps 8 and 9 touched no code or tests: the verified 8×200/200 sweep from Step 7 still describes the artifacts on disk exactly.

**Pipeline complete.** Task 2820 has: SCAFFOLD.yaml + both design indices, worklog.md, test_helpers/ (9 files), test_suite/ (12 files, 200 tests), and workspace/ with INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ (23 files, 61 endpoints) and results.1–8.json all at 200/200.
