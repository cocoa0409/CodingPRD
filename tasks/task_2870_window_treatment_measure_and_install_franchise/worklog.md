# Worklog — task_2870_window_treatment_measure_and_install_franchise

## Step 1: Create task directory — 2026-09-05T09:04:59.323Z

Created pre-assigned task directory `/home/ubuntu/github/CodingPRD/tasks/task_2870_window_treatment_measure_and_install_franchise` and its `workspace/` subdirectory. Index 2870 was fixed by the invocation (no scan/auto-allocation, to avoid collision with the up-to-32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T11:26:30.000Z

All closing checks pass. Final state of the three scaffold artifacts:

Lint verdict (verbatim, final run):
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    49
  §1.1 entities declared:     12
  §1.8 instances scanned:     22
  §1.9 instances scanned:     54
  Calls scanned (§1.8+§1.9):  1175

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files: SCAFFOLD.yaml 3140 lines (§1.0–§1.7, no design keys); SCAFFOLD_DIFFICULTY_DESIGN.yaml 2332 lines (single key scaffold_difficulty_design); SCAFFOLD_CORNER_DESIGN.yaml 5148 lines (single key scaffold_corner_design).

Domain model: `api_prefix: /blinds`, `entity_topology: flat`, `consistency_model: immediate`. 12 entities: Territory, Designer, SampleKit, Lead, Consultation, SampleCheckout, Opening, Quote, Vendor, VendorOrder, InstallJob, LedgerEntry (LedgerEntry is the only `common_fields: false` immutable entity). 10 state machines, 16 calculations, 58 error codes, 4 peer roles (Franchisor / Franchisee / Designer / VendorRep — deliberately not a hierarchy), logical clock via `POST /_clock/set_current_utc`. 49 endpoints (28 writes + 21 reads), all 49 exercised by at least one structured call across §1.8/§1.9.

§1.8 — 9 difficulty rules / 22 instances: `dual_variant_calc` (2), `combinatorial_formula` (3), `non_linear_state_machine` (2), `transitive_cascade` (2), `priority_pair_validation_conflict` (2), `boundary_precision_check` (3), `cross_entity_state_dependency` (3), `resource_temporal_overlap` (3), `compensating_invariant` (2).

§1.9 — 9 sections / 77 instances (54 full + 23 `excluded_because` stubs): entities 9 · state_machines 16 (12+4) · calculations 17 (9+8) · validations 14 (9+5) · endpoints 8 (6+2) · errors 4 (3+1) · rbac 3 (2+1) · cross_cutting_complexity_layers 5 (3+2) · consistency_model 1.

Fixes made during the closing audit:
- Error-catalog coverage gap: `ERR_COMMISSIONING_ATTEMPT_LIMIT` was reachable by no test — the stub claiming §1.8 covered it was wrong. Replaced that stub with a full instance (`the_pair_attempt_budget_is_spent_only_by_accepted_calls_and_then_locks_the_job`): three accepted pair calls each separated by a verify that lands FAILED (1 of 2 channels), fourth pair → 409, then `/complete` → `ERR_COMMISSIONING_NOT_VERIFIED`. All 58 error codes now have an assert-level trigger.
- 12 stub `difficulty_instance:` refs used a `rule_id / instance_name` compound form → normalized to the bare §1.8 instance name (spec requires match by `name`).
- 12 stubs were missing the required `grounds:` key → added.
- Unresolvable grounds: `rbac.<Role>` ×6 → `roles.<Role>`; `complexity_layers.derived_field_reconciliation` / `complexity_layers.pagination_with_filtering` (not in the declared layer list) → real declarations; `calculations.sample_library_counters` in the difficulty file → `calculations.sample_loan_conservation`.
- Added structured calls for the 5 read endpoints that had only prose mentions (`GET /blinds/leads/{id}`, `/openings/{id}`, `/vendor-orders/{id}`, `GET /blinds/quotes`, `GET /blinds/consultations`) with matching asserts.
- Removed the stray whitespace-only line; verified no duplicate names across both design files, no stub carries a `test_recipe`, every full recipe has all four keys, and every `${var}` in every call/assert resolves to an earlier capture (0 problems).
- Note for the orchestrator: `SCAFFOLD.yaml`'s `scenario:` key had picked up the line `Generate task harder than expert level!`. Per the known pipeline hazard (that directive leaks from the scaffold into PRD.md), I stripped that single line; the numbered scenario text itself is verbatim and unchanged.

`worklog.md` and `workspace/` were not touched.

Orchestrator verification: all three files present; `grep -rn "harder than expert"` over the task dir returns nothing — the difficulty directive did not leak.

## Step 3: Copy shared files — 2026-09-05T11:27:57.875Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T11:44:00.000Z

PRD complete and verified.

Deliverable: `workspace/PRD.md` — 466 lines / 102,952 bytes, built with 12 chunked `cat >>` appends (never a single Write).

Section list:
- §1. Introduction
- §2. Global Specifications & System-Wide Principles — 2.1 Actors/Identity/RBAC · 2.2 API Response Structure (verbatim fixed block) · 2.3 Pagination & List Ordering · 2.4 Resource Identity, Timestamps & the Logical Clock · 2.5 Money, Inches & Rounding Discipline · 2.6 Franchise Standing, Territory Exclusivity & the Ledger · 2.7 The Validation Ladder · 2.8 Stale-Version Protection · 2.9 Cascades, Derived Counters & Compensating Actions · 2.10 Addressing & Reverse Reachability (10 subsections)
- §3. Business Logic & Workflows — 3.1 Chartering/Staffing/Lead Routing · 3.2 Sample Library · 3.3 Appointment & Shared Designer Calendar · 3.4 Measuring an Opening · 3.5 Pricing One Opening · 3.6 The Quote & Acceptance · 3.7 Vendor Selection, Lead Times, Capacity · 3.8 Order Settlement, Remakes, Chargebacks · 3.9 Installation, Commissioning, Exceptions, True-Up, Designer Liability (9 subsections)
- §4. API Endpoints (50-row table incl. header)
- §5. Error Codes (59-row table incl. header)

Coverage vs SCAFFOLD.yaml:
- Endpoints: 49/49 — every `(method, path)` pair present as a §4 row; no duplicates.
- Errors: 58/58 — all ids present in prose and in §5; every HTTP status matches the scaffold exactly (0 mismatches); 58 unique rows.
- Calculations: 16/16 — all named calculations narrated; all numeric constants across all 16 verified present in the prose (0 unrepresented).
- State machines: 10/10, transitions 44/44 — every scaffold transition appears as an explicit `FROM → TO` arrow pair, including the parallel `InstallJob.commissioning_status` dimension (one gap found and repaired: `PENDING → NOT_REQUIRED` was only implied, now stated explicitly).
- Validations: 49/49 narrated as the 19-stage §2.7 ladder with `applies_to` endpoint sets enumerated.

Hard Contract reports:
- Contract 1 (Field-Name Coverage) — PASS. 138 required identifiers (entity fields + `request_body` + `query_params` + `path_params`), 0 missing, verified twice: once against the hand-built list and once against an independent PyYAML re-derivation from the scaffold (131 names, a strict subset). Note: the naïve backtick regex mis-parses because the §2.2 fenced JSON block flips code-span parity — the verifier strips fenced blocks first.
- Contract 2 (Rule Coverage) — PASS. Priority ordering, both OCC rules (`expected_consultation_version`/`ERR_STALE_CONSULTATION_VERSION`, `expected_quote_version`/`ERR_STALE_QUOTE_VERSION`, 412), all cascades incl. the four-hop install-exception chain, both `remake_chargeback_waterfall` origins (franchisee-request vs install-exception), all rounding asymmetries and boundary figures, and both `liability_window` variants with their worked boundaries.
- Contract 3 (§3 Path Purity) — PASS. 965 backtick tokens in §3: 0 leading-slash, 0 bare HTTP methods, 0 method+path, 0 slash-containing tokens.

Tail confirmation: the file ends at a real section boundary — the last line is the final complete row of the §5 error table, `| ERR_CREDIT_LIMIT_EXCEEDED | 409 |`, row 58 of 58. Nothing truncated mid-sentence or mid-table.

Constraints honoured: neither design yaml was opened, grepped or referenced; `worklog.md` and all sibling task dirs untouched; scratch confined to `/tmp/task_2870_prd/`; no `pkill`; nothing else in the task dir created or modified.

Orchestrator verification (independent of subagent claim): `wc -l -c` = 466 / 102952; `tail -25` confirms the file ends on the complete final error-table row; `grep -n '^#'` shows all five top-level sections plus 19 subsections present and in order; `grep -in "harder than expert|scaffold|test_recipe"` returns nothing — no difficulty-directive leak and no scaffold-vocabulary leak into the PRD.

## Step 6: Generate implementation — 2026-09-05T12:33:00.000Z

Implementation complete and verified. Final state:

Files written to `workspace/implementation/`:
| file | lines | contents |
|---|---|---|
| `core.py` | 988 | 58-id error table, envelope/meta, auth (4 roles), in-memory `Store` (12 dicts + logical clock), validators, pagination/filters/ordering, lookups, ownership guards, money/royalty, re-derivation of every counter, ledger append, lead routing/promotion, designer score + booking cancellation, calendar geometry |
| `calc.py` | 270 | every declared constant plus ordered dimensions, billable sqft, opening pricing, quote waterfall, cordless gate, order cost, lead time, vendor capacity, remake waterfall, remeasure charge, sample late fee, liability party |
| `routes_admin.py` | 335 | territories, designers, sample-kits, leads, `/_clock/set_current_utc` (15 endpoints) |
| `routes_consult.py` | 369 | consultations, sample-checkouts, openings + configuration (13) |
| `routes_quote.py` | 223 | quote assembly/supersession, present, revise, accept (6) |
| `routes_order.py` | 385 | vendors, placement/selection, ship, receive, remake (8) |
| `routes_install.py` | 268 | install jobs, commissioning pair/verify, exception cascade, complete (7) |
| `app.py` | 57 | blueprint wiring + `ApiError`/`HTTPException`/`Exception` envelope handlers |
| `start.sh` | 8 | `exec python3 app.py`, `$PORT` (fallback 10000), binds `0.0.0.0`, foreground, guarded (never re-installs when Flask present) |
| `requirements.txt` | 1 | `Flask>=2.0` |

2904 lines total; every file passes `ast.parse`. No `__pycache__`, no seeded rows, no SQLite/JSON/tmp persistence (the only `json.dump*` call is the response body). Cold boot on a fresh port returns `total_count: 0` and clock `2026-08-01T00:00:00.000Z`.

Tallies:
- Endpoints: 49/49. `app.url_map` enumerates exactly 49 rules, matching PRD §4's 48-row table plus `POST /_clock/set_current_utc`. No extra surface: `GET /blinds/territories` and `GET /blinds/vendors` (not in §4) correctly 405.
- Errors: 58/58. Programmatic diff against the §5 table: no missing id, no extra id, no status mismatch, and all 58 are actually raised somewhere in the code.

Covered — state machines: territory status; designer `ACTIVE/SUSPENDED/INACTIVE` (incl. auto-suspend at score < 80 and the cancellation sweep of future-only bookings); lead `NEW→ROUTED/QUEUED/UNROUTABLE` + `CONSULT_COMPLETE/CONVERTED/LOST` with capacity release and single queued-lead promotion; consultation; kit `AVAILABLE/ON_LOAN/LOST`; check-out `OPEN/RETURNED/LOST`; opening `measure_status` × `install_outcome`; quote `DRAFT/PRESENTED/ACCEPTED/EXPIRED/SUPERSEDED`; vendor order `PLACED/SHIPPED/RECEIVED/REMAKE_REQUESTED/CANCELLED`; install job `install_status` × `commissioning_status` as genuinely independent dimensions.

Calculations verified by hand against every PRD worked example: floor/ceil-to-eighth ordered dimensions, 12-inch billable floors and quarter-sqft round-up, two-rounding opening price with 72-inch surcharge, the pinned six-step quote waterfall (tier from pre-discount total, discount base = subtotal only), install fee 7500 + 2500·n + 4500·m, provisional royalty at acceptance and the install true-up as a difference of two independently rounded royalties (zero delta writes no row), 42 % order cost rounded once, cutoff roll + motor adder + 4-day expedite then 5-day floor, per-calendar-date vendor headcount, the 3-bucket remake waterfall with the 15000-cent territory cap, remeasure charge 35 % capped at 12000 (round then cap), liability score 100 − 22e − 9l + 3c clamped, sample late fee 750/day capped at replacement value with the 14-day write-off threshold, half-open designer calendar with the conditional 45-minute travel buffer, closed-interval kit holds that collide on `OPEN` and `RETURNED` records, and credit exposure re-derivation.

Smoke tests (all green, servers on ports the subagent chose, each killed by exact PID): five scripts under `/tmp/task_2870_impl/` — happy path + error probes; `PART1` supersession / stale-version 412s / revise cycle / capacity-vs-no-eligible-vendor / REPLACEMENT + FULL_CREDIT remakes; `PART2` the four-hop install-exception cascade (`MEASURER` liability, charge 12000, buckets 0/15000/3586, expedited lead time 8, designer suspended at 78, true-up −1841); `PART3` commissioning (`NOT_APPLICABLE`/cert/hub/channel-count/attempt-limit, 3-attempt cap, verify FAILED→re-pair), cord-hazard gate, and expiry flipping the quote to `EXPIRED` and the lead to `LOST` while still rejecting with `ERR_QUOTE_EXPIRED`; `PART4` the whole sample library (fee 750, write-off 40000 at 18 days, cap 5000 at 8 days, inclusive hold conflict, 73→`SUSPENDED`) plus the exact 45-minute travel-buffer boundary; `PART5` no-show → promotion, `UNROUTABLE`, credit-limit breach, `NOT_REQUIRED` commissioning, zero-delta true-up writing no ledger row, and every list filter. Ledger rows carry no `updated_at`/`version` and are ordered by `occurred_at` then `created_at`.

PRD ambiguities and the interpretation chosen:
1. Uniqueness breaches (territory postal exclusivity, vendor name, kit code) → `ERR_INVALID_REQUEST` 400, after range checks. A `LOST` kit's code is re-issuable.
2. `replacement_value_cents` < 1 → 400 `ERR_INVALID_REQUEST`, not 422: ladder stage 8 explicitly enumerates its guarded endpoints and `POST /blinds/sample-kits` is absent. (Most likely disagreement point with the test suite.)
3. `service_postal_code` ≠ lead's `postal_code` → 400 `ERR_INVALID_REQUEST`. The PRD names no error; stage 9's `ERR_CROSS_TERRITORY_FORBIDDEN` is attached only to the designer-territory sentence. (Second most likely disagreement point.)
4. Non-`PENDING` opening at placement → `ERR_OPENING_ALREADY_ORDERED`; at exception → `ERR_OPENING_NOT_ON_QUOTE`, checked after `ERR_INSTALL_JOB_NOT_SCHEDULED` so a finished job reports its own state.
5. Consultation close-out with zero measured openings or an open loan, and an early no-show → `ERR_CONSULTATION_NOT_SCHEDULED` (no dedicated id exists).
6. VendorRep on another vendor's order → `ERR_ROLE_NOT_PERMITTED` 403 after existence; an unresolvable actor id (any role) → 401.
7. Vendor `motorization_extra_days` / `cutoff_hour_utc` / `concurrent_capacity` treated as optional with the PRD defaults 0/17/2 despite the scaffold marking them required.
8. Pagination: non-integer → 400, out-of-range → 422. Franchisee list reads are scoped to their own territory rather than 403.
9. 5-day lead-time floor applied unconditionally (not only on remakes); `FULL_CREDIT` always writes its reversal row, while a zero install true-up writes none; exception hop 2 fires only when the order is `RECEIVED`, and the cascade does not re-derive the consultation (no such hop is declared).

## Step 5: Generate unit tests — 2026-09-05T13:26:00.000Z

Step 5 test generation for task 2870 is complete.

Deliverables (both directories at the TASK ROOT, not under `workspace/`):

`test_helpers/` — 2041 lines: `__init__.py` 29, `api_client.py` 338, `api_errors.py` 157, `assertions.py` 315, `constants.py` 193, `factories.py` 414, `fixtures.py` 487, `test_users.py` 85, `types.py` 23.

`test_suite/` — 7700 lines, 26 files: `conftest.py` 22; queue A: `test_01` 123, `test_02` 230, `test_03` 158, `test_04` 132, `test_05` 140, `test_06` 234, `test_07` 341, `test_08` 353, `test_09` 169, `test_10` 201, `test_11` 262, `test_12` 120, `test_13` 174, `test_14` 140, `test_15` 178, `test_16` 162; queue B: `test_20` 480, `test_21` 738, `test_22` 881, `test_23` 804, `test_24` 615, `test_25_error_catalog.py` 356, `test_26_rbac_and_ownership.py` 206, `test_27_cross_cutting_layers.py` 355, `test_28_consistency_model.py` 126.

Translation tally:
- 107 tests total, each with exactly one `Design:` line as the docstring's last line; 53 queue A, 54 queue B; every tag resolves to a real instance `name:` in the source yaml (audited programmatically).
- Queue A (Difficulty §1.8): 22 non-stub instances, 22 translated, 0 skipped.
- Queue B (Corner §1.9): 77 instances, 23 carry `excluded_because` (stubs, not translated), 54 non-stub, 54 translated, 0 skipped.

Verification: all 35 files pass `ast.parse`; `pyflakes` clean except three intentional `conftest.py` notices (side-effect import of `api_errors`, which registers the error→HTTP map, and the fixtures star-import). `verify_quotes.py` returns `ok` for every suite file — every ≥40-char quoted span survives a literal grep of `PRD.md`. `python3 -m pytest test_suite --collect-only -q` collects 107 tests in 0.82s, proving every module imports and every helper name referenced exists. Per-file `Design:`-tag-vs-dump-name diffs printed `TAGS_MATCH` for tests 25–28. `ls workspace/` shows only `INSTRUCTION.md`, `PRD.md`, `implementation`, `run_sweep.sh` — no `test_helpers/` or `test_suite/` leaked there. `worklog.md`, `PRD.md`, `INSTRUCTION.md`, `SCAFFOLD*.yaml` and `workspace/implementation/` were never written or read (PRD read-only); all scratch lived in `/tmp/task_2870_tests/`; no server was started and no `pkill` was run.

Design-dump defects corrected against the PRD (not copied):
1. Three dumps assert a freshly created DRAFT quote already carries `subtotal_cents` (4960 / 9920) — PRD §3.6 stamps "all of its monetary fields at zero", so the tests assert 0 on the draft and the figure after `present`.
2. `errors` instance 3 claims the two motorized openings' `install_outcome` is null — PRD §3.4 stamps `PENDING`.
3. `endpoints` instance 6's `install_fee_cents` 22500 / `total_cents` 59800 → PRD arithmetic gives 24500 / 61800; its `measure_status ORDERED` is not a declared enum member (`QUOTED` asserted).
4. `endpoints` instance 2's `open_leads_count == 1` → acceptance converts the lead, so 0.
5. Two omissions inside otherwise-translated instances, both failing the uniquely-derives test: `paging_and_filtering…`'s `limit=0` / `limit=101` → `ERR_VALUE_OUT_OF_RANGE` (PRD §2.3 bounds the limit but names no error id, and ladder rung 8's endpoint list excludes list endpoints), and its `?postal_code=` filter on leads (PRD §2.7 declares leads filterable by `territory_id` and `status` only). The paged walk was re-expressed over the unfiltered leads collection, preserving the instance's paging-plus-filtering claim.
6. Bug fixed in previously written `test_23_validation_ladder.py`: `world["job"]` → `world["install_job"]` (that is the key `fixtures.single_opening_job` actually sets).

