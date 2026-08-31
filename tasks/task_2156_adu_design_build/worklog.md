# Worklog — task_2156_adu_design_build

Scenario: 2156. Accessory Dwelling Unit Design-Build (California ADU builder): feasibility screening (zoning/setback/utility capacity), design package & permit submittal by jurisdiction, financing option guidance & appraisal challenges, utility separation vs shared metering decision, construction sequencing on occupied property, inspection scheduling & final certificate, rental readiness & short-term rental restriction check, homeowner change orders — difficulty: harder than expert level

## Step 1: Create task directory — 2026-08-25T12:52:14.362Z

Created `tasks/task_2156_adu_design_build/` and `tasks/task_2156_adu_design_build/workspace/`.

## Step 3: Copy shared files — 2026-08-25T12:52:14.362Z

Copied `./INSTRUCTION.md` to `tasks/task_2156_adu_design_build/workspace/INSTRUCTION.md`. (Run early; independent of Step 2.)

## Step 2: Generate scaffold — 2026-08-25T13:48:00.000Z

All three scaffold artifacts are generated and lint-clean.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_2156_adu_design_build/SCAFFOLD.yaml` (§1.0–§1.7 + `concurrency_rules`)
- `/home/ubuntu/github/CodingPRD/tasks/task_2156_adu_design_build/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_2156_adu_design_build/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    51
  §1.1 entities declared:     13
  §1.8 instances scanned:     20
  §1.9 instances scanned:     53
  Calls scanned (§1.8+§1.9):  707

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Design summary

**Profile**: `workflow_orchestration` × `temporal_windowing`; graph topology (flat peer collections + two self-referential FKs: `ChangeOrder.supersedes_change_order_id`, `ConstructionPhase.depends_on_phase_id`); cyclic state machines; `segregation_of_duties` role model; immediate consistency. `api_prefix: ""` (root-level flat collections, required for FK reverse-reachability derivation).

**Calibrated above the Expert band** per the "harder than expert level" request: 13 entities, 51 endpoints, 53 errors, 6 calculations, 8 state machines (7 entities, AduProject carrying two axes), 39 ordered validations, 3 OCC rules on 2 different parents.

**Difficulty coverage** — 9 rules, 20 instances (3 rules carry a bonus third):
- Dual-variant on two domains: feasibility `LOCAL_ORDINANCE` vs `STATUTORY_MINISTERIAL` (FAIL vs PASS_WITH_CONDITIONS on the same row) and appraisal `SALES_COMPARISON` vs `INCOME_CAPITALIZATION` (gap 16 320 465 vs 0).
- Combinatorial across all three §0.5 modes: per-component rounding order (total 1 120 465, not 1 120 466), pinned markup-tier evaluation order (fee 150 000), and a nested `max(0,min(100,…))` five-input score.
- Depth-4 cascade (plan-check corrections → project → phases → appointments) and a depth-3 cascade (change-order approval → contract price → financing SHORTFALL) from different triggers.
- Two interval regimes on different resources: closed day-intervals + 2-day habitability buffer on Property vs half-open slots + per-day aggregate capacity on Inspector.
- Two conserved quantities: contract-price ledger (approve→void restores 24 000 000 exactly) and inspector slot capacity (book→cancel restores `remaining_slots`).

**Corner coverage** — 56 instances across all nine claim-extraction-guide sections (53 with executable recipes, 3 `excluded_because:` stubs pointing at named §1.8 instances).

**Key notes for downstream**: every formula-derived assertion was computed in Python and written as a literal; logical clock default is pinned at `2026-08-01T00:00:00Z` via `POST /_clock/set_current_utc`; `Homeowner` identity is `entity_backed:Property` (X-User-ID = `AduProject.property_id`), `BuildingInspector` is `entity_backed:Inspector`. One structural adjustment was made mid-generation so the depth-4 cascade is reachable: `PermitSubmittal.submit` now also accepts projects in `PERMITTED`/`UNDER_CONSTRUCTION` (deferred-submittal / permit-revision packages), which additionally yields a `PERMITTED → PERMITTING → PERMITTED` cycle.

