# Worklog — task_2106_building_commissioning

## Step 1: Create Task Directory — 2026-08-16T00:00:00.000Z

Created `./tasks/task_2106_building_commissioning/` and `./tasks/task_2106_building_commissioning/workspace/`. Index 2106 chosen (highest existing was 2105).

## Step 3: Copy Shared Files — 2026-08-16T00:00:00.000Z

Copied `./INSTRUCTION.md` → `./tasks/task_2106_building_commissioning/workspace/INSTRUCTION.md` (1424 bytes). (Executed early; independent of Step 2.)

## Step 2: Generate Scaffold — 2026-08-16T03:47:00.000Z

All three artifacts are written and the scaffold linter reports clean.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    70
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     62
  Calls scanned (§1.8+§1.9):  828

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files

- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

## Shape

`compliance_audit` + `workflow_orchestration`, **flat** topology, **cyclic** state machines, **segregation_of_duties** roles (all four diversity-prioritized options in §0.2–§0.3), `difficulty_level: beyond_expert`.

13 entities · 14 state machines · 2 OCC rules · 11 calculations · 35 strictly-ordered validations · 70 endpoints · 45 errors · 5 roles. Depth is spent on coupling, not volume: `CxProject.readiness_posture` is a derived gate; `EquipmentUnit` carries two independent state dimensions; `Submittal`, `PrefunctionalChecklist` and `Issue` all loop.

Difficulty design: 9 rule_ids × 2 = 18 instances. Corner design: 62 active instances + 7 `excluded_because` stubs across all nine claim-extraction-guide sections.

## Load-bearing mechanics

- **Dual variants on different domains** — `acceptance_completion_score` reads 85.00 PROVISIONAL vs 60.00 FINAL on one unchanged project; `retro_savings_estimate` reads 46537.50 DEEMED vs 19800.00 MEASURED on one `EnergyBaseline`.
- **Combinatorial modes (b) and (c)** — retainage pins round-per-issue-then-sum (112500, *not* 112501 from sum-then-round); `credit_documentation_score` pins a single four-step pass where the tier feeds the score and the final tier is never fed back (48.75 / NONE, where a fixed-point re-evaluation would give 15.00).
- **Four-hop cascade** — FAILED test → blocking S1 issue → equipment demotion → evidence staling → SUBMITTED credit auto-WITHDRAWN. A three-hop cascade runs the reverse from `verify-closure`.
- **Two interval geometries** — witness windows are closed with a 60-min buffer against project `witness_capacity` (touching collides); seasonal windows are half-open per equipment (touching is legal).
- **Two conserved quantities** — `retainage_withheld_cents` (money) restored exactly by issue void; `verified_prefunctional_units` (weight units) restored exactly by checklist reject/re-verify.
- Default logical clock fixed at `2026-08-01T00:00:00Z` on `POST /_clock/set_current_utc`, per the mandatory rule.

Every formula-derived `assert:` literal was produced by executing the scaffold's own `formula:` + `constants:` in Python before writing it.

## Three scaffold repairs found while authoring §1.9 (the §1.5 audit pass working as intended)

1. Added `EquipmentUnit.install_status STARTED_UP → REMOVED` — previously only `NOT_INSTALLED`/`INSTALLED` could be removed, so a commissioned unit was unremovable.
2. Added `Issue DEFERRED → VERIFIED_CLOSED` — the `DeferredTest EXECUTED_PASS` side effect claimed a transition the Issue machine never declared.
3. Relaxed validation priority 12 so `schedule-retest` requires only `install_status == STARTED_UP` — otherwise a failed life-safety test demoted its own equipment to `UNVERIFIED` and the issue became permanently un-closable (deadlock).

## Note on surface size

`api_prefix` is `"/"` — required for a flat topology, since the linter derives each entity's collection segment by stripping the prefix and expecting `<segment>/{id}`. Endpoint count (70) exceeds the Expert band's 20–32 because the scenario names eight distinct sub-workflows and each of the 13 entities needs a single-resource GET plus an FK-filtered list for reverse-reachability; the extra surface is GET/discovery, not extra mechanics.

## Step 4: Generate PRD — 2026-08-16T04:03:00.000Z

