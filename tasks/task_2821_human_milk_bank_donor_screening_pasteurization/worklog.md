# Worklog — task_2821_human_milk_bank_donor_screening_pasteurization

## Step 1: Create task directory — 2026-09-05T02:34:31.448Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2821_human_milk_bank_donor_screening_pasteurization` and its `workspace/` subdirectory. Index 2821 was pre-assigned by the invoking harness (no scan/auto-allocation performed, per instruction, because up to 32 pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-05T04:59:21.601Z

Subagent summary (verbatim):

Scaffold generation for task 2821 is complete and lint-clean.

## Files

| File | Lines |
|---|---|
| `.../SCAFFOLD.yaml` | 3251 |
| `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1335 |
| `.../SCAFFOLD_CORNER_DESIGN.yaml` | 3395 |

All three parse as valid YAML (`ALL THREE PARSE OK`). `SCAFFOLD.yaml` has only the §1.0–§1.7 flat keys (`scenario, domain_name, api_prefix, response_envelope, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles`) — no design keys; each design file has exactly its one top-level key.

## SCAFFOLD.yaml counts
15 entities · 8 state machines · 3 concurrency rules · 7 calculations · 49 validations · **52 endpoints** · 49 errors · 8 roles. `domain_name: human-milk-bank-screening-pasteurization`, `api_prefix: /milk-bank`, `role_model: segregation_of_duties`, `consistency_model: immediate`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy]`.