## Step 4: Generate PRD — 2026-08-25T13:57:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2156_adu_design_build/workspace/PRD.md` — 396 lines, ~80.5 KB, written incrementally (Write for §1–2.1, then seven separate heredoc appends), so no output-cap truncation.

**Structure** (skeleton designed from the ADU domain, not copied from the example): §1 three-paragraph introduction; §2 with ten subsections (2.1 RBAC, 2.2 verbatim envelope, 2.3 Pagination, 2.4 Common Properties/Versioning/Logical Clock, 2.5 Path Resolution, 2.6 OCC, 2.7 Rejection Precedence, 2.8 Money & Rounding, 2.9 Two Project Axes & Cascades, 2.10 Interval Semantics); §3 with nine lifecycle-ordered subsections (reference data -> project intake & feasibility -> metering -> permit/plan-check loop -> financing -> change orders -> construction sequencing -> inspections -> certificate); §4 4-column endpoint table (51 rows); §5 2-column error table (53 rows). Document ends at §5 with no audit footer.

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 120 required, 120 present, 0 missing
- endpoints[].request_body/input: 69 required, 69 present, 0 missing
- endpoints[].query_params: 16 required, 16 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 39 checked, 39 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 8 machines / 44 transitions checked, 44 fully expressed, 0 missing
- calculations[]: 6 checked, 6 fully expressed (all constants embedded in business context, no pseudocode), 0 missing
- validations[] conditions: 39 checked, 39 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 51 checked, 51 expressed, 0 missing
- entities[].fields[] structured content: 13 entities / 120 fields checked, all defaults+initial values+enum sets reconstructible, 0 missing
- sibling-branch symmetry: 6 groups checked (SEPARATE/SHARED, APPROVED/CORRECTIONS_REQUIRED, APPROVE/REJECT/REQUEST_REVISION, PASS/FAIL/PARTIAL, SALES_COMPARISON/INCOME_CAPITALIZATION, PLANNED->SCHEDULED / BLOCKED->SCHEDULED), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 749
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Verification performed and gaps backfilled**: automated diff of every `entities[].fields[].name` plus every endpoint `input` identifier against the PRD's backticked tokens returned empty on first pass — no field names needed backfilling. Two backfill passes were made anyway: (a) the nine CamelCase entity type names (`FeasibilityScreening`, `UtilityConnection`, `PermitSubmittal`, `CorrectionItem`, `FinancingScenario`, `ChangeOrder`, `ConstructionPhase`, `InspectionAppointment`, `OccupancyCertificate`) were absent as literal tokens since §3 used prose names — added as natural term introductions at first occurrence; (b) §2.6 was strengthened to name the three OCC `write_endpoint` paths explicitly (allowed in §2, which path purity does not police). Also verified: all 51 endpoint paths present, all 53 `error_id`s present and every one referenced in §2/§3 narrative, all 44 state-enumeration values and all enum-field values present in backticks, §2.2 byte-identical to `section-2.2-response-structure.md`, and no fuzzy/approximating words.

**Constraint honored**: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

**Orchestrator verification**: `wc -l` = 395; `## 4. Endpoint Definitions` present with 51 method rows; `## 5. Error Code Catalogue` present with 53 `ERR_` rows. No section-4/5 truncation.

## Step 6: Generate implementation — 2026-08-25T14:14:00.000Z

Implementation complete and verified.

## What was built

`/home/ubuntu/github/CodingPRD/tasks/task_2156_adu_design_build/workspace/implementation/` — Python 3 + Flask, in-memory dicts only, written across 9 modules (no single oversized write):