Orchestrator verification (independent): `ls` of the task root shows `test_helpers/` and `test_suite/` present; `ls workspace/` confirms neither leaked under workspace/ (only INSTRUCTION.md, PRD.md, implementation/, run_sweep.sh). `python3 -m pytest test_suite --collect-only -q` → 107 tests collected in 0.78s. Steps 5 and 6 were launched in a single assistant message, so the implementation generator ran with physical isolation from test_suite/ (the directory did not exist at its spawn time).

## Step 7: Run tests and iterate — 2026-09-05T14:05:00.000Z

Clean sweep achieved. `worklog.md` untouched (13:30, before the subagent started), no stray processes, and the 8 passing `results.{1..8}.json` are left in place in `$IMPL_DIR`.

Iterations run: 2 (iteration 1 = baseline diagnosis, iteration 2 = verification after fixes)

Tests deleted: none. All 6 failures traced to a real implementation defect or a test artifact inconsistent with the PRD; every asserted rule was verbatim-covered and uniquely derivable.

Fixes applied to `test_helpers/`: none — the helper layer was already PRD-faithful (money as JSON ints, instants as full ISO-8601-UTC, four peer roles with distinct `X-User-ID` bindings).

Fixes applied to `test_suite/`:
- `test_suite/test_27_cross_cutting_layers.py` — `test_the_appointment_version_moves_only_for_the_writes_that_land` and `test_paging_and_filtering_compose_over_one_collection`: both sent `source="SHOWROOM"`, which is not one of PRD §3.1's four declared `source` members (`NATIONAL_CALL_CENTER`, `WEB_FORM`, `REFERRAL`, `WALK_IN`), so the PRD-faithful implementation correctly rejected the setup with `ERR_INVALID_REQUEST`. Changed to `WALK_IN`.
- `test_suite/test_23_validation_ladder.py` — `test_every_gate_satisfied_at_its_exact_boundary_still_passes` asserted `subtotal_cents == 2420` on the freshly-built quote, contradicting PRD §3.6 ("A new quote is stamped `DRAFT` with … all of its monetary fields at zero" / "Presenting … is the moment the price is computed"). Moved the four money assertions to the post-presentation response and added the PRD-required `DRAFT`/zero-subtotal check.

