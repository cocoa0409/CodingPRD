# Worklog — task_2941_fresh_cut_produce_processing

## Step 1: Create task directory — 2026-09-05T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2941_fresh_cut_produce_processing` and `.../workspace` (index pre-assigned by the orchestrating prompt; no index scan performed).

## Step 2: Generate Scaffold — 2026-09-05T20:53:00.000Z

Scaffold generation for task 2941 is complete. All three artifacts are in `/home/ubuntu/github/CodingPRD/tasks/task_2941_fresh_cut_produce_processing/`, generated purely from the scenario text plus the scaffold-generator skill spec (no sibling task was read).

Lint verdict (verbatim, final run):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2941_fresh_cut_produce_processing/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2941_fresh_cut_produce_processing/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2941_fresh_cut_produce_processing/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    53
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     58
  Calls scanned (§1.8+§1.9):  637

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Output files (line count / bytes):
- `SCAFFOLD.yaml` — 3307 lines / 167,112 bytes (§1.0–§1.7: 14 entities, 50 business + 3 support endpoints, 8 state machines, 9 calculations, 65 ordered validations, 59 errors, 7 roles; no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1313 lines / 93,881 bytes (single top-level key; 9 difficulty rules × 2 instances = 18)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 2877 lines / 202,192 bytes (single top-level key; 80 instances across all 9 allowed sections — 58 with full `test_recipe`, 22 `excluded_because` stubs)

Verification performed beyond the lint:
- Both design files parse as YAML with exactly one top-level key; all 80 corner names are unique and none collide with the 18 difficulty names; every `excluded_because.difficulty_instance` resolves to a real §1.8 instance; every instance has exactly one of `test_recipe` / `excluded_because`; all `section:` values are from the allowed set.
- Forbidden concurrency vocabulary ("simultaneously", "in parallel", "race…", etc.) is absent from all three files, and the "harder than expert level" directive appears nowhere — the `scenario:` key holds only the domain sentence, and difficulty is expressed as design depth (`difficulty_level: expert_plus`, dual state dimensions, six-hop recall cascade, dual-variant shelf life and risk scoring, OCC on two parents, three segregation-of-duties controls).
- Every error id in the 59-entry catalog is now triggered by some §1.8 or §1.9 instance (the last five gaps — `ERR_UNAUTHORIZED`, `ERR_STALE_PRODUCT_VERSION`, `ERR_HOLD_NOT_RELEASED`, `ERR_CHANGEOVER_BUFFER_REQUIRED`, `ERR_YIELD_OUT_OF_TOLERANCE` — were closed by the errors, rbac and cross-cutting sections).
- One arithmetic defect found and fixed while finishing: the ship-boundary instance had been written against a 2026-08-14 final code date; the BASE chain closes on 2026-08-03 with `final_shelf_life_days` 13, so the correct final code date is 2026-08-16 and the boundary ships are 2026-08-06 (exactly 10 remaining days, passes) versus 2026-08-07 (9 days, `ERR_INSUFFICIENT_REMAINING_SHELF_LIFE`).
- Scratch space `.scratch/step2/` was removed; `.scratch/` itself, `worklog.md` and `workspace/` were left untouched.

Orchestrator verification: all three files present; leak-grep for "harder than expert"/"expert level" over all three scaffold files returned no hits; `scenario:` key contains only the domain sentence.

## Step 3: Copy Shared Files — 2026-09-05T20:53:05.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2941_fresh_cut_produce_processing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T21:09:14.000Z

PRD complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2941_fresh_cut_produce_processing/workspace/PRD.md` — **463 lines, 100,904 bytes**, built in 12 incrementally verified heredoc appends (no single giant Write).

**Structure** (all `##`/`###` headings, in order):
- §1 Introduction
- §2 Global Specifications — 2.1 RBAC (7 roles, opaque identities, `override_justification`), 2.2 API Response Structure (verbatim block from the skill), 2.3 Pagination, 2.4 Plant Logical Clock, 2.5 Record Identity & Audit Fields, 2.6 Precision/Rounding/Money, 2.7 Stale-Version Protection (both OCC rules), 2.8 Validation Order (8 tiers), 2.9 Segregation of Duties, 2.10 Line Posture (derived compound state), 2.11 Cascade Discipline & Counter Conservation
- §3 Business Logic — 3.1 Master Data, 3.2 Grower Lots & Risk, 3.3 Receiving, 3.4 Wash-Water Chemistry, 3.5 Sanitation/Environmental/CAPA, 3.6 Planning & Starting a Run, 3.7 Lot Consumption & Pound Balance, 3.8 Closing a Run (yield, shelf life, code dates, cost waterfall), 3.9 Hold-and-Release, Shipping, Recall
- §4 API Endpoints — status-code rules + 53-row table (Method / Path / Description / Authorized Roles)
- §5 Error Codes — 59-row table (Error Code / HTTP Status)

**Hard Contract results** (verified programmatically, two full passes):
- **Contract 1 — Field-Name Coverage: PASS.** 157/157 entity field names present; 89/89 endpoint input names present; all non-entity endpoint output field names (e.g. the traceability projection's `rework_ancestor_run_ids`, `active_consumption_count`, `effective_code_date`) present.
- **Contract 2 — Rule Coverage: PASS.** All 59 error IDs appear in §2/§3 prose, not merely in the §5 table. All 51 transitions across the 11 state machines have their `from`/`to` states co-located in a single paragraph. All 9 calculations' constants appear as literal values (only unmatched numeral was `38`, which is a scaffold-internal priority cross-reference, not a domain figure). Both concurrency rules covered in §2.7. Zero entity enum values missing. Every named scaffold constant is rendered as its prose value (`REWORK_MAX_DEPTH`→"five hops", `MAX_TEST_ROUNDS`→"strictly below 3", `ANTIMICROBIAL_READING_MAX_AGE_MINUTES`→"60 minutes, inclusive", `ENV_CLOSED_RUN_LOOKBACK_HOURS`→"24 hours", `RISK_SUSPEND_THRESHOLD`→"50", `APC_ELEVATED_CFU_G`→"1,000,000", `CHANGEOUT_LOAD_INDEX_MAX`→"3.000").
- **Contract 3 — §3 Path Purity: PASS.** 961 backticked tokens in §3, zero HTTP methods and zero URL paths; a raw-text scan of §3 for `POST|GET|PUT|PATCH|DELETE|endpoint|/x/{` also returns nothing.

**Other checks:** no pseudocode (only the 2 JSON fences of the mandated §2.2 block); zero hits for fuzzy language (`approximately`, `roughly`, `etc.`, `as needed`, `reasonable`, `TBD`); zero hits for `expert`, `difficulty`, `scaffold`, `test_recipe`, or any `§1.x` scaffold cross-reference — no difficulty metadata leaked.

**Constraints honoured:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced. Only `workspace/PRD.md` was written. `worklog.md` untouched. Scratch confined to `.scratch/step4/` and only that subdirectory removed. No `pkill` run.

The file ends at a real boundary: the final row of the §5 error table (`ERR_WASH_SYSTEM_CAPACITY_EXCEEDED | 409`), with no audit footer.

Orchestrator verification (truncation guard): `wc -l` = 463; heading scan shows §1–§5 all present and ordered; `tail -12` shows a complete §5 error-code table row, not a mid-sentence cut. PRD accepted without regeneration.

## Step 6: Generate Implementation — 2026-09-05T21:49:11.000Z

The implementation is complete.

## What was built

`/home/ubuntu/github/CodingPRD/tasks/task_2941_fresh_cut_produce_processing/workspace/implementation/` — Python 3 + Flask, in-memory dicts only, store empty on every boot (no seeding anywhere), all modules written in chunked `cat >>` appends with `ast.parse` verification per file.

### Per-file line counts (3,677 total)
| file | lines | file | lines |
|---|---|---|---|
| `start.sh` | 10 | `routes/clock.py` | 19 |
| `requirements.txt` | 1 | `routes/wash.py` | 132 |
| `app.py` | 70 | `routes/products.py` | 160 |
| `util.py` | 169 | `routes/holds.py` | 200 |
| `db.py` | 122 | `routes/growerlots.py` | 259 |
| `errors.py` | 88 | `routes/lines.py` | 402 |
| `envelope.py` | 292 | `routes/runs.py` | 656 |
| `serializers.py` | 261 | `services/cost.py` | 44 |
| `enums.py` | 53 | `services/shelflife.py` | 73 |
| `routes/__init__.py` | 0 | `services/posture.py` | 92 |
| `services/__init__.py` | 0 | `services/holds.py` | 104 |
| | | `services/lots.py` | 121 |
| | | `services/chemistry.py` | 155 |
| | | `services/cascades.py` | 194 |

### Endpoint coverage
Programmatically diffed the Flask URL map against the PRD §4 table: **53 PRD endpoints, 53 implemented, 0 missing, 0 extra** (the §4 table has 53 rows, not 50). All 54 PRD §5 error codes are in `errors.py` with their exact HTTP statuses, plus `ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED`/`ERR_INTERNAL` for framework-level failures.

### Smoke test result — passed
Launched `PORT=18847 bash start.sh`, exercised two scripted scenarios (57 requests), then killed exactly the two captured PIDs (1887828 launcher, 1887830 `python3 app.py`); port confirmed closed. No `pkill`, no name-pattern kills.

Scenario 1 (happy path, all endpoints groups): clock set → product/spec/line/wash-system → grower lot approve → receipt + disposition → sanitation start/submit/validate (line went `RESTRICTED → OPEN`) → reading → run plan/start/consume/close → cases → ship → traceability → hold submit/result/release → swab `PRESUMPTIVE → CONFIRMED_POSITIVE` (line `FROZEN`, CAPA opened) → CAPA start/submit/verify → recall → 401/403/400/404 paths. Hand-verified numbers: yield `66.67`, cost components `148 + 0 + 41760 + 25 = 41933` cents → per-case `698`, remainder `53`; provisional shelf life `12` days → `2026-08-22`; counters `59/0/1/0` after release.

Scenario 2 (error and cascade paths): `ERR_DUPLICATE_CODE`, `ERR_STALE_PRODUCT_VERSION` 412, preharvest score `30 → SUSPENDED`, `OUT_OF_SPEC` grade with 2-day deduction, `ERR_OVERRIDE_NOT_PERMITTED` 403 (refused before the payload is examined), `ERR_RECEIPT_TEMP_OUT_OF_SPEC` ahead of `ERR_TRIM_LOSS_EXCEEDS_NET`, `ERR_RECEIPT_NOT_PENDING`, trailing score `90`, `ERR_DISASSEMBLY_INCOMPLETE`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_LINE_INTERVAL_CONFLICT`, `ERR_LINE_NOT_OPEN`, the full sanitation-failure cascade (`failed_reason=ATP_ABOVE_LIMIT` → line `RESTRICTED` → wash `DUMP_REQUIRED` → SETUP run `CANCELLED`), change-out reset, pagination bound rejection, and `ERR_HOLD_INVALID_STATE` on a cancelled run.

### Judgement calls worth flagging
- **`SanitationEvent.started_at`/`completed_at`** are stamped internally (PRD prose requires them) but not serialized, because the scaffold's entity field list omits them — I kept the response shape to the declared fields.
- **`_clock/set_current_utc`** echoes `current_utc` verbatim rather than re-canonicalising it, consistent with client-supplied instants being "taken as given".
- **Traceability lot/receipt ids** are drawn from `ACTIVE` consumptions only ("a voided row is invisible to every aggregate in this document"); voided rows still contribute to `voided_consumption_count`.
- **Hold-open preconditions** (`disposition != REJECTED`, `run_status != CANCELLED`) have no declared error id in the scaffold; they return `ERR_HOLD_INVALID_STATE` 409.
- **Auto-holds at close** touch the run again after the close's own `version` bump, so a `hold_and_release_required` close leaves the run two versions ahead rather than one — this follows §2.11's per-row cascade discipline.

## Step 5: Generate Unit Tests — 2026-09-05T22:59:13.000Z

Generation is complete. Final state of `/home/ubuntu/github/CodingPRD/tasks/task_2941_fresh_cut_produce_processing/`.

## What was emitted

**95 test functions**, one `Design:` tag each (verified: zero tests with 0 or 2+ tags), collected cleanly by pytest in 0.62 s (`95 tests collected`), `python3 -m compileall` OK, `python3 -m pyflakes test_suite/*.py test_helpers/*.py` silent.

`test_suite/` (line counts): conftest.py 17, test_01_dual_variant_calculations 231 (5 tests), test_02_combinatorial_formulas 225 (4), test_03_non_linear_state_machines 207 (4), test_04_transitive_cascades 358 (4), test_05_validation_priority_conflicts 173 (4), test_06_boundary_precision 201 (4), test_07_cross_entity_state_dependencies 190 (4), test_08_resource_temporal_overlap 252 (4), test_09_compensating_invariants 212 (4), test_10_entities 462 (11), test_11_state_machines 755 (13), test_12_calculations 681 (7), test_13_validations 477 (7), test_14_validations 507 (7), test_15_endpoints 439 (5), test_16_errors_and_rbac 370 (5), test_17_cross_cutting 288 (3).

`test_helpers/` (unchanged this session apart from one unused-import fix in assertions.py): __init__ 166, api_client 333, api_errors 168, assertions 458, constants 396, factories 385, fixtures 700, test_users 158, types 276.

Last file written this session: `test_suite/test_17_cross_cutting.py` — the two `cross_cutting_complexity_layers` instances (spec-create stale product version; consumption + void stale run version) and the one `consistency_model` instance (every effect visible in the response that caused it).

## Instance coverage (machine-verified against both yamls)

- §1.8 difficulty: **18 of 18 translated, 0 skipped**, every instance carrying ≥2 tests (37 tests).
- §1.9 corner: **58 of 58 live instances translated, 0 skipped**, ≥1 test each (58 tests).
- The 22 corner instances carrying `excluded_because` were deliberately **not** emitted (the yaml itself defers each to a difficulty instance): state_machines 3, calculations 6, validations 6, endpoints 3, errors 1, cross_cutting 3.
- No tag points at a stub, a non-existent instance, or the wrong section.

## Audit passes

1. **PRD citation pass**: every `PRD:` line in all 17 files checked as a verbatim substring of `workspace/PRD.md`. Found and fixed 4 non-verbatim citations: two `Stale-version checks. The two checks of §2.7…` lines (the PRD wraps the lead-in in `**bold**`; trimmed to the sentence proper) in test_10 and test_11; one paraphrased `net_weight_lb` sentence in test_10 (replaced with the real "The server derives `net_weight_lb` as the gross weight less the tare weight…"); and one hybrid sanitation sentence in test_16 (the "starting requires SCHEDULED or FAILED…" enumeration belongs to `ERR_CORRECTIVE_ACTION_INVALID_STATE`, so it was replaced with "An event in any other state is refused with `ERR_SANITATION_INVALID_STATE` (HTTP 409)."). Re-run: **0 failures**.
2. **Design tag pass**: 95 tags, all resolving to live instances in the right section; 0 malformed.

## Hygiene

`ls -la` on the task root shows only SCAFFOLD*.yaml, worklog.md, workspace/, test_helpers/, test_suite/, .scratch/. `ls -la workspace/` shows INSTRUCTION.md, PRD.md, implementation/, sweep.sh — **no stray test dirs under workspace/**. `workspace/implementation/` was never read or referenced; no `pkill` was run. PRD.md, worklog.md and all three SCAFFOLD files are untouched. `.scratch/step5/` (my only scratch) was removed; the sibling `.scratch/step6/` is intact. `__pycache__`/`.pytest_cache` cleaned.

## Design-vs-PRD divergences (side-claims deliberately not asserted)

Live instances were all translated, but a few individual design claims are not PRD-derivable and were omitted rather than weakened:
- `grower_lot_recall_cascades_to_cases_and_rework_runs`: design's G2 `trailing_risk_score == 100` / `env_positive_run_count == 0` contradicts §3.2 (which counts recall holds too); the score claim is asserted neither way.
- `line_run_interval_pairwise_exclusion_with_allergen_buffer`: design asserts `allergen_changeover_required == true` where the PRD derives false; the test asserts only the four derivable planning outcomes.
- test_12 ceiling instance: `topup_ppm_required`/`below_target` claims omitted when the tier target is null; excursion instance asserts the hold-reason set and `sorted(cases_held_count)` instead of a non-derivable `opened_at` order.
- `corner_override_permission_is_checked_before_the_payload`: the `override_justification` echo is not a declared RawReceipt field, so that echo is not asserted.
- `corner_spec_must_belong_to_the_product_and_still_be_active`: the design's "foreign" spec is ACTIVE, so the test uses a second product with two revisions and indexes by id.
- `corner_traceability_read_recomputes_the_whole_chain`: the view is compared against the run's current code-date state rather than the design's literal dates.
- `corner_every_role_is_refused_the_other_roles_exclusive_writes`: design's `version == 2` on the grower lot is not derivable; the test pins the version captured before the refusals and asserts it unchanged.
- `corner_corrective_action_verifier_cannot_be_the_implementer`: design writes `PENDING_VERIFICATION`; the PRD spelling `VERIFICATION_PENDING` was used (design typo).
- `corner_every_effect_is_visible_in_the_response_that_caused_it`: the instance's prose mentions ship counters but its recipe does not ship (the run's cases are ON_HOLD at close), so the test covers the close response plus the two immediate reads; ship-counter immediacy is already covered in test_16.

Orchestrator verification: `test_helpers/` and `test_suite/` both exist at the TASK ROOT; `workspace/test_helpers` and `workspace/test_suite` do not exist. 95 `def test_` definitions and 95 `Design:` tags counted independently. `.scratch/` still contains `step6/`.

## Step 7: Run Tests and Iterate — 2026-09-05T23:20:35.000Z

Sweep is clean: 8/8 rounds at 95/95 passed, 0 failed, 0 errors, 0 skipped.

## Summary

**Iterations run:** 2

**Iteration 1** — 8/8 rounds at 94/95. A single deterministic failure, identical in every round: `test_a_failed_verification_reopens_the_action_and_clears_the_narrative` (test_11_state_machines.py), asserting `failed_reason == "MANUAL_FAIL"` but receiving `"ATP_ABOVE_LIMIT"`.

Diagnosis walked the protocol:
- **STEP 1a (coverage):** PRD §3.5 covers the rule verbatim — "The server writes `failed_reason` by examining three candidate reasons in exactly this order and taking the first that applies: `ATP_ABOVE_LIMIT` when the ATP reading exceeds the line limit, then `ALLERGEN_POSITIVE` when the allergen swab came back positive, then `MANUAL_FAIL`."
- **STEP 1b (unique derivability):** Holds. The ordered first-match rule leaves no reader latitude — ATP above the line limit deterministically yields `ATP_ABOVE_LIMIT`, and compliant measurements with an explicit `FAIL` verdict deterministically yield `MANUAL_FAIL`.
- **STEP 2 (test-vs-PRD consistency):** **Test bug.** The test's setup contradicted its own assertion. It called `fx.failed_sanitation(api, world.line_id, atp_rlu=FAILING_ATP_RLU)` with `FAILING_ATP_RLU = 250` against a line whose `max_atp_rlu` is 200 — so the ATP candidate legitimately applied first and pre-empted `MANUAL_FAIL`. The assertion message ("an explicit FAIL is recorded as MANUAL_FAIL") shows the intent was compliant measurements plus a manual `FAIL` verdict. The implementation at `workspace/implementation/routes/lines.py` (validate handler, lines 233-248) evaluates the three candidates in exactly the PRD's order and was already correct — no STEP 3 fix was warranted.

**Tests deleted:** none. Both PRD sub-checks passed, so no test met the deletion criterion.

**Fixes applied to `test_suite/`:**
- `test_suite/test_11_state_machines.py` — `test_a_failed_verification_reopens_the_action_and_clears_the_narrative`: dropped the `atp_rlu=FAILING_ATP_RLU` override so the clean submits the default compliant ATP of 120 (under the line's limit of 200) with a `NEGATIVE` allergen swab, making the explicit `FAIL` verdict the only applicable reason. This makes the test *more* faithful to the cited PRD sentence — it now actually exercises the third candidate in the ordered list rather than the first. The rest of the test (corrective-action `OPEN`, `reopen_count`, posture `RESTRICTED`) is independent of `failed_reason`, since a failed clean opens a `MAJOR` action regardless of cause.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none — the sole failure was a test-artifact bug, and no PRD-required check was weakened or removed.

Notable: the failure was fully deterministic across all 8 rounds rather than flaky, and the sweep surfaced no load-induced or timing-sensitive failures in either iteration.

Orchestrator verification: read all 8 `results.$i.json` independently — every round reports total=95, passed=95, failed=0, errors=0, skipped=0, all written at the same sweep timestamp. Step 8 is NOT skipped (Step 7 ran 2 iterations with 1 `test_suite/` fix), though the diff contains 0 `implementation/` fixes and 0 deletions.

## Step 8: Finalize PRD — 2026-09-05T23:22:08.000Z

Done. `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md` — the honest conclusion for this diff.

## Line counts
- `PRD.md`: 463 lines; `PRD_FINALIZED.md`: 463 lines; **0% delta** (identical md5 `9438d401...`).

## Changes
None. No PRD silence or PRD/impl mismatch is revealed by `<step_7_diff>`.

## Verification of the single diff item (`test_11_state_machines.py` fixture-value fix)

Subject: how the server chooses `failed_reason` when a sanitation validation fails.

Impl paths enumerated and read:
- `workspace/implementation/routes/lines.py:217-251` — the `validate_sanitation` handler. It computes `atp_over = atp_rlu is not None and atp_rlu > line["max_atp_rlu"]` and `allergen_positive = allergen_swab_result != CHANGEOVER_SWAB_RESULT`, takes the `VALIDATED` branch only for `outcome == "PASS" and not atp_over and not allergen_positive`, and otherwise assigns `failed_reason` in the order `ATP_ABOVE_LIMIT` → `ALLERGEN_POSITIVE` → `MANUAL_FAIL`.
- `routes/lines.py:22` — `CHANGEOVER_SWAB_RESULT = "NEGATIVE"`; `enums.py:45` — `ALLERGEN_SWAB_RESULT = ("NEGATIVE", "POSITIVE")` and the submit schema marks the field required (`routes/lines.py:39`), so `!= "NEGATIVE"` is exactly "POSITIVE" — matching the PRD's wording rather than diverging from it.
- `enums.py:46,53` — `FAILED_REASON` and `OUTCOME` tuples match the PRD's literals exactly.
- Every other write/clear of the field: `routes/lines.py:133` (creation, null), `:183` (re-entry `FAILED → IN_PROGRESS` clears it), `:209` (submit records measurements) — all consistent with PRD lines 227/229.
- Parallel consumer of the same measurements: `routes/runs.py:303` requires `allergen_swab_result == "NEGATIVE"` on the newest `VALIDATED` event for allergen changeover, consistent with PRD line 270.

Wording adjustment: none needed. PRD line 233 already states the ordered first-match rule verbatim and also already pins the PASS-cannot-override-measurements branch that the impl implements. The Step 7 failure was purely a fixture bug (the test seeded `atp_rlu=250` against a line with `max_atp_rlu=200` while asserting `MANUAL_FAIL`), so there is nothing under-determined to pin. The diff contains zero `implementation/` fixes, zero test deletions, and zero `test_helpers/` changes, so no other candidate sites existed.

Orchestrator note: a byte-identical `PRD_FINALIZED.md` is the correct Step 8 outcome when Step 7 applied no `implementation/` fixes and made no deletions (md5 confirmed identical to `PRD.md` by the orchestrator). The full independent PRD-vs-impl scan is Step 9's job, and Step 9 must NOT come back identical.

## Step 9: Complete PRD — 2026-09-05T23:52:28.000Z

Orchestrator decision: Step 9 was executed as **three sequential module-partitioned passes** over one shared `PRD_COMPLETED.md`, rather than one subagent. Rationale: a single pass over a 3,676-line implementation exhausts its output budget and silently drops coverage (the failure mode is a `PRD_COMPLETED.md` that is byte-identical to its source). Pass 1 owned the `cp`; passes 2 and 3 were explicitly forbidden from copying and edited in place.

Partition: pass 1 = app/start.sh/db/util/errors/enums/envelope/serializers + routes/clock, products, growerlots. Pass 2 = routes/lines, routes/wash, services/chemistry, posture, cascades (except `recall()`). Pass 3 = routes/runs, routes/holds, services/cost, shelflife, holds, lots, and `cascades.recall()`.

### Pass 1 (infra + master data + receiving) — 19 edits: 15 ambiguity-pins, 4 mismatch-revisions
463 lines / 100,904 chars → 465 lines / 109,810 chars (+8,906).
- §2.1 — insert — ambiguity — emptiness test is against the exact empty string, so a whitespace-only `X-User-ID`/`X-User-Role` authenticates rather than 401 — `envelope.py:94`
- §2.1 — insert — ambiguity — the override refusal is preceded only by JSON parsing; an explicit `null` justification never triggers it — `routes/growerlots.py:217`, `envelope.py:134-146`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 random alphanumerics — `envelope.py:32-33`
- §2.2 — insert — ambiguity — pagination `meta` omitted from object responses; `has_more` = `offset + len(page) < total_count` — `envelope.py:57-65`
- §2.3 — insert — ambiguity — bad/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` 400, empty-string param = absent; `created_at` ties broken by global write sequence — `envelope.py:238-254`, `db.py:78,92`
- §2.3 — insert — ambiguity — unrecognised filter value → 400; `below_target` accepts only 4 literals; free-text filters exact/case-sensitive; filters validated before the path parent, pagination after it — `envelope.py:257-281`
- §2.4 — revise — mismatch — the clock does not police monotonicity; an earlier `current_utc` is accepted; endpoint returns 200 echoing the supplied text — `util.py:79-80`, `routes/clock.py:13-19`
- §2.4 — insert — ambiguity — client-supplied instants echoed verbatim, never re-rendered to canonical 3-fraction-digit form — `db.py:56-63`, `util.py:23-31`
- §2.6 — insert — ambiguity — no input quantisation; conventions govern comparison/derived values only; trailing zeros dropped in rendering — `envelope.py:36-39,153-162`
- §2.7 — insert — ambiguity — `expected_product_version` is a required non-negative integer, so omission/null/non-integer is 400, not 412 — `routes/products.py:42,107`
- §2.8 — insert — ambiguity — empty body = `{}`; `null` = absent; strings non-blank but untrimmed; `5.0` accepted for int fields; booleans strict; instants 1–9 frac digits, optional `Z`, zero-offset only — `envelope.py:134-230`, `util.py:15-58`
- §2.11 — insert — ambiguity — grower-lot recomputation does not touch the row when nothing changed — `services/lots.py:104-105`
- §3.1 — insert — ambiguity — duplicate-`code` match is exact and case-sensitive, after request-shape validation — `routes/products.py:59-62`
- §3.2 — revise — mismatch — the `SUSPENDED` adjudication branch also refreshes both counters; `POSITIVE` is the only branch that does not — `routes/growerlots.py:124-136`
- §3.2 — revise — mismatch — "trailing score only ever falls / counters monotonic" is wrong: both counters are re-derived from scratch, so rejecting a `PENDING_INSPECTION` out-of-spec load (or voiding a consumption) lets the score rise; only the suspension is irreversible — `services/lots.py:21-28,74-106`
- §3.3 — insert — ambiguity — `pulp_temp_c` unconstrained in sign/range; tare-vs-gross reported as 400 before `grower_lot_id` is resolved — `routes/growerlots.py:50-52,158-163`
- §3.3 — revise — mismatch — blank/empty `override_justification` fails `ERR_INVALID_REQUEST` 400, not `ERR_RECEIPT_TEMP_OUT_OF_SPEC`; absent/null trim defaults to 0; negative trim reports `ERR_TRIM_LOSS_EXCEEDS_NET` — `envelope.py:167-171`, `routes/growerlots.py:229-244`
- §3.3 — insert — ambiguity — rejection leaves `trim_loss_lb` null and skips both acceptance gates; `override_justification` persists on either branch — `routes/growerlots.py:250-258`
- §5 — insert — ambiguity — transport-level `ERR_NOT_FOUND` 404 / `ERR_METHOD_NOT_ALLOWED` 405 / `ERR_INTERNAL` 500 in the same envelope, bypassing auth; trailing slash tolerated — `app.py:20,30-55`

### Pass 2 (lines, sanitation, environmental/CAPA, wash chemistry, posture, cascades) — 15 edits: 7 ambiguity-pins, 8 mismatch-revisions
465 lines / 109,810 chars → 465 lines / 119,562 chars (+9,752, all in-paragraph).
- §2.10 ¶1 — revise — mismatch — posture is a **stored** field recomputed at exactly four points, not on every child change; scheduling a later-dated event leaves `posture` `OPEN` so run starts still pass — `services/posture.py:71`, `routes/runs.py:275`
- §2.10 ¶4 — revise — mismatch — `open_corrective_action_count` and `last_validated_sanitation_at` are re-derived from scratch on every recomputation regardless of posture movement; newest-validated key is `validated_at` then greater `sequence_no`; containment fires whenever recomputation lands on `FROZEN`, including `FROZEN → FROZEN`; line row touched only on an actual change — `services/posture.py:71-92`, `services/cascades.py:78-80`
- §2.11 ¶1 — revise — mismatch — sanitation-failure cascade is four hops, not five — `services/cascades.py:105-125`
- §3.1 line ¶ — revise — mismatch — `required_disassembly_component_count` and `max_atp_rlu` are zero or greater, not "at least 1"; duplicate `line_code` exact/case-sensitive after shape validation — `routes/lines.py:26-27,67-69`
- §3.1 wash-system ¶ — insert — ambiguity — duplicate `system_code` terms; `status` has only `IN_SERVICE`/`DUMP_REQUIRED` and no direct setter — `routes/wash.py:35-39`
- §3.4 reading ¶ — insert — ambiguity — all five reading fields required, `orp_mv` unconstrained in sign; no state precondition (a reading may be taken on a `DUMP_REQUIRED` system); list order `reading_at` desc then greater `sequence_no` — `routes/wash.py:22-28,67-71,123`
- §3.4 trigger ¶ — insert — ambiguity — reading and change-out always bump the system's `version`/`updated_at`; consumption/void/close bump only on an actual change — `routes/wash.py:99,131` vs `services/chemistry.py:121-134`
- §3.4 step two — insert — ambiguity — index numerator is the rounded two-decimal `weighted_load_lb`; `IN_SERVICE → DUMP_REQUIRED` is one-way — a void dropping the index below 3.000 re-derives a tier target while `status` stays `DUMP_REQUIRED` — `services/chemistry.py:95,129-143`
- §3.4 step three — insert — ambiguity — a latest reading with `free_chlorine_ppm` exactly 0 yields the base 90 seconds, not a division by zero — `services/chemistry.py:102-107`
- §3.4 step four — insert/revise — ambiguity — frozen figures use that reading's own `free_chlorine_ppm`; a null tier target freezes `topup_ppm_required` null and `below_target` false — `routes/wash.py:101-109`
- §3.4 change-out ¶ — revise — mismatch — no state precondition; `reading_sequence_high_water` is not reset; window lower bound inclusive, so a consumption whose `created_at` equals the new `last_changeout_at` is still in the window — `services/chemistry.py:48-63,146-155`
- §3.5 clean-loop ¶ — insert — ambiguity — `started_at`/`completed_at` are internal and appear in no sanitation-event response — `serializers.py:195-211`
- §3.5 scheduling ¶ — insert — ambiguity — `sequence_no` derivation, seven null-on-create fields, `scheduled_for` may be past or future, list order `scheduled_for` desc then greater `sequence_no` — `routes/lines.py:120-157`
- §3.5 submit ¶ — insert — ambiguity — all three measurements required, `disassembled_component_count` and `atp_rlu` integers ≥ 0 — `routes/lines.py:36-40`
- §3.5 sanitation-failure cascade — revise — mismatch — hops unconditional on resulting posture; only currently-`IN_SERVICE` systems flip, but the plant-wide `SETUP → CANCELLED` hop keys off the whole visited set; cancel order `planned_start_at` asc; no `RUNNING` run cancelled/held, no lot rescored — `services/cascades.py:105-125`
- §3.5 env-confirmation cascade — revise — mismatch — `env_positive_run_count` is recounted, not incremented; rescoring deferred until every hold of the sweep exists; unchanged lot is not a touched row; a `MAJOR` confirmation on an already-`FROZEN` line does fire containment — `services/cascades.py:49-97`
- §3.5 corrective-action ¶ — revise — mismatch/ambiguity — submitter need not be `implemented_by_user_id`; `start`/`submit`/failed-`verify` run no posture recomputation; `PASS` drops the re-derived count; `FAIL` leaves `verified_at`/`verified_by_user_id` null — `routes/lines.py:343-402`

### Pass 3 (runs, consumption, closing, holds/shipping/recall, cost, shelf life) — 22 edits: 16 ambiguity-pins, 6 mismatch-revisions
465 lines / 119,562 chars → 465 lines / 129,852 chars (+10,290, all in-paragraph).
- §2.7 — insert — ambiguity — `expected_process_run_version` required integer ≥ 1, so 0/negative/non-integer is `ERR_INVALID_REQUEST` not `ERR_STALE_PROCESS_RUN_VERSION` — `routes/runs.py:45,48`
- §2.11 ¶2 — insert — ambiguity — creation sequence is the final tie-break for receipt/run/wash-system cascade ordering — `services/cascades.py:12-21`
- §3.6 ¶2 — insert — ambiguity — planned run's initial values: `input_lb` 0.00, excursion count 0, four case counters 0, sixteen close-only fields null and all present in the representation — `routes/runs.py:213-229`
- §3.6 rule 5 — insert — ambiguity — preceding-run tie-break is the earlier-created run — `routes/runs.py:152`
- §3.6 gate 6 — insert — ambiguity — "newest `VALIDATED`" is the `validated_at`/`sequence_no` key, not `scheduled_for`; the `last_run_ended_at` comparison is skipped when that field is null — `routes/runs.py:299-308`
- §3.6 start effects — insert — ambiguity — the start's chemistry evaluation is read-only (system row never written, never pushed to `DUMP_REQUIRED`); line row untouched when `last_run_allergen_group` already matches — `routes/runs.py:315,322-324`
- §3.7 balances ¶ — insert — ambiguity — balances recomputed not adjusted, so a sub-cent-of-a-pound draw leaves the load row unmutated; repeat draws on one load permitted — `routes/runs.py:77-82`
- §3.7 void ¶ — insert — ambiguity — `ERR_RUN_NOT_RUNNING` precedes `ERR_CONSUMPTION_ALREADY_VOIDED` — `routes/runs.py:420-425`
- §3.7 traceability ¶ — insert — ambiguity — `ACTIVE`-only lineage arrays de-duplicated in first-appearance order; the two consumption counts; `case_count` over all statuses; `effective_code_date` = final-else-provisional-else-null; ancestor chain starts at the immediate source, uncapped, cycle-safe, empty when not a rework — `routes/runs.py:607-655`
- §3.8 yield ¶ — revise — mismatch — `yield_pct` divides the stored, already-rounded `output_lb`, not the raw product — `routes/runs.py:505-506`
- §3.8 cost ¶ — insert — ambiguity — a closing reading with null `topup_ppm_required` yields a zero sanitizer component — `services/cost.py:15`
- §3.8 automatic holds ¶ — revise — mismatch — hold-and-release opens first so it owns `cases_held_count` (the excursion hold records 0); both record `shipped_case_count` 0; the close bumps run `version` by 2 when either branch fires; the line row is two versions ahead on the excursion branch — `routes/runs.py:565-584`, `services/holds.py:64-76`
- §3.9 ¶1 — revise — mismatch — hold-open refusals are `ERR_HOLD_INVALID_STATE` with disposition reported before `CANCELLED`; the client may name any of the five reasons; the sweeps do not apply the `CANCELLED` refusal and will hold a cancelled run — `routes/holds.py:34-38`, `services/cascades.py:52-55`
- §3.9 ¶2 — insert — ambiguity — the hold's counts are written as part of creation so a new hold is `version` 1; the run row is not mutated when a second hold changes nothing — `services/holds.py:45-76`
- §3.9 submit-sample ¶ — insert — ambiguity — the state check precedes the round-count check — `routes/holds.py:62-71`
- §3.9 record-result ¶ — insert — ambiguity — an omitted `latest_apc_cfu_g` is written as null, clearing any earlier count — `routes/holds.py:92`
- §3.9 release ¶ — insert — ambiguity — a release on a run that never reached `CLOSED` computes no final shelf life/code date and re-dates nothing; a case already carrying the final values and not on hold is not a mutation — `routes/holds.py:133-142`
- §3.9 reject ¶ — revise — mismatch — rejection's state check is its only guard: no segregation of duties, no other-hold gate, no negative-result gate; it computes no final shelf life — `routes/holds.py:151-167`
- §3.9 ship ¶ — revise — mismatch — the run row is also a mutation (+1), not just the case — `routes/holds.py:198-199`
- §3.9 recall ¶ — revise — mismatch — descendants held even when they never consumed the lot; roots never re-held as descendants; cycle-safe walk; all depths held as one `planned_start_at`-ordered batch; the recalled lot advances by 2 versions when the sweep held a run that consumed it — `services/cascades.py:144-194`
- §4 table (GET hold-records) — revise — ambiguity — descending tie-break is the later-created record — `routes/holds.py:53`

Pass 3 verified-correct with no change needed: all planning/start/close/consumption gate orders and error ids; every error's HTTP status against `errors.py`; all 18 endpoint role lists; the inclusive `[started_at, closed_at]` reading window; the full four-component cost formula and remainder waterfall; both shelf-life variants; `case_code` and `code_date_label` composition; the four-way release guard order; the three shipping checks.

### Aggregate
**56 edits total (38 ambiguity-pins, 18 mismatch-revisions).** `PRD.md`/`PRD_FINALIZED.md` 463 lines / 100,904 chars → `PRD_COMPLETED.md` 465 lines / 129,852 chars (**+28,948 chars, +28.7%**).

Orchestrator verification: `PRD_COMPLETED.md` md5 `ced41f49…` differs from `PRD_FINALIZED.md` md5 `9438d401…` (the scan demonstrably ran); 28 `^#` headings and 25 `##`/`###` section headings intact; file still ends at the final §5 error-table row; pass-1 sentence ("Neither counter is accumulated") and pass-2 sentence ("stored field on the line row") both survive in the final file, confirming no pass clobbered another. Every module under `workspace/implementation/` is covered exactly once across the three partitions.