| File | Contents |
|---|---|
| `start.sh` | Guarded `pip install` (`if ! python3 -c "import flask"`), `exec python3 app.py` |
| `app.py` | Blueprint registration, `ApiError`/`HTTPException`/`Exception` handlers, `0.0.0.0:$PORT` (default 10000) |
| `common.py` | Store, envelope, auth decorator, 53-entry error->HTTP map, validation helpers, `Decimal` rounding |
| `calc.py` | All 6 calculations + their constants |
| `services.py` | Cross-aggregate cascades (phase blocking, scenario repricing, metering reversal) |
| `routes_core.py` / `routes_permit.py` / `routes_finance.py` / `routes_build.py` | 51 endpoints |

**Boot check: PASSED.** `PORT=18499 bash start.sh` from a fresh process, `GET /adu-projects?limit=5` -> HTTP 200 with the correct envelope, `POST /_clock/set_current_utc` -> 200; server killed cleanly. No 500s or tracebacks in any run. Route dump confirms exactly **51** registered routes matching the PRD §4 table.

## Verification

Two end-to-end scripts (in the session scratchpad) both pass against a fresh server:
- **Happy path + errors**: full intake->certificate flow, both feasibility pathways on one project, permit fee components (139750 / 85333 / 388720 / utility), OCC 412s, dup-code/dup-utility 409s, pagination 422s, RBAC 401/403.
- **Cascades & fiscal**: markup tiers 10/15/20% with strict boundaries, `ERR_CHANGE_CAP_EXCEEDED` persisting nothing, credit rounding away from zero (-12505 x 0.20 -> -2501), void restoring the ledger, `COMMITTED->SHORTFALL->COMMITTED`, the full 4-link corrections cascade (submittal -> project -> phases BLOCKED with cleared windows -> appointments CANCELLED, each with its own `version` bump), lazy `EXPIRED` transition persisting before the 409, metering reversal firing only on the *first* approved change order, `PARTIAL` holding the inspector slot, and rental classification with `OPEN_CHANGE_ORDERS`.

## Judgement calls worth flagging

1. **Precedence follows PRD §2.7 globally**, over the narrative ordering inside §3 sections. Notably identity-bound auth (step 5) runs *before* request-shape (6), OCC (7), and state (8) — so a wrong-owner homeowner gets `ERR_NOT_PROJECT_OWNER` even with a malformed body; likewise `screening_id` resolution precedes the `INTAKE` state check, despite §3.2 listing them the other way.
2. **Window-conflict buffer uses the literal formula**, not the prose. §2.10's "separated by more than two clear days" is looser than the concrete rule (`new.start <= P2.end + B AND P2.start <= new.end + B`); with `B=2`, windows ending 09-05 and starting 09-08 do *not* collide. Formula wins (scaffold priority 66 agrees).
3. **`window_end_date < window_start_date` -> `ERR_VALIDATION` (422)** at shape time. The PRD names no error for it; this was the only unassigned failure mode.
4. **`current_utc` echoes the supplied `to_iso8601` string verbatim** rather than reformatting to 3-fractional-digit form — "reports the new setting" read literally, and it survives an exact-equality assertion.
5. **Empty strings pass for free-text fields.** Validation priority 25 says only "present and carries the declared JSON type", so `title: ""` is accepted; empty IDs simply fail to resolve into a 404.
6. **`slot_start`/`slot_end` are stored and returned as the raw client strings** (parsed copies kept privately for overlap math), so `final_inspection_passed_at` echoes exactly what the test sent.

## Step 5: Generate unit tests — 2026-08-25T14:37:00.000Z

Test infrastructure and suite are complete and verified.

## What was produced