Fixes applied to `implementation/`:
- `core.py::parse_instant_strict` — accepted `"2026-08-01 08:00:00"` (space separator, no UTC designator) as a valid instant, so a malformed `requested_at` created a lead with 201. PRD §2.7 stage 7 requires `ERR_INVALID_REQUEST` when "an instant is not a valid ISO 8601 UTC string"; now requires the literal `T` separator and an explicit UTC designator.
- `core.py::require_territory_ownership` — rejected any row whose territory linkage did not equal the acting franchisee's id, including `QUEUED`/`UNROUTABLE` leads whose `territory_id` is null. PRD §2.1 conditions the check on "any row that references a territory" and rejects only a row "belonging to another territory"; a null linkage references no territory. Added a `None` guard.
- `routes_admin.py::list_designers`, `list_sample_kits`, `list_leads`; `routes_order.py::list_orders`; `routes_install.py::list_jobs` — each silently filtered a `Franchisee`'s list result to its own territory. That filter is declared nowhere in the PRD, and it contradicts §2.3's definition of `total_count` as "the number of rows matching the request's filters". Removed; every franchisee list call in the suite already passes its own explicit filter, so the declared inversion filters of §2.10 carry the scoping.

Final tally: 107 / 107 passing in all 8 parallel rounds (0 failed, 0 errors, no flakiness — the 6 baseline failures were deterministic in all 8 rounds, and the fixed suite is green in all 8).