The PRD is complete. Final verification of all three hard contracts:

**Contract 1: Field-Name Coverage**
```
Field coverage check:
- entities[].fields: 114 required, 114 present, 0 missing
- endpoints[].request_body: 65 required, 65 present, 0 missing
- endpoints[].query_params: 20 required, 20 present, 0 missing
- extra (checklist item sub-fields + /readiness computed-read outputs + clock output): 11 required, 11 present, 0 missing
Status: PASS
```
Every name appears as a standalone backticked token (no reliance on substring matching).

**Contract 2: Rule Coverage**
```
Rule coverage check:
- validations[] with priority: 35 checked, 35 expressed in prose (§2.5 renders the full 35-row precedence chain in order, each with its error_id, HTTP status and enumerated applies_to scope), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (§2.9 names POST /cx-plans and POST /certification-credits/{id}/submit, expected_project_version as non-optional, ERR_STALE_PROJECT_VERSION, HTTP 412; framed purely as stale-version, no "simultaneous"/"race" wording), 0 missing
- state_machines[].transitions: 75 checked across 14 machines, 75 fully expressed (from/to states, every precondition paired with its error, every side effect incl. version bumps and BLOCKED/PLANNED deferred-test cascades), 0 missing
- calculations[]: 11 checked, 11 fully expressed in precise prose with all constants embedded in business context, 0 missing
- validations[] conditions: 35 checked, 35 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 70 endpoints checked, all side-effect sets expressed, 0 missing
- entities[].fields[] structured content: 114 checked (types, defaults, initial values, enum members, range constraints), 114 reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (3 submittal decisions; 3 functional-test outcomes; 3 issue-reopen sources; 3 issue-void sources; deliver from PLANNED/RETURNED; REMOVED from 3 install states; PROVISIONAL/FINAL score variants; DEEMED/MEASURED savings variants), 8 with equal prose density, 0 asymmetric
Status: PASS
```