**`test_helpers/`** (9 modules, 1,790 lines) — Stage 1 infrastructure:
- `types.py` (401) — 20 status/role enums plus TypedDicts for all 13 entities. `FeasibilityScreening` and `OccupancyCertificate` carry only `id` + `created_at` (no `updated_at`/`version`), per PRD §2.4.
- `api_client.py` (205) — one method per endpoint (all 51), plus `raw_get` for the header-less auth test.
- `api_errors.py` (120) — all 53 error ids + HTTP map, registered via `set_error_http_status_map`.
- `assertions.py` (302) — per-entity assertions, plus invariant checkers `assert_permit_fee_components_sum`, `assert_screening_verdict_consistent`, `assert_contract_ledger_consistent`, `assert_availability`.
- `constants.py` / `factories.py` / `test_users.py` — thresholds, canonical PLMD/SNVL + P1/P2 + project A/B data, and per-instance header builders `make_homeowner_headers(property_id)` / `make_building_inspector_headers(inspector_id)` for the two entity-backed roles.
- `fixtures.py` (385) — 5 tiers, from primitives up to `setup_permitted_project`, `setup_corrections_round`, `setup_committed_income_scenario`, `setup_approved_change_order`, `setup_certificate_ready_project`. Ownership-gated calls always thread the real parcel/inspector id.

**`test_suite/`** (11 files + conftest, 2,709 lines) — **93 tests**, grouped by domain concern (registry, intake/feasibility, metering, permit fees, plan-check cycle, financing, change orders, construction sequencing, inspection slots, occupancy certificate, authorization).

## Coverage against the design indices

- Queue A: **20/20 difficulty instances x >=2 tests** (40 tests).
- Queue B: **53/53 non-stub corner instances x >=1 test** (53 tests). The 3 `excluded_because:` stubs were verified to cross-reference real difficulty instances and were not translated.
- Every test carries exactly one `Design: Difficulty/...` or `Design: Corner/...` line, all resolving to real `name:` entries; no untagged, dual-tagged, or stub-tagged tests.
- **176 PRD citations** all survive a literal whitespace-normalized grep of `PRD.md`. No instance failed the PRD-first filter, so nothing was skipped — no `skip`/`skipif`/`xfail` anywhere.

## Verification run

`python -m pytest test_suite --collect-only` -> **93 tests collected, 0 errors**; `test_helpers` imports cleanly; pyflakes is clean apart from the expected barrel-export re-exports; a static binder confirmed every `api.*` and helper call matches its signature; no "scaffold"/table references leaked into generated code.

Two notes on judgment calls: the certificate's `final_inspection_passed_at` is asserted as an *instant* equal to the qualifying slot's `slot_end` rather than as a literal string, since the PRD does not pin the serialization of that field (a PRD-only implementer could echo the input format); and the `impact_fee_threshold_at_750_sqft` / `school_fee` boundary pairs are asserted with the exact pre-computed cent values from the index, which I independently recomputed and confirmed.

## Step 7: Test-and-fix iteration loop — 2026-08-25T14:47:00.000Z

Verified: the rounds are genuinely independent (8 distinct checksums; the identical "116.4s" was display rounding of differing floats like 116.44018…, and per-test entries differ). The workload is per-test-boot-latency dominated, which is why concurrent rounds converge on the same wall time.

The loop exited on the first sweep — no failures to triage, so the diagnostic protocol (STEP 0–3) never engaged.

## Summary

**Iterations run:** 1 (one full 8-round parallel sweep). All 8 rounds green on the first pass, so no fix-and-rerun cycles were needed.

**Result:** 93/93 passed, 0 failed, 0 errors, 0 skipped — in every one of the 8 concurrent rounds.

**Tests deleted:** none. No test failed in any round, so no test was ever subjected to the STEP 1 coverage / unique-derivability filter. No PRD-silence or collapse-pattern deletions were warranted.

**Fixes applied to `test_helpers/`:** none — no fixture, factory, or role-header helper misbehaved.

**Fixes applied to `implementation/`:** none.

### Validation that the green sweep is real, not lucky or hollow