Orchestrator verification (independent): all 8 `results.$i.json` parsed directly — every round reports `passed=107 failed=0 total=107 errors=0`. The baseline sweep (13:34) had recorded 101/107 with 6 deterministic failures in all 8 rounds, so the failures were genuine defects, not load-induced transport flakiness. `find . -name "worklog*.md"` returns only the single task-root worklog (no cwd-drift stray under workspace/). `grep` for `sqlite3` / `json.dump(` across the implementation returns nothing — storage remains in-memory only, so per-test-server isolation wipes all state. Step 8 is NOT skipped: Step 7 applied 3 implementation fixes and 2 test_suite fixes.

## Step 8: Finalize PRD — 2026-09-05T14:10:00.000Z

PRD_FINALIZED.md is written. Three surgical edits, all traceable to the `<step_7_diff>` implementation fixes; the two `test_suite/` fixes needed no PRD change (both were fixture artifacts contradicting prose already verbatim in the PRD).

File sizes: PRD.md 466 lines / 102,952 bytes → PRD_FINALIZED.md 466 lines / 103,967 bytes. Line delta 0 (+0.0%); byte delta +1,015 (+0.99%). All edits are inline extensions of existing sentences; no new sections, no reflow.

Changes:
- §2.1 (Franchisee identity bullet) — insert — null territory linkage does not trigger the ownership check, so an unrouted `QUEUED`/`UNROUTABLE` lead is not withheld from any franchise owner — `implementation/core.py:716-729` (`require_territory_ownership`, `require_territory_ownership_row`).
- §2.3 (Pagination and List Ordering) — insert — list endpoints apply no implicit caller/role scoping; result rows are the whole collection reduced only by the request's own query-string filters; the territory ledger listing is confined by its path `{territory_id}`, not by a caller filter — `routes_admin.py:195-199, 244-248, 313-318`, `routes_order.py:242-246`, `routes_install.py:101-106`, `core.py:590-596`.
- §2.7 stage 7 (Request shape) — revise — pinned the lexical form of a valid client-supplied instant: literal `T` separator plus explicit UTC designator (`Z` or zero `+00:00`/`-00:00` offset); space separator, missing designator, or non-zero offset are invalid — `core.py:145-167` (`parse_instant_strict`), reached via `core.py:475`.