## Design index instance counts
- **§1.8 difficulty: 19 instances across 9 rule blocks** (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
- **§1.9 corner: 86 instances across all nine guide sections** — entities 12, state_machines 17, calculations 12, validations 23, endpoints 6, errors 5, rbac 4, cross_cutting_complexity_layers 6, consistency_model 1. 64 carry a full `test_recipe`; 22 are `excluded_because:` stubs, every one citing an existing §1.8 instance.

## Verification
- `scaffold_lint.py`: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (2242 calls scanned, 19 §1.8 + 64 §1.9 instances).
- All 49 error codes are referenced by at least one instance; all 52 endpoints are hit by at least one structured `call:`; instance names are globally unique across both design files; no forbidden concurrency vocabulary.

## Two things for the parent
1. **`scenario:` in SCAFFOLD.yaml still begins with the literal line `Generate task harder than expert level!`** — strip that line after Step 2 so the difficulty directive cannot leak into PRD.md.
2. The task dir also contains a pre-existing `worklog.md` and empty `workspace/` from Step 2; I left both untouched.

### Orchestrator post-step action
Per the known leak path, the orchestrator stripped the two leading lines (`Generate task harder than expert level!` + blank) from the `scenario:` block of SCAFFOLD.yaml. `grep -rn "harder than expert"` over all three scaffold files now returns no match, and SCAFFOLD.yaml still parses as valid YAML with `scenario` beginning at `2821. Human Milk Bank ...`. `workspace/` and `worklog.md` both survived Step 2 intact (no rebuild needed).

## Step 3: Copy shared files — 2026-09-05T04:59:41.530Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T05:16:40.000Z

Subagent summary (verbatim):

PRD generation is complete.

## Output

- **Path:** `.../workspace/PRD.md`
- **Size:** 436 lines / 103,503 bytes
- Written incrementally (1 `Write` + 12 heredoc appends); ends at a real boundary — the completed final row of the §5 table, `| \`ERR_SUBSIDY_CAP_EXCEEDED\` | 402 |`, followed by a trailing newline. No mid-sentence truncation at any of the 12 append junctions (verified programmatically).

## Section list

`# Human Milk Bank Screening Pasteurization API — Product Requirements Document`
- **1. Introduction**
- **2. Global Specifications & System-Wide Principles** — 2.1 Operators, Roles and Donor-Scoped Access · 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`, incl. both `####` subheads) · 2.3 Pagination, Filtering and List Ordering · 2.4 Resource Identity, Audit Fields and the Logical Clock · 2.5 Ordered Rejection: How a Request Is Evaluated · 2.6 Money, Millilitres and Rounding Discipline · 2.7 Stale-Read Protection on Shared Parents · 2.8 Cascade Discipline and Derived-Field Propagation · 2.9 Segregation of Duties Across the Processing Chain · 2.10 Per-Operation Check Ordering · 2.11 Addressing Model: Flat Collections and Reverse Reachability
- **3. Business Logic & Workflows** — 3.1 Enrolling a Donor and Triaging Her Health History · 3.2 Clinical Clearance: Serology, Physician Approval and Qualification · 3.3 Deferral Events, Lookback Recall and the Road Back to Screening · 3.4 The Cold Chain: Dispatch, Receipt and Courier Reimbursement · 3.5 Building a Pool: Donor Spread and Nutritional Balance · 3.6 Pasteurization Run Control: Three Dimensions on One Row · 3.7 Bottling, Lot Identity, Shelf Life and QA Release · 3.8 Demand: Prescriptions, Priority Tiers, the Waitlist and Subsidy Programs · 3.9 Filling a Prescription: Nine-Step Pricing, Safety Gates and Reversal · 3.10 The Allocation Cycle and Time-Driven Expiry
- **4. Endpoint Definitions** (4-column table)
- **5. Error Code Catalogue** (2-column table)

## Coverage verification

- **Endpoints: 52 / 52.** Every scaffold endpoint appears as an exact `| METHOD | \`path\` |` row in §4; 0 missing. Table row count = 52 (+1 header).
- **Errors: 49 / 49.** All 49 distinct `error_id`s appear in §5 with the exact scaffold HTTP status (0 mismatches), **and** all 49 are additionally used in the §1–§3 prose (0 catalogue-only errors).

## Hard Contracts

**Contract 1 — Field-Name Coverage: PASS.** 141 unique required names (134 entity fields + 70 request-body inputs + 18 query params, deduped). 141 / 141 appear inside inline-code spans outside fenced blocks; 0 missing. (`prescription_id` was the single initial gap and was added to §3.9.)

**Contract 2 — Rule Coverage: PASS.** Mechanically checked: all 8 state machines' initial, terminal, `from` and `to` states present (0 missing across every entity); all enum literals from every entity field's `one of {...}` constraint present (0 missing); all calculation constants present (the three flagged by the naive matcher — `ZONE_BASE_CENTS` 1200/1850/2600, `QUARANTINE_CREDIT_FACTOR` as "one half", `ALCOHOL_TIER_POINTS` 0/5/15/45 — were confirmed present in prose form). Manually walked: 49 ordered validations (global order in §2.5, per-operation chains in §2.10, plus in-situ ordering in §3.9), 3 OCC rules (§2.7), the 5-hop deferral recall and 4-hop culture cascade, `applies_to` scopes, field-level defaults, and sibling-branch symmetry (receipt 3-way fork, disposition ACCEPT/REJECT, DRAFT/BALANCED, RELEASED/EXHAUSTED, TEMPORARY/PERMANENT, the two named risk-score variants, the two named reimbursement variants).

**Contract 3 — §3 Path Purity: PASS.** 1,040 inline-code spans in §3 scanned: 0 `/`-leading tokens, 0 bare HTTP methods, 0 method+path pairs. 0 raw `/milk-bank...` mentions anywhere in §3, and 0 method+path strings in §1-§2.

Also swept: no fuzzy hedges (one `typically` was rewritten into a precise monotonicity statement about `screening_risk_score` vs `surveillance_risk_score`), no TODO/TBD, no pseudocode (the only 2 fenced blocks are the two verbatim JSON envelopes in §2.2), and no Hard-Contract/meta text inside the document. §2.3's 14 ordering bullets were cross-checked against the 16 list endpoints (two bullets each cover a pair of collections sharing an ordering) and every query filter was diffed against the scaffold input lists — exact match.

Constraints honoured: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped or referenced; no sibling `task_*/` directory and no `worklog.md` was read or written; scratch files live only in `/tmp/task_2821_prd/`.

### Orchestrator post-step verification
Independently confirmed the anti-truncation guardrail: `wc -l` = 436 lines / 103,503 bytes; `tail -12` ends on the complete final table row `| \`ERR_SUBSIDY_CAP_EXCEEDED\` | 402 |` (a real section boundary, not mid-sentence); top-level headings present at lines 1/3/11/163/323/382 (§1–§5, none dropped). `grep -in "harder than expert|scaffold|difficulty_design|corner_design|test_recipe"` over PRD.md returns no match — the difficulty directive did not leak. No regeneration needed.

## Step 6: Generate implementation — 2026-09-05T05:50:00.000Z

(Launched concurrently with Step 5 in a single orchestrator message, so the implementation generator started before `test_suite/` existed on disk — physical isolation from the test artifact. Step 6 returned first; Step 5 was still running at this point.)

Subagent summary (verbatim):

The implementation is complete, smoke-verified, and all my smoke servers are shut down.

## File inventory — `workspace/implementation/`

| file | lines | role |
|---|---|---|
| `app.py` | 88 | Flask app, 6 blueprints at `/milk-bank`, request hooks, error handlers |
| `start.sh` | 16 | `$PORT` from env, `0.0.0.0`, foreground `exec python3 app.py` (executable) |
| `requirements.txt` | 1 | `Flask>=2.0` |
| `errors.py` | 93 | the single 49-code catalogue + `ApiError`/`fail`/`not_found`/`invalid`/`out_of_range` |
| `envelope.py` | 87 | PRD §2.2 envelope + §2.3 pagination (`ok`/`ok_list`/`page`/`error_response`) |
| `auth.py` | 92 | `guard(*roles)`, header auth, donor-scope `require_own` |
| `validate.py` | 123 | two-phase shape-then-range validation |
| `store.py` | 146 | in-memory dicts, logical clock, version discipline |
| `util.py` | 124 | ids, ISO-8601 formatting, Decimal/ROUND_HALF_UP helpers |
| `serializers.py` | 297 | 15 `*_out` projections |
| `listing.py` | 40 | shared list filtering/ordering |
| `domain_donor.py` / `domain_shipment.py` / `domain_pool.py` / `domain_run.py` / `domain_dispense.py` / `domain_sweep.py` / `domain_bubble.py` | 322 / 68 / 106 / 205 / 255 / 51 / 29 | state machines, calculations, cascades, clock sweep, bubble-ups |
| `routes_donors.py` / `routes_shipments.py` / `routes_pools.py` / `routes_runs.py` / `routes_lots.py` / `routes_rx.py` | 373 / 275 / 243 / 236 / 88 / 296 | 13 / 9 / 7 / 8 / 4 / 11 endpoints |

3654 lines total; no `services/` or `routes/` leftovers, no `__pycache__`, nothing but source in the directory.

## Endpoints — 52, exact match with the PRD

Dumped `app.url_map`, normalised path params, and diffed against the 52 rows of the PRD endpoint table: **byte-identical, zero diff** in both directions.

## Centralisation

- **Errors**: one `ERROR_STATUS` dict in `errors.py` maps all 49 ids to their HTTP status; routes only call `fail("ERR_...", msg)`, which raises `ApiError`; `app.py` has the single `@errorhandler(ApiError)`. Diffed the catalogue against every `ERR_*` in the PRD (49 = 49, no diff) and cross-checked every `(HTTP nnn)` the PRD states next to an id — **no status mismatches**.
- **Envelope**: only `envelope.py` builds `meta`/`response_type`/`data`; `error_response` is reused by the `ApiError`, 404, 405 and catch-all handlers, so a bad path or wrong method also returns a proper `ERR_RESOURCE_NOT_FOUND` envelope.
- **Version discipline**: `store.touch()` applies the single `version`/`updated_at` bump on first touch per request, so multi-hop cascades increment once and the response body already shows post-increment values.
- **Bubble-ups**: `after_request` runs `domain_bubble.bubble_up()` for non-GET/<400 responses, then closes the mutation window.

## Smoke results

Booted with `bash start.sh` on `PORT=51821` / `51822` (own PIDs captured and killed individually; no `pkill` ever used). A scripted end-to-end walk covered: 4 donors enrolled -> health history -> serology -> physician approval -> qualify; shipments received on both the clean-`ACCEPTED` and the `QUARANTINED` fork with medical-director `ACCEPT` top-up; containers logged with OCC token; pool built from 3 donors -> `BALANCED` -> `COMMITTED`; run scheduled -> 4 readings -> complete -> culture -> bottling; QA release; subsidy program -> prescription -> manual fill -> void -> allocation cycle; clock advance.

Verified figures matched hand calculation: Z2 + dry ice reimbursement 2403 cents; quarantine 45-min excursion -> penalty capped at 0.60 -> final 960, credited 480 at receipt, topped to 960 on `ACCEPT`; thermal hold 1800 s -> `PASSED`; lot expiry 2026-08-01 + 180 d = 2027-01-28; fill 400 ml -> gross 1920 / subsidy 1152 / payer 768.

Negative paths all returned the right id and status: `ERR_MISSING_AUTH_HEADERS` 401, `ERR_ROLE_NOT_PERMITTED` 403, `ERR_DONOR_SCOPE_VIOLATION` 403, `ERR_DUPLICATE_CODE` 409, `ERR_INVALID_REQUEST` 422 (bad regex and bad `limit=0` pagination), `ERR_RESOURCE_NOT_FOUND` 404 for an unknown path, `ERR_SHIPMENT_STATE_INVALID` 409, `ERR_READING_SEQUENCE_INVALID` 409, `ERR_SOD_RELEASE_CONFLICT` 403, `ERR_SOD_DISPENSE_CONFLICT` 403, `ERR_CLOCK_NOT_MONOTONIC` 409, and `ERR_DONATION_STATE_INVALID` correctly preceding the OCC check per the §2.10 order.

Two "failures" printed by my throwaway script were wrong expectations in the script, not defects: I guessed 412 where the §2.10 order legitimately rejects on donation state first, and 409 where the catalogue (and PRD) assign 403 to `ERR_SOD_RELEASE_CONFLICT`.

**No-disk-state proof**: three separate cold boots each started with `total_count=0` on all seven collections and replayed the identical walk; the implementation directory's contents were byte-for-byte unchanged after a full run (`start.sh` also sets `PYTHONDONTWRITEBYTECODE`, so not even `__pycache__` is written).

Untouched as required: nothing outside `implementation/` was read or written — no `test_helpers/`, no `test_suite/`, no `worklog.md`. Scratch files live only in `/tmp/task_2821_impl/`.

## Step 5: Generate unit tests — 2026-09-05T07:05:00.000Z

Subagent summary (verbatim):

Test generation for task_2821 is complete.

## File inventory (all at the task root, nothing written inside `workspace/`)

`test_helpers/` — 9 files, 3117 lines (Stage 1, unmodified this session):
`__init__.py` 108, `api_client.py` 295, `api_errors.py` 135, `assertions.py` 586, `constants.py` 153, `factories.py` 336, `fixtures.py` 834, `test_users.py` 106, `types.py` 564

`test_suite/` — 8 files, 6876 lines, **102 tests**:

| file | lines | tests |
|---|---|---|
| `conftest.py` | 67 | – (session `api` fixture + per-role header fixtures) |
| `test_01_donor_intake_and_risk.py` | 744 | 17 |
| `test_02_cold_chain_and_reimbursement.py` | 638 | 17 |
| `test_03_pooling_and_nutrition.py` | 1249 | 19 |
| `test_04_pasteurization_and_thermal.py` | 1298 | 20 |
| `test_05_dispensing_and_fiscal.py` | 1641 | 18 |
| `test_06_deferrals_and_recall.py` | 668 | 6 |
| `test_07_access_control_and_read_surface.py` | 571 | 5 |

## Design-index coverage (audited by AST over the two source YAMLs)

- **Queue A (§1.8 difficulty): 19 / 19 non-stub instances translated, every one with >=2 tagged tests** (`with_ge2=19`).
- **Queue B (§1.9 corner): 64 / 64 live instances translated, each with >=1 tagged test.** The 22 instances carrying `excluded_because:` are stubs and were never translated (not skips).
- Every test carries exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line at the end of its docstring, copied verbatim; no untagged, dual-tagged or dangling tags.
- **229 `PRD: "..."` citation lines all survive a literal substring grep against `workspace/PRD.md`** (`checked=229 bad=0`).
- `pytest --collect-only` collects all 102 tests cleanly; pyflakes is clean; no `skip`/`xfail` markers and no mention of the scaffold anywhere in the generated code.

## Instances SKIPPED under the PRD-first filter

**None.** Two designs needed restructuring rather than skipping, because their asserted outcome was not uniquely PRD-derived as written:

1. `Corner/cross_cutting_complexity_layers/selector_policy_fefo_tie_is_broken_by_smaller_available_volume_before_lot_code` — the design's demand order relied on `created_at` separating two same-tier orders created at the same frozen logical instant (PRD §2.4 does not list `created_at` among the clock-stamped instants, so a tie is legal and `remaining_ml DESC` would reverse the draw). Rewritten as two sequential allocation cycles with one live order each, with draws asserted as a `{lot_id: volume}` mapping instead of row order; the FEFO-tie claim itself is preserved.
2. `Corner/validations/fill_time_guards_reject_a_back_dated_order_a_cancelled_order_and_a_second_release` — the design literal `waitlist_position == 1` for the partly-filled order contradicts the PRD's bucket ordering; the PRD-derived 1/2 is asserted with an inline note.

Other adjustments to design literals were format-only (e.g. `SUB-01` -> `SUB-0001` to satisfy the documented code pattern).

## Notable helper-level finding (left untouched, per the "do not modify `test_helpers/`" rule)

`fixtures.released_lot()` / `held_lot()` call `build_chain(...)` without `run=`, so `build_chain` returns right after the commit and they hand back `chain.lots == []`. No test uses them — modules 03-07 build chains through local `_uniform_chain` / `_released_chain` / `_canonical_chain` helpers instead.

### Orchestrator post-step verification
Checked the known "test dirs land under workspace/" failure mode: `find workspace -maxdepth 2 -name test_helpers -o -name test_suite` returns nothing, and `test_helpers/` + `test_suite/` both sit at the task root as required. `workspace/` contains exactly `INSTRUCTION.md`, `PRD.md`, `implementation/`. No relocation needed. `workspace/implementation/start.sh` confirmed to read `$PORT`, set `PYTHONDONTWRITEBYTECODE`, and `exec` the server in the foreground.

## Step 7: Run tests and iterate — 2026-09-05T07:26:00.000Z

Subagent summary (verbatim):

Step 7 complete — all 8 sweep rounds green.

## Summary

**Iterations run:** 2 (sweep #1: 92/102 in all 8 rounds, 10 deterministic failures; sweep #2: 102/102 in all 8 rounds)

**Tests deleted:** none. Every failure traced to a verbatim PRD sentence and was either a faithful-test/broken-fixture-call issue or a genuine implementation defect. No PRD-silence or non-derivability collapse was found.

**Fixes to `test_suite/` (STEP 2, test-vs-PRD consistency):**

- `test_suite/test_04_pasteurization_and_thermal.py` — 7 chain-setup call sites (lines 149, 264, 318, 379, 444, 599, 1235) omitted `run={}`. `fx.build_chain` returns early when `run is None`, so `chain.run` stayed `None` and `chain.lots` stayed `[]`; the tests then hit `TypeError: 'NoneType' object is not subscriptable`, `IndexError`, or asserted `pool.status == PASTEURIZED` against a still-`COMMITTED` pool. Added `run={}` (the suite's established convention, already used at 13 other sites). The three deliberate `run=None` sites (495, 546, 811) and the two `commit=False` sites were left untouched.
- `test_suite/test_03_pooling_and_nutrition.py` — `test_the_donations_component_channel_lists_both_draws_in_created_order` drew 400 ml then 300 ml from one donation into **two different pools**, which PRD §3.5 forbids outright (`ERR_COMPONENT_ALREADY_ALLOCATED`); the setup 409'd. Rewrote both draws into the same pool, which the same sentence explicitly permits ("it does not prevent a second draw from the same donation into the *same* pool"). All assertions kept, with pool total 400+300 -> 700 and the pagination probe keyed on `allocated_volume_ml` instead of the removed second pool.
- `test_suite/test_05_dispensing_and_fiscal.py` — `test_a_back_dated_order_a_cancelled_order_and_a_second_release_are_refused` expected RX-5003 at `version=2` after cancellation. Filling RX-5002 drops its `remaining_ml` 200->100, which renumbers the tier-1 bucket (`created_at` asc -> `remaining_ml` desc -> code asc) and moves RX-5003 from position 3 to 2 — a derived-field-only mutation that PRD §2.4 requires to increment ("increases by exactly 1 on every mutation of that row — including mutations that only change a derived field"). Cancellation then adds the third. Corrected to `version=3`; this is consistent with the test's own later position assertions.

**Fixes to `test_helpers/`:** none needed.

**Fixes to `implementation/`:**

- `workspace/implementation/store.py` — added `DB.rearm(*rows)`, which re-opens the per-request audit window for named rows so their next real field change takes another `version` increment. `touch()`'s absorb rule exists for cascades (§2.8: one increment per row per cascade) and must stay, but it was also swallowing the second fill of an allocation cycle.
- `workspace/implementation/domain_dispense.py`, `run_allocation_cycle` — call `db.rearm(prescription, lot, program)` before each `apply_fill`. PRD §3.10: "Every draw creates a fill exactly as a manual fill would ... applying the same ledger consequences to the lot, the subsidy program and the prescription", and §3.9's lot/program ledger consequences each read "with a `version` increment". §3.10 also names the *only* per-fill consequence a cycle suppresses (waitlist renumbering, deferred to cycle end), so by exception-listing the version increments apply per draw. Previously a cycle creating two fills against one lot advanced it by 1 instead of 2 (`assert 3 == (2 + 2)` in `test_the_outpatient_order_gets_only_the_spare_above_the_reserve`). The end-of-cycle `renumber_all()` deliberately runs without a re-arm, so an order's deferred renumbering is absorbed into its own fill increment, matching §3.9's "its tier bucket is renumbered and its `version` increments by 1".

**Final sweep (8 concurrent rounds, `setsid nohup`, per-test-server isolation):**

| round | passed / total |
|---|---|
| 1 | 102 / 102 |
| 2 | 102 / 102 |
| 3 | 102 / 102 |
| 4 | 102 / 102 |
| 5 | 102 / 102 |
| 6 | 102 / 102 |
| 7 | 102 / 102 |
| 8 | 102 / 102 |

Zero failures, zero errors, zero skips in every round — no flakiness signal. No assertion was weakened, no `skip`/`xfail` added, no endpoint or field invented, and storage remains in-memory dicts only. `worklog.md` untouched.

### Orchestrator post-step verification
Independently parsed all 8 `workspace/implementation/results.$i.json` files (per the known "subagent claims a clean sweep with no artifacts behind it" failure mode): every round reports `passed == total == 102`. The baseline sweep was also independently observed by the orchestrator at 92/102 in all 8 rounds — identical in every round, so the 10 failures were deterministic and none was load-induced flakiness. Step 8 will NOT be skipped: Step 7 ran 2 iterations with 3 `test_suite/` fixes and 2 `implementation/` fixes.

## Step 8: Finalize PRD — 2026-09-05T07:31:30.000Z

Not skipped: Step 7 ran 2 iterations with 3 `test_suite/` fixes and 2 `implementation/` fixes, so the skip condition (zero fixes on the first sweep) did not apply. The Step 7 worklog entry was handed to the subagent verbatim as `<step_7_diff>`.

Subagent summary (verbatim):

Done. `PRD_FINALIZED.md` written with two inline edits.

## Size
- PRD.md 436 lines / 103,503 bytes; PRD_FINALIZED.md 436 lines / 104,671 bytes — 0.0% line delta, +1.13% bytes. No sections added, no prose deleted.

## Changes
- **§3.10 (Allocation Cycle)** — insert — appended to the "Every draw creates a fill..." paragraph: the audit consequences of §3.9 apply **once per draw, not once per cycle** (each draw increments the `version` of the lot it drains, the prescription it credits, and the linked program whenever that draw moves `consumed_cents`; two draws from one lot => lot `version` +2), and the single end-of-cycle renumbering is *not* a further mutation of a prescription the cycle already filled, while an unfilled prescription takes one increment iff that pass changes its position — `implementation/store.py:110-125` (`DB.rearm`) and `implementation/domain_dispense.py:254-258` (`rearm` before each `apply_fill`, bare `renumber_all()` at the end).
- **§3.8 (Waitlist)** — insert — one sentence after the renumbering-trigger list: a renumbering pass rewrites only positions that genuinely change; a prescription whose recomputed position is unchanged takes no `version` increment from the pass — `implementation/domain_dispense.py:93-107` (`renumber_tier` writes via `set_field`) + `implementation/store.py:102-108`.

No PRD edit for the three other Step 7 items: the `test_04` `run={}` omissions are a `build_chain` call-site convention bug (`test_helpers/fixtures.py:637-662` — "leaving `run` None stops before scheduling"), the `test_03` two-pool double draw is forbidden verbatim by §3.5/§2.10, and the `test_05` `version=3` correction is derivable verbatim from §2.4 + §3.8 + §3.9.

## Per-edit pre-edit search log

**Edit 1 (§3.10)**
- (a) Subject: per-row `version` increment counting inside a multi-write request, specifically the allocation cycle's fills and its end-of-cycle renumbering.
- (b) Enumerated/read: `store.py` in full (`touch` absorb rule, `set_field` change-guard, new `rearm`, `begin`/`commit`); `domain_dispense.py` in full (`apply_fill` lot/program/prescription writes, `void_fill`, `reopen_prescription`, `renumber_tier`/`renumber_all`, `run_allocation_cycle`); `routes_rx.py:100-289` (create/fill/cancel/void/cycle routes and their `renumber_tier` calls); repo-wide grep for `rearm|touch(|renumber` across all `routes_*.py`/`domain_*.py`/`app.py` — `rearm` occurs **only** in the cycle, so every other request (recall/scrap/culture cascades, sweep) keeps one increment per row per request; `domain_sweep.py` in full; unconditional `touch()` sites at `routes_shipments.py:239` and `domain_pool.py:106`.
- (c) Adjustments: (i) restricted the program clause to "whenever the draw moves that program's `consumed_cents`", because `apply_fill:130-134` skips the program entirely when `subsidy_cents` is 0 — an unqualified "each draw increments the program" would have been false; (ii) framed the rule as a scoped exception to §2.8 ("a cycle is a sequence of independent fills, not the single cascade...") instead of restating §2.8, so the cascade paths that still absorb to one increment are not contradicted; (iii) made the unfilled-prescription clause conditional ("if and only if that pass changes its position") to match `set_field`'s change-guard.

**Edit 2 (§3.8)**
- (a) Subject: whether a waitlist renumbering pass mutates rows whose computed position is unchanged.
- (b) Enumerated/read: `domain_dispense.py:93-107` (sole renumber implementation) and all six of its callsites — `routes_rx.py:132` (creation), `:242` (manual fill), `:256` (cancel), `domain_dispense.py:192` (void/reopen), `:258` (end of cycle), `domain_sweep.py:36` (clock sweep); `store.py:102-108` (`set_field` writes only on real change) and `store.py:83-100` (per-request absorb); also checked the two unconditional `touch()` sites to confirm neither is a renumber.
- (c) Adjustment: dropped an initially drafted second half that said a moved prescription "takes one" increment — for the filled or cancelled order the move is absorbed into the increment §3.9/§3.8 already grants, so the claim would have double-counted. Replaced with the non-committal "is a mutated row by §2.4", leaving the total-increment arithmetic to the existing verbatim sentences.

### Orchestrator post-step verification
`diff` confirms `PRD_FINALIZED.md` is NOT byte-identical to `PRD.md` (104,671 vs 103,503 bytes; both 436 lines, so the two edits were in-paragraph inserts as intended).

## Step 9: Complete PRD — 2026-09-05T08:14:00.000Z

Run as **three sequential module-partitioned passes over one shared `PRD_COMPLETED.md`** rather than a single full scan. Rationale (orchestrator decision, made without escalation per the autonomy directive): the implementation is 3,658 lines across 22 modules / 52 endpoints, and a single-agent exhaustive scan of that surface reliably under-covers — the classic failure signature being a `PRD_COMPLETED.md` that comes back byte-identical to its source because the scan never really ran. Partitioning by implementation module keeps each pass's reading set small enough to be genuinely exhaustive. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden to copy and edited the file additively in place. Each later pass was told which modules the earlier passes owned, which items they had deferred, and not to duplicate or contradict prose already inserted (including Step 8's §3.8/§3.10 inserts).

Partition:
- **Pass 1** — `app.py`, `envelope.py`, `errors.py`, `auth.py`, `validate.py`, `util.py`, `routes_donors.py`, `domain_donor.py` (global surface + donor lifecycle).
- **Pass 2** — `routes_shipments.py`, `domain_shipment.py`, `routes_pools.py`, `domain_pool.py`, `routes_runs.py`, `domain_run.py` (cold chain, pooling, pasteurization).
- **Pass 3** — `routes_lots.py`, `routes_rx.py`, `domain_dispense.py`, `domain_sweep.py`, `domain_bubble.py`, `store.py`, `serializers.py`, `listing.py` (lots, dispensing, fiscal, sweep, store/serializer/listing internals).

### Pass 1 summary (verbatim)

Done. Pass 1 complete.

## Setup (pass 1's responsibility)
`cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` performed. Source 436 lines / 104,671 chars -> output **436 lines / 112,627 chars, char delta +7,908**. All 24 diff hunks are single-line in-paragraph replacements; heading count unchanged (29 -> 29), no new sections, no line-count change.

## Counts
- ambiguity-pins: **19**
- mismatch-revisions: **5** (§2.1 donor-list filtering, §2.3 "each ordering is total", §3.1 stored-score ordering claim, §3.2 reason_code enum, §4 `X-Role`)

Every claim I inserted was verified empirically against the implementation in-process via Flask's `test_client` (no server, no port bound).

## Changes
- §2.1 — revise — mismatch — donor-scope: path-addressed donor sub-collections *reject* (before existence resolution) rather than being silently filtered; the only filtered channel is the flat shipment list — `auth.py:88-92`, `routes_donors.py:102`, `routes_shipments.py:117-121`
- §2.1 — insert — ambiguity — a whitespace-only auth header counts as empty -> `ERR_MISSING_AUTH_HEADERS` — `auth.py:37-43`
- §2.2 — insert — ambiguity — `api_request_id` = `req_` + exactly 20 chars from `[A-Z0-9]` — `util.py:31-32`
- §2.2 — insert — ambiguity — `api_request_timestamp` is the host wall clock, not the logical clock — `envelope.py:21-25`, `util.py:35-36`
- §2.3 — insert — ambiguity — bad/non-integer/out-of-bounds `limit`/`offset` -> `ERR_INVALID_REQUEST` (never `ERR_FIELD_OUT_OF_RANGE`); empty string = omitted; offset past `total_count` yields an empty page — `envelope.py:61-81`
- §2.3 — revise — mismatch — orderings are not total; ties resolve by insertion order, oldest first, in every list channel — `listing.py:32-40`, `store.py:66-68`
- §2.3 — insert — ambiguity — empty-string filter values and unrecognized query params are ignored — `listing.py:6-29`
- §2.4 — insert — ambiguity — accepted ISO-8601 input spellings (space/`T`, optional seconds, any fractional width, `Z`/offset/naive->UTC) vs. the fixed `...SS.mmmZ` output; strict 10-char dates — `util.py:17-81`
- §2.5 — insert — ambiguity — unrouted path *and* undeclared method both answer `ERR_RESOURCE_NOT_FOUND` 404 before check 1 (no 405 ever); unattributable failures -> `ERR_INVALID_REQUEST` 422 — `app.py:61-77`
- §2.5 — insert — ambiguity — shape phase also covers string length/`contains`, booleans rejected for numeric fields, explicit `null` == absent (default for optional), absent/non-object body == `{}`, all shapes before any range — `validate.py:27-117`
- §2.8 — insert — ambiguity — one `version` increment per row per cascade (not per hop), no-op writes are not mutations, rows created this request stay at 1, and the new `version`/`updated_at` appear in the causing response — `store.py:83-108`
- §2.8 — revise — ambiguity — bubble-up runs only at the end of a successful non-GET request (status < 400) — `app.py:46-55`
- §2.11 — insert — ambiguity — trailing slash tolerated on every path — `app.py:35`
- §3.1 — insert — ambiguity — "newest questionnaire" final tie-break is the last-recorded row, opposite to the list page's insertion tie-break — `domain_donor.py:37-43`
- §3.1 — revise — mismatch — the stored `screening_risk_score`/`surveillance_risk_score` may be observed inverted; the never-lower claim holds only per-snapshot — `domain_donor.py:145-152`, `routes_donors.py:296,325`
- §3.1 — insert — ambiguity — after an auto-deferral, `screening_risk_score` is *not* recomputed and excludes the new event's 15 points — `routes_donors.py:149-158`
- §3.1 — revise — ambiguity — serology/approval state gate is `APPLICANT|SCREENING|INFO_REQUESTED|QUALIFIED`; a `TEMPORARILY_DEFERRED` donor is refused — `routes_donors.py:32,190,247`
- §3.2 — insert — ambiguity — `collected_on`/`approved_on` are not constrained against the clock date — `routes_donors.py:183,246`
- §3.2 — revise — mismatch — the deferral enum admits all seven reason codes, including the two system codes, from a director — `routes_donors.py:26-27,337`
- §3.3 — insert — ambiguity — `temporary_deferral_count` is a lifetime tally (never lowered); a deferral write leaves `screening_risk_score` untouched — `domain_donor.py:156-160,211-219`
- §3.3 — insert — ambiguity — `active_deferral_until_date` tie-break: later-recorded event governs on equal `created_at` — `domain_donor.py:163-179`
- §3.3 — insert — ambiguity — recall hop 1 also recomputes `lifetime_accepted_volume_ml` from its definition — `domain_donor.py:248-251`
- §3.3 — insert — ambiguity — hop 2 skips already-`VOIDED` components entirely (no downstream implication); each scrapped pool counts once — `domain_donor.py:259-276`
- §3.3 — insert — ambiguity — hop 4 floors `consumed_cents` at 0 and re-derives programme status — `domain_donor.py:308-313`
- §4 — revise — mismatch — header is `X-User-Role`, not `X-Role` — `auth.py:48`

Verified as already uniquely pinned (no edit): the whole 49-code catalogue and its statuses match `errors.py` exactly (programmatic diff, 49/49); all 13 donor endpoints' roles, status codes, sort keys, filters, field ranges/patterns, risk-score formulas, band thresholds, and the five recall hops.

## Deliberately left to later passes
- `domain_dispense.reopen_prescription` (hop 5): a prescription outside `FILLED|PARTIALLY_FILLED|QUEUED` (e.g. `CANCELLED`) still has its volumes rewritten but keeps its status and is not renumbered — pass 3's module, and §3.3 hop 5's wording depends on it.
- `refresh_program_status`'s exact cap comparison (`consumed >= cap` -> `EXHAUSTED`) — pass 3.
- `domain_bubble.py`'s rule *contents* (`available_ml <= 0`, shipment-then-lot order) — I pinned only the trigger condition in §2.8; the rules themselves belong to shipment/lot modules.
- §3.4's definition of `lifetime_accepted_volume_ml` and all shipment/donation state text — pass 2.

### Pass 2 summary (verbatim)

Pass 2 complete.

**No re-copy performed** — I edited `workspace/PRD_COMPLETED.md` in place with 15 surgical `Edit` calls. All 24 of pass 1's paragraphs still differ from `PRD_FINALIZED.md` (verified by line-level diff), so nothing was reverted.

| | before | after |
|---|---|---|
| lines | 436 | 436 (all edits in-paragraph; no new paragraphs/sections) |
| chars | 112,627 | 117,714 |

**Counts: 12 ambiguity-pins, 4 mismatch-revisions** (16 pins over 15 edits; §2.1 carries two, §3.7¶277 carries two).

Behaviors were verified empirically with Flask's `test_client` (4 probe scripts under `/tmp/task_2821_step9_p2/`); no server was started.

### Changes
- **§2.1 — insert — ambiguity** — `/shipments/{id}` resolves the row *before* the donor-scope check (unknown cooler -> 404, another donor's cooler -> 403), the mirror of the `/donors/{id}` sub-collections; and cooler registration compares the submitted `donor_id` *before* existence resolution — `routes_shipments.py:130-133`, `:67-73`
- **§3.4 ¶219 — insert — ambiguity** — `shipped_on` is never compared with the logical clock; `container_count` and `declared_volume_ml` are declarative and never reconciled against logged containers or measured volume — `routes_shipments.py:75-82, 206-240`
- **§3.4 ¶223 — insert — ambiguity** — `estimated_reimbursement_cents` is written once at dispatch and never recomputed or cleared — `routes_shipments.py:107-108, 156-157`
- **§3.4 ¶225 — insert — ambiguity** — none of the three logger figures carries a declared range (`ERR_FIELD_OUT_OF_RANGE` is never a receipt's answer; a negative `excursion_minutes` enters the penalty formula unclamped, doubling the payout at -50), and receipt is admitted only from `IN_TRANSIT` — `routes_shipments.py:142-147`
- **§3.4 ¶229 — insert — ambiguity** — `QUARANTINED` is the only state admitting a disposition; anything else is `ERR_SHIPMENT_STATE_INVALID` — `routes_shipments.py:179`
- **§3.4 ¶231 — insert — ambiguity** — a donation's `expressed_on` is compared with nothing at log time (not the clock, not `shipped_on`, not the 365-day ceiling) — `routes_shipments.py:206-213`
- **§3.5 ¶241 — revise — mismatch** — "eight business rules" corrected to nine (the paragraph enumerates nine, and §2.10 lists nine plus the token) — `routes_pools.py:142-182`
- **§3.5 ¶251 — insert — ambiguity** — a scrap leaves a `COMPLETED`/`BOTTLED` run of the pool alone with its interval still occupied; bottling is then blocked arithmetically (`total_volume_ml` 0 -> `ERR_BOTTLING_EXCEEDS_POOL_VOLUME`), not by a state gate — `domain_pool.py:102-104`, `routes_runs.py:228-232`
- **§3.6 ¶255 — insert — ambiguity** — a `COMMITTED` pool is not limited to one run, and `scheduled_start_at` is never compared with the logical clock — `routes_runs.py:55-71`
- **§3.6 ¶265 — insert — ambiguity** — `culture_cfu_per_ml` and `culture_organism` carry no range/length bound; a negative CFU reads as a pass and `NONE` is not enforced — `routes_runs.py:189-192`
- **§3.6 ¶267 — insert — ambiguity** — hop 4 recomputes each affected donor's `lifetime_accepted_volume_ml` (with her own `version` increment), and the cascade disturbs neither the pool's three aggregates nor its `bottled_volume_ml` — `domain_run.py:118-124`
- **§3.7 ¶271 — revise — mismatch** — `bottled_volume_ml` sums the lots of **any** run of the pool (not "that pool's run"), so two runs share one headroom figure; and it refreshes only on a bottling, so a later `DISCARDED`/`RECALLED` lot does not restore headroom — `domain_pool.py:79-87`
- **§3.7 ¶273 — revise — mismatch** — dropped the false "every lot code is unique across the bank": the code is never uniqueness-checked and two runs of one pool completing on the same date collide (reproduced: both first lots got `20260801-001-01`) — `domain_run.py:161-167`
- **§3.7 ¶277 — revise — mismatch** — the pool's advance to `PASTEURIZED` is conditional on it still being `COMMITTED` — `domain_run.py:190-191`
- **§3.7 ¶277 — insert — ambiguity** — a second-or-later lot leaves the run's own row unmutated, so its `version`/`updated_at` do not move (verified 7 -> 7) — `domain_run.py:187-189`

### Left for pass 3 (their modules)
- `listing.py:12-26` — an unparseable filter value (e.g. `qualifies=maybe` on my readings list, or a non-integer `int` filter) yields an **empty page** rather than a 422. §2.3 ¶93 is silent on this; the behavior lives entirely in pass 3's `listing.py` and affects every list channel, so I left it deliberately rather than pin it from one endpoint's viewpoint.
- §3.7 ¶279/¶281 (lot release, SoD, the `dispensed_ml`/`available_ml` ledger, the `EXPIRED` sweep) — `routes_lots.py`, `domain_dispense.py`, `domain_sweep.py`. Untouched.
- §2.8's **lot-side** bubble-up rule and `store.py`'s `rearm()` version discipline (§3.10). Untouched. The **shipment-side** bubble-up rule needed no change: §2.8 ¶135 (pass 1) and §3.4 ¶233 already match `domain_bubble.py:14-19` exactly, and `CLOSED` is already in the credited-states definition in ¶227.

### Pass 3 summary (verbatim)

Pass 3 complete. I edited `workspace/PRD_COMPLETED.md` **in place** — no `cp`, no whole-file `Write`, and I did not touch `worklog.md`.

**File size:** 436 lines / 117,714 chars before -> 436 lines / 123,612 chars after (10 paragraphs revised; `diff` vs `PRD_FINALIZED.md` grew from 39 to 45 changed lines, so all prior-pass edits are intact).

**Counts:** 8 ambiguity-pins, 5 mismatch-revisions (13 changes in 10 paragraphs).

- §2.3 ¶93 — insert — ambiguity — an unreadable filter value is not a shape failure: it is applied, matches nothing, 200 + empty `data` + `total_count` 0, in every channel and at any `offset`; page controls are still validated first, so `limit=abc&priority_tier=maybe` still reports the page control's 422. Names the only int filter (`priority_tier`, base-ten, so `3`/`+3`/`03` all match) and the only bool filter (`qualifies`: `true|false|1|0`, any case) — `listing.py:12-26`
- §2.8 ¶135 — revise — ambiguity — lot-side bubble rule threshold changed from "reached 0" to "fallen to 0 or below" / "rises strictly above 0"; added the fixed shipment-then-lot evaluation order, one visit per family, and that the inline `RELEASED`/`EXHAUSTED` moves of §3.9 do not draw a second increment — `domain_bubble.py:22-29`
- §3.3 ¶213 — insert — mismatch — recall hop 5 shares `reopen_prescription`, so an order already `CANCELLED`/`EXPIRED` takes the volume credit and `version` increment but keeps its terminal status, keeps `waitlist_position` null and triggers no renumbering — `domain_dispense.py:187-192`, `domain_donor.py:322`
- §3.7 ¶273 — insert — ambiguity — a new lot exposes `released_at`/`released_by_user_id` as null — `serializers.py:238-239`, `domain_run.py:183`
- §3.7 ¶279 — insert — ambiguity — release admits only `HOLD`; any other `release_status`, including `RELEASED`, is `ERR_LOT_STATE_INVALID` (409); no self-loop — `routes_lots.py:72-74`
- §3.8 ¶285 — revise — mismatch — `coverage_pct` "two decimal places" is a convention, not a rule: only the 0.00-1.00 range is enforced, extra decimals are stored/echoed unchanged and multiplied in unrounded (verified: 0.375 -> 201) — `routes_rx.py:63`, `validate.py:53-56`
- §3.8 ¶287 — insert — ambiguity — a named `subsidy_program_id` need only exist; an `EXHAUSTED` program may be named and only bites at fill time — `routes_rx.py:94-95`
- §3.8 ¶287 — insert — ambiguity — `needed_by_date` need not be in the future; a past-dated order is accepted `QUEUED`, cannot be filled, and the next accepted clock write expires it (verified) — `routes_rx.py:106`
- §3.9 ¶307 — revise — mismatch — the void's `EXHAUSTED -> RELEASED` return carries the §2.8 expiry proviso; an out-of-date lot stays `EXHAUSTED` — `domain_dispense.py:160-163`
- §3.9 ¶307 — insert — mismatch — status recomputation on void is confined to `FILLED|PARTIALLY_FILLED|QUEUED`; a `CANCELLED`/`EXPIRED` order still has both volume fields rewritten and `version` bumped but keeps its status, keeps `waitlist_position` null, renumbers nothing (verified: cum 0, remaining = prescribed, still `CANCELLED`, v3->v4) — `domain_dispense.py:177-192`
- §3.10 ¶319 — insert — mismatch — "exactly as a manual fill would" covers pricing and the three ledger writes only, not the §3.9 gauntlet: the cycle never checks the OCC token, segregation of duties, the two fiscal gates, or the 20 ml manual floor (verified: cycle filled an order the acting operator prescribed, filled a `subsidy_required` order against a 1-cent-headroom program clipping the subsidy to 1, and drew 10 ml where a manual fill was refused 422) — `domain_dispense.py:244-256`
- §3.10 ¶319 — insert — ambiguity — `allocation_cycle_sequence` counter starts at 1 and advances by one per accepted cycle even when the cycle fills nothing (verified) — `domain_dispense.py:214`
- §3.10 ¶321 — insert — ambiguity — the sweep runs on every accepted clock write including one restating the current instant, visits the four families in the order listed, and no other endpoint sweeps (verified: a no-op clock write expired a past-dated order) — `routes_rx.py:291-295`, `domain_sweep.py:9-51`

**The six deferred items:**
1. `reopen_prescription` terminal-order carve-out — pinned in **two** places (§3.9 ¶307 for void, §3.3 ¶213 for recall hop 5), empirically confirmed.
2. `refresh_program_status` cap comparison — **no edit**: §3.8 ¶285 already reads "`OPEN` while `consumed_cents` is strictly below `annual_cap_cents` and `EXHAUSTED` once it reaches or passes it", which is exactly `consumed >= cap`.
3. Lot-side bubble rule — revised §2.8 ¶135 to `<= 0` / strictly `> 0` and stated the shipment-then-lot order.
4. Unparseable filter -> empty page — pinned globally in §2.3 ¶93; I grepped every `apply_filters` call site to confirm `priority_tier` is the only `int` filter and `qualifies` the only `bool` one bank-wide, and added the page-control precedence caveat so the claim can't be over-read.
5. §3.7 ¶279/¶281 — ¶281's ledger definition and `EXPIRED`-from-`HOLD`-only sweep already matched impl, so ¶279 needed only the state-gate pin (plus the ¶273 release-stamp nulls); segregation of duties was already exact in §2.9/§2.10.
6. §3.10 / `rearm()` version discipline — **no edit to the version prose**: I read Step 8's inserted paragraphs in §3.10 and §3.8 and verified them against `store.touch/rearm` and `apply_fill` (per-draw increment on lot + prescription, program only when `consumed_cents` moves, end-of-cycle renumber free for already-filled orders). My ¶319 insert sits ahead of that prose and neither duplicates nor contradicts it.

### Orchestrator post-step verification
- `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (the tell-tale sign of a scan that never ran): 123,612 vs 104,671 bytes, 90 diff lines = 45 revised paragraphs (24 from pass 1 + 15 from pass 2 + a further 6 lines newly touched by pass 3, which also re-edited 4 paragraphs an earlier pass had touched). Aggregate: 39 ambiguity-pins, 14 mismatch-revisions, 53 pins over 45 paragraphs.
- Structure preserved: still 436 lines and 29 headings, §1-§5 all present at lines 3/11/163/323/382, and the file still ends on the complete final error-catalogue row `| \`ERR_SUBSIDY_CAP_EXCEEDED\` | 402 |` — no truncation and no new sections.
- `grep -in "harder than expert|SCAFFOLD"` over `PRD_COMPLETED.md` returns nothing — no difficulty-directive or scaffold leakage survived into the final contract.
- `find workspace/implementation -name "*.py" -newer workspace/PRD_FINALIZED.md` is empty: Steps 8 and 9 touched only PRD files, so the Step 7 result stands unchanged — the 8-round sweep at 102/102 in every round remains valid for the shipped implementation. The 8 `results.{1..8}.json` files are retained in `workspace/implementation/`.

## Pipeline complete — 2026-09-05T08:15:00.000Z

All nine steps finished. Final artifacts: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `worklog.md`, `test_helpers/` (9 files), `test_suite/` (conftest + 7 modules, 102 tests), `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}`.