- **Not skip-masked.** 93 `def test_` functions defined, 93 collected, 93 `passed`, 0 `skipped`. The only `skip`/`xfail` grep hit across `test_suite/` and `test_helpers/` is the word "skips" inside a docstring at `test_08_construction_sequencing.py:180`, not a marker.
- **Not one run copied 8 ways.** All 8 `results.*.json` have distinct md5sums and distinct per-test entries.
- **Storage rules honored.** `common.py:105` defines a `Store` class of plain in-memory dicts (13 entity maps). No sqlite, no `json.dump`, no `open(`, no `/tmp`, no pickle/shelve/redis anywhere in the implementation.
- **No startup seeding.** The only module-level dicts are `ERROR_HTTP` (`common.py:29`) and `CERT_REQUIREMENTS` (`routes_build.py:22`), both static config rather than entity data.
- **Port discipline correct.** `app.py:56-57` reads `$PORT` (default 10000) and binds `0.0.0.0`.
- **No design-index leak.** Grepping the implementation for `scaffold`/`design_index`/`corner`/`difficulty`/`instance_id`/priority markers returns nothing.

One note carried over: `start.sh` guards its `pip install` behind an `import flask` check, which is what keeps 8 simultaneous reboots-per-test from thrashing on install contention. That guard is load-bearing for sweep stability — worth preserving if `requirements.txt` ever changes.

### Orchestrator-side transcript audit (independent of the Step 7 agent)

Parsed the Step 4 and Step 6 subagent `.output` JSONL transcripts, extracting only `tool_use` blocks' `input` fields and filtering for `SCAFFOLD_(DIFFICULTY|CORNER)_DESIGN`:

- Step 4 (doc-generator): **0** tool_use calls referencing either withheld design index.
- Step 6 (impl-generator): **0** tool_use calls referencing either withheld design index, and **0** referencing `test_suite/` or `test_helpers/`.

So the all-green first sweep is NOT explained by a design-index leak into the implementation. Step 8 is correctly skipped (empty `<step_7_diff>` = empty scope), but per prior-task experience a clean leak audit does not by itself prove the PRD is complete — Step 9 remains load-bearing and is being given an explicit note to that effect.

## Step 8: Finalize PRD — SKIPPED — 2026-08-25T14:47:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `<step_7_diff>` is empty, so Step 8 has no scope. The completeness question it would normally settle is deferred to Step 9's full PRD-vs-implementation scan.

## Step 9: Complete PRD — 2026-08-25T14:57:00.000Z

Done. `PRD_COMPLETED.md` written.

## Result

**Source vs output:** `PRD.md` 395 lines / 80,725 chars -> `PRD_COMPLETED.md` 395 lines / 86,245 chars (**+5,520 chars, ±0 lines**). All 24 changes are in-paragraph inserts/revisions on 23 existing lines; no new sections, no new paragraphs. Verified: §1–§5 intact, 51 endpoint rows, 53 error rows.

**Counts:** 22 ambiguity-pins, 2 mismatch-revisions.

**Cross-checks run first (found clean, no edit needed):** all 51 endpoint method/path pairs and all 51 RBAC role sets diffed programmatically against the `@bp`/`@authorize` decorators — exact match; all 6 calculation formulas, the 3 OCC guards, and the 53-entry error->HTTP map matched the PRD verbatim.

### Changes