Per-edit pre-edit search log:

1. §2.1 null-linkage edit. (a) Subject: the stage-5 territory ownership check and every row whose territory linkage can be null. (b) Enumerated: `grep -rn require_territory_ownership` over all modules → `core.py:716` (guard itself), `core.py:728` (`_row` wrapper, passes `None` when the territory row is unresolvable), and all 14 callsites: `routes_admin.py:115,123,143,169,191,211,240,309`, `routes_consult.py:34,36`, `routes_install.py:49,51,97`, `routes_order.py:158,238,271,355`. Read `routes_admin.py:280-318` (lead intake sets `territory_id: None` and only `ROUTED` fills it; `read_lead` passes `lead.get("territory_id")`) and `routes_consult.py:26-45` (`create_consultation` already had its own independent `if lead.get("territory_id")` truthiness guard, so booking behavior is unchanged and still reaches `ERR_CROSS_TERRITORY_FORBIDDEN` when a designer's territory differs from a null lead territory). Designer/SampleKit rows always carry a non-null `territory_id`; VendorOrder/InstallJob linkage is derived (`territory_of_order`, `territory_of_job`) and can be `None` only on a broken chain. (c) Adjustment: wrote the rule generically over "a row whose territory linkage is null" with the unrouted lead as an illustrative "for instance" rather than as the only case, so the derived-`None` VendorOrder/InstallJob paths and any future nullable linkage stay described; deliberately did not say the check is skipped for consultation booking, since that endpoint's own cross-territory stage still rejects.

2. §2.3 list-scoping edit. (a) Subject: what population a list endpoint considers, and whether caller identity ever reduces it. (b) Enumerated: every GET route (`grep '@bp.route' | grep GET`) — 21 total; read each list handler: `list_designers`, `list_sample_kits`, `list_leads` (`routes_admin.py`), `list_consultations`, `list_sample_checkouts`, `list_openings` (`routes_consult.py`), `list_quotes` (`routes_quote.py`), `list_orders` (`routes_order.py`), `list_jobs` (`routes_install.py`), plus the nested `list_ledger_entries` (`routes_admin.py:119-131`). Confirmed there is no list endpoint for territories or vendors at all, that `core.py:571-596` (`apply_filters`/`list_response`) reads filters only from the query string, and that single-resource reads are a separate story (ownership enforced on `read_territory`, `read_designer`, `read_sample_kit`, `read_lead`, `read_order`, `read_job`; not enforced on `read_consultation`, `read_checkout`, `read_opening`, `read_quote`, `read_vendor`). Also re-read the §4 preamble, which defers ownership rules to §2.1 and so does not conflict. (c) Adjustment: scoped the sentence strictly to list endpoints and said nothing about single-resource reads — an earlier draft added "single-resource reads still enforce the §2.1 check", which would have been a false universal given consultation/quote/opening/check-out/vendor reads perform no ownership check. Added the explicit ledger-listing carve-out so "never narrowed by caller identity" cannot be read as forbidding the path-scoped ledger query.

3. §2.7 stage 7 instant-form edit. (a) Subject: lexical validity of every client-supplied instant. (b) Enumerated: `grep -rn "req_instant|opt_instant|parse_instant_strict|fromisoformat"` → single parser at `core.py:145`, reached only via `core.py:475` (`req_instant`) / `core.py:481` (`opt_instant`), used by exactly six client-facing fields: `requested_at` (`routes_admin.py:288`), `current_utc` on the clock endpoint (`routes_admin.py:329`), `scheduled_start_at`/`scheduled_end_at` (`routes_consult.py:39-40` and `routes_install.py:54-55`), `hold_start_at`/`hold_end_at` (`routes_consult.py:142-143`). Also checked that the `YYYY-MM-DD` manufacturing dates are computed server-side (`fmt_date`, `core.py:180`) and never parsed from a client, and cross-read §2.4's rendering rule and §5's `ERR_INVALID_REQUEST` row for consistency. (c) Adjustment: left fractional-second width unconstrained (the parser delegates to `datetime.fromisoformat` and accepts 0-6 digits, so mandating three would have contradicted the impl), and phrased it as "a client-supplied instant" so §2.4's rendering contract for server output is untouched.

Completeness: PRD_FINALIZED.md is complete and untruncated — 466 lines, same line count as PRD.md, `diff` shows exactly the three intended single-line hunks and nothing else, and the file ends at a real section boundary (`| ERR_CREDIT_LIMIT_EXCEEDED | 409 |`, the last row of the §5 error table).

Orchestrator verification (independent): `wc -l -c` = 466 / 103967 vs PRD.md 466 / 102952; `diff PRD.md PRD_FINALIZED.md` yields 6 changed lines (3 hunks, revise-in-place); `cmp` reports the files DIFFER (Step 8 genuinely ran); tail confirms the file ends on the final §5 error-table row.

## Step 9: Complete PRD — 2026-09-05T14:47:00.000Z

Run as THREE SEQUENTIAL module-partitioned passes over one shared `workspace/PRD_COMPLETED.md` (pass 1 did the `cp`; passes 2 and 3 were explicitly forbidden from re-running it, and each verified the prior passes' hunks by grep probe before starting). Partition: pass 1 = `app.py` + `core.py` + `calc.py`; pass 2 = `routes_admin.py` + `routes_consult.py`; pass 3 = `routes_quote.py` + `routes_order.py` + `routes_install.py`. Total 48 hunks — 41 ambiguity-pins, 8 mismatch-revisions (one of which corrected a pass-1 edit, see pass 3 §2.9).

### Pass 1 (app.py + core.py + calc.py) — 16 edits (15 ambiguity-pins, 1 mismatch)

Created `PRD_COMPLETED.md` with `cp PRD_FINALIZED.md PRD_COMPLETED.md`. 466 lines / 103,967 chars → 467 lines / 110,528 chars (+1 line, +6,561 chars); 14 hunks = 13 in-paragraph revisions + 1 new bullet inside the existing §2.2 error-format list. No new sections.

- §2.1 — insert — ambiguity — an unrecognised/missing `X-User-Role` yields `ERR_UNAUTHENTICATED` (not 403), and a `Franchisee`/`Designer`/`VendorRep` id naming no row is 401 (not 404), because entity binding is part of resolution — core.py:328-351
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case-alphanumeric chars — core.py:189-193
- §2.2 — insert — ambiguity — `api_request_timestamp` reads the host wall clock, not the logical clock, so it does not follow `/_clock/set_current_utc` — core.py:196-200
- §2.2 — insert (new bullet) — ambiguity — transport failures reuse the error envelope with `ERR_INVALID_REQUEST` at 404/405/400/500 rather than 400; trailing slashes address the same endpoint — app.py:23,34-47
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` is 400 vs out-of-domain 422; empty-string value = absent; no `offset` ceiling — core.py:549-568
- §2.3 — insert — ambiguity — `created_at` ties break on creation sequence (the universal final tiebreaker, never exposed as a field); ledger adds it as a third key after `occurred_at`,`created_at` — core.py:282,292-297
- §2.3 — insert — ambiguity — filters match textually; empty-string filter ignored, undeclared query params ignored, null stored value matches nothing — core.py:571-587
- §2.4 — insert — ambiguity — all stored instants (`created_at`/`updated_at`/`occurred_at`/`*_at`) come from the logical clock; rendering truncates below millisecond width — core.py:170-177,273-283
- §2.5 — insert — ambiguity — inches/percentages render as bare JSON numbers with no significant trailing zeros (`48.500` → `48.5`) — core.py:203-216
- §2.7 stage 4 — insert — ambiguity — only present JSON-string FKs resolve here; absent/null/wrong-typed FKs fall through to stage 7's `ERR_INVALID_REQUEST` — core.py:655-665
- §2.7 stage 7 — insert — ambiguity — postal-code shape is a stage-7 failure; lower-case `z` accepted; body parsed from raw bytes regardless of `Content-Type`; empty/absent body = `{}`; non-object body rejected; explicit `null` ≡ omitted; booleans never accepted as int/number — core.py:370-457,519-526
- §2.7 stage 8 — revise — ambiguity — royalty rate's four-decimal-place limit is an `ERR_VALUE_OUT_OF_RANGE` domain failure, not a stage-7 shape failure — core.py:529-543 / routes_admin.py:45
- §2.9 — revise — MISMATCH — PRD claimed a territory's "four money totals" are re-derived; only three are (`royalty_accrued_cents`, `remake_chargeback_cents` from the ledger, `open_order_exposure_cents` from live orders). `net_sales_cents` is carried forward by signed adjustments — core.py:775-799
- §2.9 — insert — ambiguity — re-derivation bumps territory/kit/consultation/vendor unconditionally, even when nothing changed; a designer bumps only on an actual counter/score change or suspension; a quote's opening counters are re-derived with no bump — core.py:775-844,938-951
- §3.1 — insert — ambiguity — queue promotion's final tiebreak is creation sequence, and promotion does not re-test capacity (reachable after HQ lowers `lead_capacity_per_week`) — core.py:869-894
- §3.4 — insert — ambiguity — ordered-dimension derivation is unguarded arithmetic; a deduction driving a dimension to ≤ 0 is stored as computed, the §3.5 twelve-inch floor being what keeps it priceable — calc.py:70-95,98-105

Pass 1 deliberately left alone (already pinned uniquely, non-obvious): the 58-row §5 error table is byte-for-byte identical to `core.ERROR_STATUS` including ordering (verified programmatically, zero id or status divergence); half-up "away from zero" money rounding matching `money()`'s `ROUND_HALF_UP`; every calc.py constant and rounding order (two per-opening rounding steps and oversize test on billable width; six-step waterfall with tier from `pre_discount_total_cents` and discount base `subtotal_cents`; single round over summed retail at 42%; cutoff roll on `hour >= cutoff_hour_utc`; expedite-then-floor lead time; three-bucket remake waterfall with floor-halved `SHARED_50_50` and 15000 cap; round-then-cap remeasure charge; ceil-day lateness and value-capped late fee; liability boundaries 0.375/2.500; score 100/−22/−9/+3 clamped 0..100 with strict `< 80` suspension); calendar geometry (half-open intervals, buffer as a property of the pair, `start < other_end + buffer and other_start < end + buffer`, 45 minutes); vendor capacity as an inclusive-both-ends per-date headcount over `PLACED`/`SHIPPED`/`REMAKE_REQUESTED`; the §2.1 territory-ownership null-linkage carve-out and the two territory `version` bumps on a freeing-plus-promotion; `LedgerEntry` carrying only `id` + `created_at`.

### Pass 2 (routes_admin.py + routes_consult.py) — 13 edits (11 ambiguity-pins, 2 mismatches)

No `cp` and no Write; every change an in-place `Edit`. Pass 1's hunks verified intact by re-probing 12 of its distinctive strings. Bytes 110,528 → 116,422 (+5,894); lines 467 → 467 (all in-paragraph).

- §2.4 — insert — ambiguity — a `PATCH` supplying no recognised field, or only identical values, still refreshes `updated_at` and bumps `version` — core.py:286 via routes_admin.py:107, routes_admin.py:181, routes_consult.py:366
- §2.4 — insert — ambiguity — the clock may move backwards (no monotonicity) and the call answers 200 with an empty object as `data` — routes_admin.py:325-331, core.py:240
- §3.1 — insert — ambiguity — negative `credit_limit_cents` is 422; postal-exclusivity breach is `ERR_INVALID_REQUEST` 400 decided by the first offending entry in request order and evaluated after the numeric-domain stage, so an out-of-range royalty rate wins over a taken code — routes_admin.py:43-56
- §3.1 — insert — ambiguity — the five patchable terms are exhaustive (`postal_codes` supplied here is ignored, not rejected), and any standing may be re-stated into any other, `TERMINATED` included in both directions — routes_admin.py:83-107
- §3.1 — insert — ambiguity — the designer suspension/retirement cascade is keyed on the transition, so re-stating an already-`SUSPENDED` designer bumps the row and cancels nothing — routes_admin.py:182-183
- §3.1 — insert — ambiguity — lead intake performs no ownership check, so a `Franchisee` may intake a lead that routes to another territory — routes_admin.py:281-283
- §3.1 — insert — ambiguity — routing is part of creation: the created lead reads `version` 1 with `updated_at == created_at` in all three outcomes, while the winning territory is bumped — routes_admin.py:270-273, core.py:277-282
- §3.2 — insert — ambiguity — `replacement_value_cents` < 1 and a `kit_code` collision are both `ERR_INVALID_REQUEST` 400 (stage 8 does not guard this endpoint), both decided before the franchise-standing check; collision is territory-scoped and skips `LOST` kits so a written-off code is re-issuable; adding a kit re-derives and bumps the territory — routes_admin.py:216-232
- §3.3 — revise — ambiguity — `service_postal_code` ≠ the lead's `postal_code` is `ERR_INVALID_REQUEST` 400 decided before the end-after-start 422; no precondition on the lead's `status`, so an unrouted lead fails as `ERR_CROSS_TERRITORY_FORBIDDEN` while a `CONVERTED`/`LOST` lead in-territory books normally; past windows and multiple appointments per lead are admissible — routes_consult.py:42-48
- §3.3 — revise — ambiguity — close-out's three business preconditions all report `ERR_CONSULTATION_NOT_SCHEDULED` 409, tested status → measured count → open loans, and a failing attempt leaves `version` unchanged — routes_consult.py:87-96
- §3.3 — revise — ambiguity — an early no-show is also `ERR_CONSULTATION_NOT_SCHEDULED` 409, tested after the status check — routes_consult.py:112-117
- §3.4 — revise — MISMATCH — "a supersession is only meaningful against a `REMEASURE_REQUIRED` opening" implied a guard that does not exist; same-consultation membership is the only test, the superseded row is untouched, and two openings may name the same predecessor — routes_consult.py:274-276
- §3.4 — revise — MISMATCH — a new opening's `motorization_option` is stamped `NONE`, not null (PRD grouped it with the null fields) — routes_consult.py:308

### Pass 3 (routes_quote.py + routes_order.py + routes_install.py) — 19 edits (14 ambiguity-pins, 5 mismatches)

No `cp`, no Write, no new sections, no new lines. Bytes 116,422 → 126,836 (+10,414); lines 467 → 467. Verified all 29 previously-differing lines still differ and re-probed three pass-1 strings and five pass-2 strings — all present. Headings 27 and table rows 111 unchanged in both files.

- §2.1 — insert — ambiguity — `InstallJob` joins the Franchisee-ownership row set, and order placement is checked against the named quote's territory before any `VendorOrder` row exists — routes_install.py:97, routes_order.py:158
- §2.7 stage 5 — insert — MISMATCH — same enumeration corrected in the ladder, incl. install-job creation checking order territory then designer territory — routes_install.py:49,51,97
- §2.6 — revise — MISMATCH — "`ROYALTY_REVERSAL` always negative / others always positive" is false: royalty amounts are rounded products and are 0 at a zero `royalty_rate_pct`; §3.6/§3.8 rows are written anyway, only §3.9's true-up suppresses — routes_quote.py:215, routes_order.py:344
- §2.9 — revise — MISMATCH — pass 1's "quote `version` moves only for §3.6 and §3.7" corrected to §3.6–§3.9 (full credit and true-up also `touch(quote)`) — routes_order.py:339, routes_install.py:250
- §3.6 (supersession) — insert — ambiguity — sweep set fixed before any write so a failed `ERR_QUOTE_HAS_NO_OPENINGS` supersedes nothing; a `REMEASURE_REQUIRED` opening is detached but not swept; an already-overtaken `PRESENTED` quote is neither superseded nor flipped — routes_quote.py:73-103
- §3.6 (present) — revise — MISMATCH — the non-null `fabric_code`/`lift_system` requirement is structurally guaranteed by the sweep, carries no error id and is unreachable — routes_quote.py:153-159
- §3.6 (accept) — insert — ambiguity — the `NET_SALES_ROYALTY` row is unconditional (zero amount at rate 0); conversion keys on the lead's own status alone, any other status is left alone and frees no capacity — routes_quote.py:213-222
- §3.7 (vendors) — insert — ambiguity — `base_lead_time_days` required; `motorization_extra_days` ≥ 0; `concurrent_capacity` unbounded above; name collision is `ERR_INVALID_REQUEST` 400 after all four numeric domains — routes_order.py:52-60
- §3.7 (placement) — insert — ambiguity — stage-4 order `quote_id` → each string of `opening_ids` in array order → `preferred_vendor_id`; opening not-found outranks the array's cardinality/duplicate rules; ownership on the quote's territory precedes the shape stage — routes_order.py:150-158
- §3.7 (placement) — revise — ambiguity — a non-`PENDING` opening reports `ERR_OPENING_ALREADY_ORDERED`, tested before the live-order overlap — routes_order.py:177-187
- §3.7 (lead time) — revise — MISMATCH — the five-day floor applies unconditionally, not only on the remake branch — calc.py:186
- §3.8 (ship) — insert — ambiguity — a foreign `VendorRep` gets `ERR_ROLE_NOT_PERMITTED` 403 after existence; reads/lists are unrestricted; ship re-derives nothing and bumps neither vendor nor territory — routes_order.py:252-263
- §3.8 (remake) — insert — ambiguity — `credit_scope` required and shape-tested before `ERR_ORDER_NOT_RECEIVED`; the four guards run in the stated order, all behind `RECEIVED` — routes_order.py:356-369
- §3.8 (replacement) — insert — ambiguity — re-placement re-tests no eligibility, no capacity, no credit, keeps a now-`SUSPENDED` vendor, and is one mutation so `version` +1 and `REMAKE_REQUESTED` is never observable — routes_order.py:301-316
- §3.8 (full credit) — insert — ambiguity — openings keep `install_outcome` `PENDING`; the reversal row is unconditional incl. zero amount; chargeback row precedes reversal row at one `occurred_at`; territory re-derived, vendor not — routes_order.py:319-348
- §3.9 (scheduling) — insert — ambiguity — stage-4 order `vendor_order_id` → `designer_id`; ownership checked twice; several jobs may share one order, designer calendar the only conflict test — routes_install.py:45-67
- §3.9 (pair) — insert — ambiguity — pairing is the only operation in the API that examines `certifications` — routes_install.py:126
- §3.9 (pair) — insert — MISMATCH — the channel-count test precedes the attempt-cap test (§3.9's narrative order implied the reverse) — routes_install.py:134-138
- §3.9 (exception) — insert — ambiguity — the already-resolved opening reports the same `ERR_OPENING_NOT_ON_QUOTE` but after `ERR_INSTALL_JOB_NOT_SCHEDULED` while membership precedes it; no `ERR_ORDER_NOT_RECEIVED` guard — routes_install.py:177-182
- §3.9 (cascade) — insert — ambiguity — hop 2 fires only when the order is still `RECEIVED` (else silently skipped, exception still 200) and bypasses cap/policy/window/capacity/credit; hop 3's recompute runs on every liable party; the consultation is never re-derived; remeasure row precedes remake row — routes_install.py:194-210
- §3.9 (true-up) — insert — ambiguity — the re-statement bumps the quote's `version` and leaves `credited_net_sales_cents` alone — routes_install.py:249-250

Pass 3 cross-check: every `error_id` raised in `routes_quote.py`, `routes_order.py` and `routes_install.py` (33 distinct, plus `ERR_VALUE_OUT_OF_RANGE` via `check_range`) now has a PRD passage pinning it uniquely; `ERR_MOTOR_OPTION_MISMATCH` and `ERR_INSUFFICIENT_MOUNT_DEPTH` live only in `routes_consult.py` (pass 2's partition) and were left untouched.

### Orchestrator final verification

- `wc -l -c`: PRD.md 466 / 102,952 → PRD_FINALIZED.md 466 / 103,967 → PRD_COMPLETED.md 467 / 126,836.
- `cmp PRD_FINALIZED.md PRD_COMPLETED.md` → DIFFERENT (the completeness scan genuinely ran; a byte-identical PRD_COMPLETED.md would have meant the scan never happened).
- `diff PRD_FINALIZED.md PRD_COMPLETED.md` → 95 changed lines across 48 hunks; heading count (27) and table-row count (111) identical in both, so no section was added or dropped.
- `tail` confirms PRD_COMPLETED.md still ends at the real final section boundary, the last §5 error-table row `| ERR_CREDIT_LIMIT_EXCEEDED | 409 |` — not truncated.
- `grep -in "scaffold|harder than expert|test_recipe"` over PRD_COMPLETED.md returns nothing: no scaffold vocabulary and no difficulty-directive leak survived into the final contract.
- `find` proves no file under `workspace/implementation/`, `test_suite/` or `test_helpers/` is newer than `results.1.json`, so the recorded 107/107 × 8-round green sweep still describes exactly the delivered code. Steps 8 and 9 touched only PRD documents.

PIPELINE COMPLETE — Step 9 has written workspace/PRD_COMPLETED.md.