**Contract 3: §3 Path Purity**
```
Path purity check (§3 only):
- backtick tokens scanned: 1037
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Output**: `workspace/PRD.md` (~99 KB, 517 lines).

Structure: §1 Introduction (3 paragraphs, framed from the CxA firm's chain-of-custody pain point); §2 with 11 subsections (2.1 RBAC, 2.2 verbatim envelope — byte-identical to `section-2.2-response-structure.md`, 2.3 Pagination, then 8 domain-named cross-cutting subsections: Common Resource Properties/Logical Clock, Order of Rejection, Readiness Posture Gate, Retainage Invariant, Conserved Roll-Ups & Cascades, Stale Project Views, Precision & Interval Geometry, Segregation of Duties & Engagement Scope); §3 with 9 workflow subsections grouped by commissioning lifecycle stage; §4 with a 4-column, 70-row endpoint table; §5 with a 2-column, 45-row error table. The document ends at §5 — no audit footer.

Notable content decisions worth flagging: all five roles carry `identity: opaque`, so §2.1 states that explicitly and names the seven fields where the server records `X-User-ID` (which is what makes the segregation-of-duties comparisons meaningful). The two different interval geometries (closed + 60-minute buffered witness windows vs. half-open unbuffered seasonal windows) are contrasted side by side in §2.10 so they cannot be conflated. The pinned rounding order — round-per-row-then-sum for retainage and the severity index, versus sum-unrounded-then-round-once for the acceptance score — is called out as part of the contract in three places. The four-step credit documentation score is explicitly described as a single top-to-bottom pass with `final_tier` never fed back into `documentation_score`. Only two files were read from the task directory: `SCAFFOLD.yaml` and `worklog.md`; neither design index was opened.

**Orchestrator note**: leak-check run on PRD.md for §1.8 worked-example literals (112500 / 112501 / 48.75 / 46537.50 / 19800 / 85.00 / 60.00) — no test-answer values present. The single "15.00" hit is the scaffold's own per-stale-evidence penalty constant, which legitimately belongs in PRD prose.

## Step 6: Generate Implementation — 2026-08-16T04:28:00.000Z

(Completed before Step 5; the two ran concurrently.)

All servers cleaned up. The implementation is complete and verified.

## Summary

Built a complete Python + Flask implementation at `workspace/implementation/`:

```
start.sh          # guarded-install foreground launcher (exec, 0.0.0.0:$PORT, default 10000)
requirements.txt  # flask>=3.0.0
app.py            # blueprint registration, envelope error handlers, global request mutex
core.py           # in-memory store, logical clock, error catalogue, envelope, auth, validators
calc.py           # all enums/constants + every calculation rule
services.py       # cross-aggregate cascades + immediate roll-up reconciliation
finders.py        # path/FK lookups mapped to the 12 not-found error ids
routes/*.py       # 12 resource modules covering all 63 endpoints
```

**Verification**: 321 assertions across three hand-written end-to-end suites all pass — auth/RBAC, every 404 code, envelope/pagination shape, the full commissioning chain (requirements → plan pinning → equipment → checklists → functional tests → issues → seasonal tests → deliverables → credits → acceptance), plus the FAILED-test four-hop cascade (issue → demotion → evidence staling → credit withdrawal), FROZEN posture entry/exit with deferred-test blocking/unblocking, retainage cap rejection with no row written, both interval geometries (buffered-closed witness vs. unbuffered half-open seasonal), aging multipliers via the logical clock, and both dual-variant calculations. Store starts empty on every boot (no seeding anywhere); `bash start.sh` serves HTTP in ~0.5 s across repeated reboots.

**Key fidelity decisions taken from PRD prose where it outranks the scaffold:**
- `CxProject.version` increments **only** for the 17 operations enumerated in PRD §2.8 (plus a separate increment per posture change) — notably *not* for equipment registration, requirement/plan approval, submittal review, or deferred-test/deliverable creation. This is what makes `expected_project_version` OCC land correctly.
- Roll-ups (`retainage_withheld_cents`, `verified_prefunctional_units`, `open_blocking_issue_count`, `acceptance_completion_score`, evidence freshness, credit scores) are recomputed from their stated definitions after every mutation, which satisfies the exact-reversal invariants by construction; `withdrawn_credit_count` is a true event counter since a withdrawn credit can return to `IN_PREPARATION`.
- Validation ordering follows PRD §2.5's 35-step chain verbatim (e.g. `ERR_PROJECT_FROZEN` before phase checks; equipment-readiness before plan-approved on test scheduling), not the narrative order in §3.
- `created_at`/`updated_at` use a strictly monotonic wall clock (unique per row at ms resolution, per the scaffold's tie-break note); all business stamps (`opened_at`, `approved_at`, `staled_at`, …) read the logical clock.

**Two genuinely ambiguous points, resolved and worth flagging:**
1. Cross-engagement `evidence_ref_id` on credit-evidence attachment returns `ERR_EVIDENCE_REF_INVALID` (422) — PRD §3.8 and §2.5 #24 both assign that case to this error, though §2.5 #7 also lists evidence attachment under `ERR_PROJECT_SCOPE_MISMATCH` (409).
2. Verifying a checklist whose unit has `blocking_issue_count > 0` returns `ERR_INVALID_STATE` (409), checked last per PRD §3.3's prose order; the PRD names no error for that gate and `ERR_EQUIPMENT_NOT_READY` is not declared for `/verify` (both candidates are 409, so only the `error_id` differs).

**Orchestrator note**: independent route audit confirms all **70** scaffold endpoints are implemented (the subagent's "63" is its own module grouping). Route-vs-scaffold diff is empty once path-parameter names are normalized (`{id}` vs `{credit_id}` etc.) — 70 impl route entries, 70 scaffold endpoints, 1:1 shape match.

## Step 5: Generate Unit Tests — 2026-08-16T04:35:00.000Z

Test infrastructure and suite are complete and verified.

## What was generated

**`test_helpers/`** (Stage 1, ~2,650 lines)
- `types.py` — 24 enums + 13 entity TypedDicts. All entities carry `id`/`created_at`/`updated_at`/`version` (PRD §2.4: "No entity in this system is exempt"); embedded checklist items deliberately carry none.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (63 methods, including `/_clock/set_current_utc`).
- `api_errors.py` — all 45 `ERR_*` ids + HTTP map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions, `assert_readiness`, roll-up invariants, whole-cent checks.
- `factories.py`, `constants.py`, `test_users.py` (5 opaque roles + per-user builders for the two segregation-of-duties rules).
- `fixtures.py` — 5 tiers of composite setups, incl. `setup_dual_variant_completion_project`, `setup_submitted_gold_credit_with_test_in_progress` (4-hop cascade preamble), `setup_frozen_project_with_blocked_seasonal_test`, `setup_three_holds_on_life_safety_unit`, `setup_two_ready_units_with_occupied_window`, `setup_project_in_acceptance_phase`.

**`test_suite/`** (Stage 2) — `conftest.py` + 10 domain-named files, **98 test functions / 105 collected cases**.

## Coverage audit (verified programmatically)

- **Queue A**: all **18/18** difficulty instances have exactly ≥2 tests tagged `Design: Difficulty/<rule_id>/<name>`.
- **Queue B**: all **62/62** non-stub corner instances have ≥1 test tagged `Design: Corner/<section>/<name>`. The 7 `excluded_because:` stubs were **not** translated; all 7 `difficulty_instance` cross-references were checked and resolve to real difficulty-design names.
- **Zero instances skipped** — every non-stub instance passed the PRD-first two-condition filter, so there are no gaps to report.
- Every docstring ends with exactly one `Design:` line; **every quoted PRD citation was machine-checked to survive a literal whitespace-normalized grep of `workspace/PRD.md`** (0 failures). No `skip`/`skipif`/`xfail` anywhere; no freelance tests invented from `SCAFFOLD.yaml`.

## Notable translation decisions

- `entities/equipment_unit_system_fields_client_input_ignored` is written as the design's own disjunction (400 `ERR_VALIDATION` **or** 201 with `NOT_INSTALLED`/`UNVERIFIED`/0 defaults), since the PRD pins only the resulting row state.
- Priority-conflict pairs (D9, D10) are split into "winning error" + "loser error not returned and no row written", both citing PRD §2.5's explicit ordering sentence — never a bare precedence claim.
- Dropped one over-strict invariant during review: `retainage_withheld_cents <= cap` is not a PRD-stated global invariant (the cap only guards issue logging), so it is no longer asserted structurally.

`pyflakes` is clean and `pytest --collect-only` succeeds; tests were not executed since no implementation exists yet under `workspace/`.

## Step 7: Run Tests and Iterate — 2026-08-16T04:52:00.000Z

Clean sweep achieved. Final state: **8/8 rounds at 105/105**.

## Summary

**Iterations run:** 2 (baseline sweep at 103/105 in all 8 rounds → one fix batch → 105/105 in all 8 rounds).

No flakiness was observed: the same 2 tests failed deterministically in all 8 rounds of the baseline sweep, and all 105 passed in all 8 rounds afterward.

**Tests deleted:** none. Both failures survived STEP 1a (PRD verbatim-covers) and STEP 1b (uniquely derivable) and resolved at STEP 2 as test bugs.

**Root cause (shared by both failures):** `test_helpers/fixtures.py` `setup_gold_credit_on_verified_equipment` drives the training deliverable all the way to `ACCEPTED`, and both tests then called `POST /closeout-deliverables/{id}/return` on it. PRD §3.7 states verbatim that acceptance "moves the row `DELIVERED` → `ACCEPTED`" and that "`ACCEPTED` is terminal", and that return "moves the row `DELIVERED` → `RETURNED`". The implementation's `ERR_INVALID_STATE` ("Only a DELIVERED deliverable may be returned") is therefore PRD-correct — the fixture/request was inconsistent with PRD, not the implementation.

A corollary worth recording: because §3.8 makes a `TRAINING`/`MANUAL_SECTION` evidence row fresh only while the deliverable is `ACCEPTED`, and `ACCEPTED` is terminal, the §3.7 return→stale cascade can never produce a false→true flip in a PRD-faithful implementation. Any test needing a fresh→stale flip must use a different, reachable trigger.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `setup_gold_credit_on_verified_equipment`: added an `accept_training: bool = True` parameter so a test that needs to exercise `return` can stop the training deliverable at `DELIVERED`, the only source state PRD §3.7 admits. Default behaviour is unchanged, so `setup_submitted_gold_credit_with_test_in_progress` (which needs 4 fresh rows to submit) is unaffected.

**Fixes applied to `test_suite/`:**
- `test_suite/test_08_certification_credits_and_evidence.py` — `test_returning_a_training_deliverable_stales_only_its_own_evidence_row`: setup now passes `accept_training=False` and asserts the deliverable is `DELIVERED` before returning it. All four original assertions (training row stale, the other three fresh, `fresh_evidence_count == 3`, `stale_evidence_count == 1`) are kept byte-identical; only the illegal precondition was corrected. Docstring gained the two PRD §3.7 sentences that pin the legal source state.
- `test_suite/test_08_certification_credits_and_evidence.py` — `test_the_score_uses_the_provisional_tier_weight_in_a_single_pass`: replaced the illegal `return`-on-`ACCEPTED` staling trigger with a PRD-reachable one — logging an `S2` (blocking) issue against the unit, which per PRD §3.4/§3.5 demotes the unit and stales exactly its `EQUIPMENT_VERIFICATION` evidence row while the checklist stays `VERIFIED` and both deliverables stay `ACCEPTED`. This keeps the input to the score identical (4 fresh → 3 fresh + 1 stale of 4 required), so every scored assertion is unchanged: `completeness_ratio == 0.75`, `provisional_tier == SILVER`, `documentation_score == 48.75`, `final_tier == NONE`, `status == IN_PREPARATION`. Added an explicit four-row freshness check and the two PRD sentences licensing the new trigger. The test's design intent is fully preserved — 48.75 is exactly the discriminator proving the **provisional** tier weight (0.85) is used in a single pass rather than the final tier being fed back.

**Fixes applied to `implementation/`:** none. No implementation change was warranted; the deliverable state machine was already PRD-faithful, and weakening its `DELIVERED`-only gate to accommodate the fixture would have violated the cardinal rule against relaxing a PRD-required check.

**Orchestrator verification**: independently re-read all 8 `results.{1..8}.json` — every round reports `passed=105 / total=105 / failed=0`.

## Step 8: Finalize PRD — 2026-08-16T05:02:00.000Z

Done. `PRD_FINALIZED.md` written with exactly one edit.

## Line counts
- `PRD.md`: 516 lines — `PRD_FINALIZED.md`: 516 lines — **0.00% line delta** (1 line revised in place, +1 sentence).

## Changes

- **§3.8 (Certification Credit Documentation and Evidence Freshness), line 350 — revise** — pinned the birth-time freshness state of a credit evidence row: a row attached to an artifact already outside its evidentiary state is *born* with `is_stale` true and `staled_at` already stamped from the logical clock (a row born fresh carries `is_stale` false / `staled_at` null), and that initial evaluation is part of writing the row rather than a later mutation, so a born-stale row still reads `version` 1 — `implementation/routes/credits.py:103-112` (with `core.py:237-248` `new_row`).

## Per-edit pre-edit search log

**Edit 1 — §3.8 line 350**

(a) **Subject identified:** the `is_stale` / `staled_at` pair on a `CreditEvidence` row at creation time, and the version/`updated_at` consequences of stamping it.

(b) **Impl paths enumerated** (grepped `staled_at|is_stale` across all of `implementation/**/*.py`; every hit read):
- `routes/credits.py:103-112` — `attach_evidence`: the **only** creation site for an evidence row. `new_row(...)` with `is_stale: False, staled_at: None`, then `if calc.evidence_is_stale(row): row["is_stale"]=True; row["staled_at"]=clock.now_iso()` — deliberately **without** a `touch(row)` call, so `version` stays 1 and `updated_at == created_at`.
- `core.py:237-248` — `new_row`: confirms `version: 1`, `created_at == updated_at` at birth.
- `services.py:159-166` — `sync_evidence_freshness`: the only *other* write site; flips in both directions, stamps `staled_at` only on false→true, calls `touch(row)`. Already covered verbatim by the existing sentence, left untouched.
- `calc.py:412-431` — `evidence_is_stale`: all six evidence kinds; matches PRD §3.8's enumeration exactly (plus a dangling-ref guard that is unreachable because `_resolve_evidence_ref` at `routes/credits.py:16-40` pre-validates family + engagement).
- `services.py:127-135` (`recompute_credit`) and `routes/credits.py:126-131` (`?is_stale=` filter) — read-only consumers; unaffected by the wording.
- Cross-checked the sentence against §2.4's "`version` … increments by one on every mutation" so the new clause does not contradict the global rule.

(c) **Wording adjustment made:** two. (1) Phrased the initial state as "born with" rather than "flips to", so the sentence cannot be read as a mutation that would bump `version` past 1 — `attach_evidence` skips `touch`. (2) Added the explicit "that initial evaluation is part of writing the row rather than a later mutation of it, so a row born stale is still returned with `version` 1" clause, because §2.4's blanket increment-on-mutation rule would otherwise leave a fresh implementer free to `new_row` + `touch` and return `version` 2. Also stated the born-*fresh* case (`is_stale` false, `staled_at` null) so the sentence describes both branches of `routes/credits.py:110` rather than narrowing to the stale one.

## Items deliberately **not** patched

Both `<step_7_diff>` items were verified against `implementation/` and found already uniquely determined by PRD prose — no edit warranted:

- **Deliverable-return source state.** `routes/deliverables.py:117-135` gates on `status != "DELIVERED"` → `ERR_INVALID_STATE`. PRD §3.7 line 342 ("moves the row `DELIVERED` → `RETURNED`") + line 340 ("`ACCEPTED` is terminal") + §2.5 rule 11 ("target resource is in a status from which the requested transition is declared … applies to every state-changing action endpoint") already pin this. Also confirmed the impl correctly omits a `FROZEN` check here, matching §2.5 rule 9's closed list of five frozen-guarded operations, and §4 line 453 already pins the `CxAuthority`-only role.
- **Evidence-freshness conditions per kind.** `calc.evidence_is_stale` matches §3.8 line 350's six-way enumeration one-for-one; the `row is None` fallback is unreachable.
- **Issue-severity → demotion → evidence-staling cascade.** `services.create_issue` (demote iff `blocks_acceptance` and unit in `VERIFIED_SET`) → `reconcile()` → `sync_evidence_freshness` → `recompute_credit` is pinned verbatim by §3.4 line 282, §3.5 line 308, and §3.8 lines 359/365. `apply_issue_status_change`'s promotion path (`was_live != now_live`, count 0, checklist `VERIFIED`) matches §3.4 line 282 and §3.5 line 313.
- Also checked and left alone: `return` clearing only `delivered_by_user_id` (§3.7 enumerates what changes; impl leaves `attendee_count`/`duration_minutes`/`session_start`/`coverage_ratio` intact), and `attach_evidence` not refusing a non-evidentiary artifact (§3.8/§2.5 rule 24 restrict `ERR_EVIDENCE_REF_INVALID` to family and engagement mismatches only).

**Orchestrator verification**: `diff PRD.md PRD_FINALIZED.md` confirms a single hunk — `350c350`, one line revised in place, no other changes.

## Step 9: Complete PRD — 2026-08-16T05:12:00.000Z

`workspace/PRD_COMPLETED.md` is written.

**Source vs completed:** `PRD_FINALIZED.md` 516 lines / 100,060 chars → `PRD_COMPLETED.md` 516 lines / 104,465 chars (**+4,405 chars, +0 lines**). All 21 changes are in-paragraph line replacements; no new sections, no heading or endpoint/error-table changes.

**Counts:** 19 ambiguity-pins, 2 mismatch-revisions.

**Changes**

- §2.3 — insert — ambiguity — a `limit`/`offset` that does not parse as an integer is also `ERR_VALIDATION` — `core.py:460-479`
- §2.3 — insert — ambiguity — list filter values are never enum-validated (unknown value → empty page, not 400); undeclared query params ignored — `routes/projects.py:64-72`
- §2.4 — insert — ambiguity — a row's `version` advances by exactly one per request however many times that request writes it (engagement excepted, per §2.8) — `core.py:251-262`
- §2.5 #7 — **revise** — **mismatch** — credit evidence attachment removed from the `ERR_PROJECT_SCOPE_MISMATCH` list (cross-engagement `evidence_ref_id` → check 24's `ERR_EVIDENCE_REF_INVALID` 422); checklist creation noted as having no second entity — `routes/credits.py:16-41`
- §2.8 — insert — ambiguity — the version-increment enumeration is exhaustive both ways: roll-up-only refreshes bump `updated_at` only, and server-opened issues carry no increment of their own — `services.py:172-212`, `routes/submittals.py:88-96`
- §2.11 — **revise** — **mismatch** — evidence rows dropped from the scope-mismatch illustration (they answer `ERR_EVIDENCE_REF_INVALID` 422); checklist example replaced with submittal/deliverable — `routes/credits.py:37-40`
- §3.1 — insert — ambiguity — the `FUNCTIONAL_TESTING → ACCEPTANCE` roll-call includes `REMOVED` units — `routes/projects.py:109-112`
- §3.1 — insert — ambiguity — requirement revise answers `201` returning the new `DRAFT` row, not the predecessor — `routes/requirements.py:91-108`
- §3.3 — insert — ambiguity — `REMOVED` is terminal; every other install move (skip/repeat/backwards/out of `REMOVED`) is `ERR_INVALID_STATE` — `routes/equipment.py:15-20,83`
- §3.3 — insert — ambiguity — a unit may carry several checklists; "*the* checklist is `VERIFIED`" means any of them — `calc.py:190-191`
- §3.3 — insert — ambiguity — item append answers `201` returning the whole checklist row — `routes/checklists.py:94`
- §3.3 — insert — ambiguity — `record-item` has no status gate (works in `DRAFT`/`REWORK`/`EXECUTED`/`VERIFIED`) — `routes/checklists.py:98-116`
- §3.3 — insert — ambiguity — the `blocking_issue_count == 0` verify gate is `ERR_INVALID_STATE` (409), evaluated **last**, after the safety-item gate — `routes/checklists.py:155-157`
- §3.4 — insert — ambiguity — `measured_value` required and range-unconstrained — `routes/functional_tests.py:130`
- §3.5 — insert — ambiguity — `source_ref_id` stored as supplied, never resolved against any collection or engagement — `routes/issues.py:25`
- §3.5 — insert — ambiguity — deferral with no `PLANNED`/`BLOCKED` seasonal test → `ERR_INVALID_STATE` (409) — `routes/issues.py:163-167`
- §3.6 — insert — ambiguity — deferred-test `measured_value` required and unbounded — `routes/deferred_tests.py:92`
- §3.7 — insert — ambiguity — `attendee_count`/`duration_minutes` required integers with no range constraint — `routes/deliverables.py:74-75`
- §3.8 — insert — ambiguity — evidence attachment is ungated by credit status; `IN_PREPARATION`/`SUBMITTED`/`AWARDED`/`DENIED` packages keep their status — `routes/credits.py:114-116`
- §3.8 — insert — ambiguity — awarding a `final_tier` `NONE` package → `ERR_INVALID_STATE` (409), checked after the `SUBMITTED` gate — `routes/credits.py:180-183`
- §3.9 — insert — ambiguity — `post_kwh`/`post_hdd` required numbers with no range constraint — `routes/baselines.py:74-75`

Both impl-flagged ambiguities are resolved: the cross-engagement `evidence_ref_id` case is now pinned to `ERR_EVIDENCE_REF_INVALID` (422) in §2.5 #7 and §2.11, and the `blocking_issue_count` verify gate is pinned to a last-evaluated `ERR_INVALID_STATE` (409) in §3.3. Everything else in `implementation/` — the 35-check screening order, all 11 calculations, the 14 state machines, the 17-operation project-version list, and all 70 endpoint role/status pairs — was walked and already uniquely pinned by the source PRD.

**Orchestrator verification**: `diff PRD_FINALIZED.md PRD_COMPLETED.md` reports exactly 21 changed lines, matching the 21 reported edits; line count unchanged at 516.

---

# PIPELINE COMPLETE — task_2106_building_commissioning

Final state: **8/8 parallel rounds at 105/105 passing**. 0 tests deleted, 0 implementation fixes required during Step 7.