- **§2.1 — insert — ambiguity** — whitespace-only `X-User-ID`/`X-User-Role` counts as empty -> `ERR_UNAUTHENTICATED` — `common.py:226`
- **§2.3 — insert — ambiguity** — `limit`/`offset` present but empty fall back to defaults — `common.py:393,401`
- **§2.3 — insert — ambiguity** — filters match by exact equality; empty-valued filter narrows nothing; unrecognised query params ignored — `routes_core.py:141-146`
- **§2.4 — insert — ambiguity** — `created_at` never ties (stamp pushed forward), so "oldest first" is a total order; a row's `version` moves only where stated (child creates don't touch parents) — `common.py:135-140,151-158`
- **§2.4 — revise — ambiguity** — `current_utc` echoed back verbatim, no normalization, sole field in the response; unparseable/absent `to_iso8601` -> `ERR_VALIDATION`; zoneless instant read as UTC *(flagged call #4)* — `routes_core.py:33-37`, `common.py:363-376`
- **§2.7 — insert — ambiguity** — the 9-rung ladder is authoritative over any §3 narrative recital order; §3 orderings bind only within a rung *(flagged call #1; resolves §3.2 `screening_id`-before-`INTAKE` and §3.8 identity-before-state)* — `routes_core.py:344-357`, `routes_build.py:281-288`
- **§2.7 — insert — ambiguity** — absent/empty/unparseable body = empty object, non-object body = `ERR_VALIDATION`; JSON `null` treated as omitted; free-text fields accept `""` *(flagged call #5)* — `common.py:244-270`
- **§2.10 — revise — MISMATCH** — prose said occupied-parcel windows need "more than two clear days"; the implementation's inclusive buffer formula accepts exactly two clear days. Revised to "at least two clear days / start >= 3 days after prior end" *(flagged call #2)* — `routes_build.py:130-131`
- **§3.1 — revise — ambiguity** — `slot_date` required + `YYYY-MM-DD` or `ERR_VALIDATION`; count spans all projects; reply unpaginated — `routes_core.py:156-175`
- **§3.2 — insert — ambiguity** — a screening runs from any lifecycle state and leaves the project row untouched — `routes_core.py:310-323`
- **§3.3 — revise — ambiguity** — new utility record also carries `override_decision` and `energized_on_date` null; no project-state gate on opening — `routes_permit.py:36-46`
- **§3.3 — insert — ambiguity** — `override_decision` is persisted on the record (null when absent) — `routes_permit.py:89`
- **§3.3 — insert — ambiguity** — a project with *no* submittal fails the `ERR_PERMIT_NOT_APPROVED` freshness check — `routes_permit.py:103-105`
- **§3.3 — insert — ambiguity** — metering reversal leaves `override_decision` standing — `services.py:153-160`
- **§3.4 — insert — ambiguity** — preparing a package has no project-state gate — `routes_permit.py:118-142`
- **§3.4 — insert — ambiguity** — `correction_items` sent with an `APPROVED` outcome is shape-checked but writes no rows — `routes_permit.py:196-224`
- **§3.6 — insert — ambiguity** — repricing is symmetric: `SHORTFALL -> COMMITTED` also fires on an *approval* whose recomputed gap is 0; other `financing_state` values untouched; no committed scenario = nothing to reprice — `services.py:144-147`
- **§3.6 — revise — MISMATCH** — void narrative put the `FINALED` gate before the change-order state check; implementation checks change-order state first — `routes_finance.py:256-262`
- **§3.6 — insert — ambiguity** — `decided_by_user_id` survives a void unchanged — `routes_finance.py:264-269`
- **§3.7 — insert — ambiguity** — phase creation has no lifecycle gate; `depends_on_phase_id` resolved by id alone, no same-project requirement — `routes_build.py:36-64`
- **§3.7 — revise — ambiguity** — `window_end_date < window_start_date` -> `ERR_VALIDATION` (422) on rung 6, before both state gates *(flagged call #3)* — `routes_build.py:95-100`
- **§3.8 — insert — ambiguity** — `slot_start`/`slot_end` stored and returned as raw client strings, zoneless read as UTC; booking has no phase/project state gate *(flagged call #6)* — `routes_build.py:204-254`
- **§3.8 — revise — ambiguity** — omitted `result_notes` is written as null (overwriting a prior PARTIAL's notes) — `routes_build.py:286,303`
- **§3.8 — insert — ambiguity** — segregation-of-duties is a rung-9 compliance check despite its 403, running after payload and appointment-state validation; scans other appointments in any status — `routes_build.py:288-299`

## Pipeline complete — 2026-08-25T14:58:00.000Z

Final state: 93/93 tests passing in all 8 parallel rounds (`results.1.json`..`results.8.json` all `passed=93, total=93, failed=0`). Deliverables: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/`, `test_suite/` (93 tests), `workspace/PRD.md`, `workspace/PRD_COMPLETED.md`, `workspace/implementation/` (10 files, 51 endpoints). `workspace/PRD_FINALIZED.md` absent by design (Step 8 skipped).
