# Worklog — task_2947_audio_post_production_sound_design

## Step 1: Create task directory — 2026-09-05T20:36:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2947_audio_post_production_sound_design` and its `workspace/` subdirectory. Index 2947 was pre-assigned by the orchestrating prompt; no scan of `./tasks/` was performed (concurrent pipelines on this host would collide on auto-allocated indices).

## Step 2: Generate scaffold — 2026-09-05T22:10:00.000Z

Step 2 complete. All three scaffold artifacts are written and lint-clean.

**Deliverables** (`/home/ubuntu/github/CodingPRD/tasks/task_2947_audio_post_production_sound_design/`)

| file | lines |
|---|---|
| `SCAFFOLD.yaml` | 2825 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1912 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4383 |

**§1.0–§1.7 surface (SCAFFOLD.yaml, `api_prefix: "/"`, `consistency_model: immediate`)**
- 14 entities: Project, PlatformSpec (immutable), MixStage, Mixer, VoiceTalent, LibraryAsset, StemPackage, MusicCue, AssetUsage (m:n junction), AdrSession, MixStageBooking, Deliverable, QcReport, ArchivePackage. Topology `graph`, state-machine shape `parallel`, role model `segregation_of_duties`, difficulty `expert_plus`.
- 9 state machines, 3 OCC concurrency rules (`booking-create-stale-project`, `deliverable-create-stale-project`, `cue-create-stale-stem-package`), 9 calculations (2 dual-variant: stage cost provisional/final, license risk intake/audit), 44 priority-ordered validations, 53 endpoints, 44 errors, 6 roles (FacilityAdmin, PostSupervisor, SoundEditor, Mixer `entity_backed`, QcOperator, ClientReviewer). Complexity layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation.
- One correction to §1.4/§1.6 this session: validation priority 25 (`ERR_UNLICENSED_MATERIAL_PRESENT`) was re-scoped to `POST /deliverables` only — on qc-submit/qc-evaluate/deliver/archive it was permanently shadowed by priority 16 (`ERR_PROJECT_FROZEN`), since any unlicensed usage forces posture RESTRICTED.

**§1.8** — 9 rule_ids × 2 instances (3 for boundary_precision_check) = **19 instances**, all arithmetic literals computed in code.

**§1.9** — **75 instances across all nine sections** (60 full `test_recipe`s + 15 `excluded_because` stubs, every stub citing a real §1.8 instance): entities 13, state_machines 16, calculations 13, validations 12, endpoints 6, errors 4, rbac 4, complexity_layers 6, consistency_model 1. All 44 error ids in the §1.6 catalog are triggered at least once across §1.8+§1.9; all three OCC rules, both dual-variant calculations, the SoD identity rule, the ledger role/ownership double gate and the pagination bounds are covered. Instance names are unique across both design files.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  §1.5 endpoints declared:    53
  §1.1 entities declared:     14
  §1.8 instances scanned:     19
  §1.9 instances scanned:     60
  Calls scanned (§1.8+§1.9):  912

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

`workspace/` and `worklog.md` were not touched; scratch stayed in the gitignored `.scratch/step2/`. No sibling task directory was read.

Orchestrator verification: all three files present (2825 / 1912 / 4383 lines). Difficulty-directive leak check — `grep "harder than expert" SCAFFOLD.yaml` returns nothing; the `scenario:` key contains only the verbatim scenario text starting at "2947.". No stripping needed.

## Step 3: Copy shared files — 2026-09-05T22:11:00.000Z

Copied `INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T22:24:00.000Z

PRD generated and verified at `/home/ubuntu/github/CodingPRD/tasks/task_2947_audio_post_production_sound_design/workspace/PRD.md` — 444 lines / ~100 KB, ending at a complete §5 Error Code Catalogue.

**Sections written**

- **§1 Introduction** — 3 paragraphs (facility pain-point angle, the three pervading concerns, logical-clock/root-mount note).
- **§2 Global Specifications** — 11 domain-derived subsections: 2.1 RBAC & identity, 2.2 API Response Structure (pasted byte-identical from `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Logical Clock & Instant Formats, 2.5 Resource Identity / Revision Counters / Immutable Records, 2.6 Path Resolution & Reference Checking Order, 2.7 Stale-View Protection (OCC), 2.8 Money/Hours/Rounding Discipline, 2.9 Project Posture (derived write gate), 2.10 The Invalidation Cascade (shared rule R-STALE, 3 hops), 2.11 Validation Precedence (all 44 rungs as an ordered ladder with error id + status + scope).
- **§3 Business Logic** — 8 lifecycle-grouped subsections: 3.1 facility configuration, 3.2 project intake + the two independent status dimensions, 3.3 stem packages / music cues / conform, 3.4 licensed material (clearance, dual risk scores, revocation cascade), 3.5 ADR scheduling, 3.6 mix stage (reservation, occupancy, stage-hour ledger, PROVISIONAL vs FINAL cost), 3.7 deliverable prep + QC loop, 3.8 delivery / 9-step billing roll-up / archival seal.
- **§4** — 1 status-code paragraph + 53-row table, exactly 4 columns.
- **§5** — 44-row table, exactly 2 columns.

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 121 required, 121 present, 0 missing
- endpoints[].request_body: 70 required, 70 present, 0 missing
- endpoints[].query_params: 15 required, 15 present, 0 missing
- endpoints[].output (ledger/clock payload keys): 22 required, 22 present, 0 missing
- concurrency_rules[].occ_field: 2 required, 2 present, 0 missing
Status: PASS   (verified by strict exact-backtick-token match, not substring)
```

```
Rule coverage check:
- validations[] with priority: 44 checked, 44 expressed in prose (ordered ladder §2.11), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 40 checked, 40 fully expressed, 0 missing
- calculations[]: 9 checked (2 dual-variant), 9 fully expressed with pinned step order, constants in business context, forbidden alternatives named, 0 missing
- validations[] conditions: 44 checked, 44 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 53 endpoints checked, all side effects + all applies_to sets expressed, 0 missing
- entities[].fields[] structured content: 121 checked, defaults/initials/nullability/enum sets/precision reconstructible, 0 missing
- sibling-branch symmetry: 11 groups checked (2 lock branches, 2 conform sources, 2 qc-submit sources, 2 release sources, 2 supersede sources, 2 sign-off states, 3 cancel branches, 2 invalidate sources, PROVISIONAL/FINAL, INTAKE_SNAPSHOT/DELIVERY_AUDIT, discount/surcharge), 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1001
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Coverage audit notes / judgement calls**

- Every one of the 44 `errors[].id` is mentioned in §2 or §3 prose, not only in the §5 table (verified mechanically).
- §2.2 diffs clean against the canonical source (only a trailing blank separator line added).
- Sort order follows the scaffold rather than the skill's generic default: top-level lists are `created_at` **descending** ("newest first" per each endpoint description), music-cues are `cue_number` then `created_at` ascending, qc-reports are `round` then `created_at` ascending, archive-packages ascending. No tie-breaker was invented.
- Two scaffold preconditions have no error id assigned anywhere in §1.4/§1.6 — the "logical clock at or past `window_start_utc`" guards on ADR record and on the `TALENT_NO_SHOW` cancel. I attributed both to `ERR_INVALID_STATE` (409, the generic no-transition-for-this-trigger rung), and flagged it here in case Step 6/7 wants a different mapping.
- `ERR_UNLICENSED_MATERIAL_PRESENT` vs `ERR_PROJECT_FROZEN` shadowing is spelled out explicitly in §2.11 and §3.7/§3.8: the `unlicensed_usage_count == 0` precondition at deliver surfaces as `ERR_PROJECT_FROZEN` (posture `RESTRICTED`), while `ERR_UNLICENSED_MATERIAL_PRESENT` is reachable only at deliverable preparation.
- Rungs 24 vs 42 (422 before 409) and rungs 25 vs 16 (scoping to avoid permanent shadowing) are both called out in prose as deliberate ordering, per the scaffold notes.
- Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced; no sibling task directory was read. Scratch confined to `.scratch/step4/`; `worklog.md` and all `SCAFFOLD*.yaml` untouched.

Orchestrator truncation check (known doc-generator failure mode): `tail -15` ends mid-table? No — the file ends at the final `ERR_ALREADY_SIGNED_OFF` row of the complete §5 table, and `grep "^#"` shows all of §1–§5 including §2.1–§2.11 and §3.1–§3.8 present. Not truncated; no regeneration needed.

## Step 6: Generate implementation — 2026-09-05T23:05:00.000Z

(Steps 5 and 6 were launched concurrently in a single assistant message, so the implementation generator never saw `test_suite/`. Step 6 returned first; Step 5's entry follows below.)

**Step 6 complete.** `workspace/implementation/` holds a 17-file Flask app (2875 lines) that boots clean and empty on every `start.sh` invocation.

### Modules written (line counts)

| Module | Lines | Responsibility |
|---|---|---|
| `app.py` | 63 | app factory, blueprint wiring, `ApiError`/`HTTPException`/`Exception` handlers, `strict_slashes = False`, `threaded=True` |
| `errors.py` | 108 | all 44 PRD §5 error ids → HTTP status + default message |
| `clock.py` | 38 | logical clock (default `2026-08-01T00:00:00Z`), whole-second `Z` and 3-fractional-digit formatters |
| `db.py` | 73 | `Store` of 14 empty dicts, `new_id`/`new_record`/`touch`, deterministic `(created_at, _seq)` sort key |
| `response.py` | 56 | success/list/error envelopes, `req_` + 20-char id, pagination window |
| `validation.py` | 237 | enum vocabularies, body/type/range/instant coercion, pagination bounds, query filters |
| `calc.py` | 236 | all 9 calculations incl. both dual variants, `Decimal` + `ROUND_HALF_UP`, integer-second math |
| `derive.py` | 189 | posture derivation, project recompute (ledger, counts, roll-up), the §2.10 cascade, pipeline advance |
| `serialize.py` | 306 | explicit per-entity payloads; immutable entities omit `updated_at`/`version`; ledger emits exactly 21 fields |
| `middleware.py` | 122 | rungs 1–11 and the posture/archived/picture-lock gates (16–18) |
| `routes/facility.py` | 239 | clock, specs, stages, mixers, talents, assets, revoke cascade |
| `routes/projects.py` | 203 | create/read/list, picture-lock, break-picture-lock, ledger, archive packages |
| `routes/stems.py` | 272 | stem packages, music cues, conform, asset usages |
| `routes/adr.py` | 184 | ADR create/confirm/record/cancel |
| `routes/bookings.py` | 282 | booking create/confirm/start/complete/client-signoff/release |
| `routes/deliverables.py` | 256 | deliverable create, qc-submit, qc-evaluate (201), qc-reports, remediate, deliver |
| `start.sh` / `requirements.txt` | 10 / 1 | guarded `pip install`, `exec python3 app.py` on `$PORT` |

### Coverage, verified mechanically
- **Endpoints: 53/53, exact one-to-one.** A diff of Flask's `url_map` against the PRD §4 table reported zero missing and zero extra. (The PRD declares no collection-list route for platform-specs, mix-stages, mixers or voice-talents; those correctly 405 → `ERR_INVALID_REQUEST`.)
- **Errors: 44/44.** Every id in the PRD appears in `ERROR_STATUS`, every HTTP status matches the §5 table row-for-row, and every id is actually raised somewhere in the code (no dead entries).
- **Validations:** the 44 rungs are evaluated in ladder order per endpoint, rung number beating status severity — notably rung 24 (`ERR_MIXER_NOT_CERTIFIED`, 422) before rung 42 (`ERR_STAGE_HOURS_EXCEEDED`, 409), and rung 20 → 25 → 28 → 29 on deliverable creation.
- **Posture gate:** `gate_posture` appears at exactly the 14 operations §2.9 names in its FROZEN list; `RESTRICTED` blocks only qc-submit, qc-evaluate, deliver, archive.
- **Calculations:** every PRD worked example reproduces exactly — conform `4.74`/`7110` (3×95 s) and `1.50`/`2250` (1×90 s); licence accrual `100000` (RM) and `17890` (RF) over 100 s; risk scores intake `20.00` / audit `65.00`; ADR `54000` (union 45 min and 15 min, min-call 60) and `27000` (non-union 45 min); provisional `360000` / `576000` RUSH / `450000` EXPEDITED / `240000` on the 2 h floor; final `3.25` billable, `0.25` overtime, `405000`, and `2.00`/`240000` at the same instant; billing roll-up `759050` STANDARD and `910860` RUSH.
- **Cascade:** the depth-4 chain was exercised from both origins (asset revoke and break-picture-lock) — package → `STALE`, deliverable → `INVALIDATED`/`STEM_STALE`, booking → `RELEASED`/`DELIVERABLE_INVALIDATED`, fees reversed to 0, `stage_hours_available` returned to its exact pre-booking value with the three-term ledger identity holding.

### Smoke test: PASS
Two suites on a high random port, killed by exact pid each time (no broad pkill). Suite 1 (~115 assertions): envelope shape, auth ladder, full happy path through picture-lock → cues → conform → usages → booking → complete → deliverable → QC reject → remediate → pass → deliver → archive, plus OCC 412s, changeover-buffer boundary, segregation of duties, post-archival blocking, client-reviewer ownership. Suite 2 (~45 assertions): both cascades, re-lock/re-conform recovery to `OPEN`, empty stem set, pagination bounds. **All assertions pass** (the only two failures encountered were bugs in my own smoke script — a wrong key and an expectation of `PICTURE_CHANGED` where the PRD says `PICTURE_LOCK_BROKEN`; the implementation was right both times).

**No-seed / fresh-boot verified:** 5 consecutive kill-and-relaunch cycles each reported `total_count = 0` at boot and `1` after one create; `find` showed zero files written to disk during the boots, and a grep found no sqlite/pickle/shelve/`json.dump`/`open(...,'w')`/`/tmp` usage anywhere.

### PRD ambiguities resolved
1. **Project version bumps** — exactly one per request that mutates the project row. break-picture-lock is `+1` total (§3.2 explicit) even though it stales packages; a cue revision that stales its package is `+1`; asset revoke is `+1` per affected project. No bump for stem-package create, ADR create/record, `NO_SHOW` or `PROPOSED` cancel, booking start, client-signoff, qc-submit, qc-evaluate or remediate.
2. **Stem-package version bumps exactly once per cue creation**, even when that cue stales the package — implemented by splitting `cascade_from_stale_package` (hops B+C only) out of `mark_stem_package_stale`.
3. **Any cue added to a `CONFORMED` package stales it**, not just a superseding one, read from "A cue added to a `DRAFT` or already-`STALE` package changes no status."
4. **Facility reads with no dedicated 404 code** (platform-specs, mix-stages, mixers, voice-talents, asset-usages) answer `ERR_REFERENCE_NOT_FOUND` 404; the reads that do have spine codes use them.
5. **Uniqueness collisions** (`room_code`, `asset_code`, `reel_label` per project) → `ERR_INVALID_REQUEST` 400; no dedicated code exists.
6. **client-signoff on a non-`REMOTE` booking** → `ERR_INVALID_STATE` 409 (§3.6 states the requirement but names no code).
7. **`ERR_ALREADY_ARCHIVED` (rung 43) is unreachable** — rung 17 `ERR_PROJECT_ARCHIVED` fires first on a second archival. Implemented in ladder order anyway.
8. **Rung 29 is unreachable on asset-usage creation** (that request names no project); implemented on deliverable creation where it bites.
9. **Body FK semantics:** present but unresolvable → rung 9 (404); absent, null, non-string or empty → rung 12 (400).
10. **Risk scores recomputed only on asset-usage creation and asset revocation**, so the clock-dependent near-expiry term cannot drift on unrelated writes.
11. **List filters** with unrecognised values act as plain predicates (empty result, not 400) — rung 12 is scoped to request bodies.
12. **Date-only instants accepted** as midnight UTC as a hedge; anything else malformed → 400.
13. **Rung 17 (`ARCHIVED`) also applied** to picture-lock, break-picture-lock and stem-package creation, reading "any write beneath that project" literally, even though those three are outside the §2.9 posture list.

`.scratch/step6/` removed (siblings `step2`, `step4`, `step5`, `step7` untouched); `__pycache__` cleaned; `worklog.md`, `PRD.md`, `INSTRUCTION.md` and `SCAFFOLD.yaml` were read only, never written.

## Step 5: Generate unit tests — 2026-09-05T23:26:00.000Z

Step 5 is complete. All test infrastructure and test cases are written at the task root, verified, and the scratch dir is cleaned up.

**Files written (line counts)**

`test_helpers/`: `__init__.py` 16, `api_client.py` 345, `api_errors.py` 101, `assertions.py` 236, `constants.py` 181, `factories.py` 340, `fixtures.py` 449, `test_users.py` 85, `types.py` 265.

`test_suite/`: `conftest.py` 23, `test_01_stage_bookings_and_hour_ledger.py` 319, `test_02_licensing_exposure_and_revocation.py` 273, `test_03_conform_totals_and_billing_rollup.py` 201, `test_04_quality_control_loop.py` 286, `test_05_picture_lock_cycle_and_cascade.py` 146, `test_06_adr_scheduling_capacity.py` 281, `test_07_validation_precedence_pairs.py` 185, `test_08_entity_registry_and_reads.py` 493, `test_09_state_machine_transitions.py` 524, `test_10_pricing_and_scoring_calculations.py` 455, `test_11_validation_guards_and_precedence.py` 643, `test_12_endpoint_surface_and_actions.py` 344, `test_13_error_gates_and_pagination.py` 305, `test_14_role_and_ownership_gates.py` 281, `test_15_stale_views_and_derived_reconciliation.py` 334. Total 7111 lines across both dirs.

**Coverage**

- Queue A (difficulty): 19/19 instances, 38 tests (exactly 2 per instance), files 01–07.
- Queue B (corner): 60/60 non-stub instances, 60 tests, one per instance — entities 13, state_machines 11, calculations 9, validations 9, endpoints 5, errors 4, rbac 4, complexity_layers 4, consistency_model 1 (files 08–15).
- 98 tests, 98 `Design:` tags, one per test.
- 15 `excluded_because:` corner stubs not translated; every stub's `difficulty_instance` cross-reference resolves to a real non-stub difficulty instance.

**Verification passes** (scripted, then `rm -rf .scratch/step5` only)

- Design-citation pass: 0 dangling / dual / missing tags; every tag's section or rule_id matches the source yaml; no instance covered twice.
- PRD-citation pass: all 98 quoted citations found verbatim in `workspace/PRD.md` after whitespace normalisation, and every `PRD §X.Y` label matches the section the quote actually lives in. Two defects were found and fixed: a dropped `**` in the §3.6 "**Closing** the stage…" quote in test_04, and a `§3.9` label on a §3.8 archival sentence in test_09.
- Static pass: `py_compile` clean on all 25 files; `pyflakes` clean except the intentional `# noqa: F401` fixture re-exports in `conftest.py` and two unused header constants in `fixtures.py`.
- Symbol pass: every `world.*`, `api.*` and `f.*` call site resolves to a real method in `World` / `ApiClient` / `factories`.
- Placement: `test_helpers/` and `test_suite/` exist at the task root; `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/` (never read). No server started, no `pkill`, `worklog.md` / `PRD.md` / `SCAFFOLD*.yaml` untouched, sibling `.scratch/step2|step4|step7` intact.

**Instances skipped for the PRD-first filter: none.** Every non-stub instance had verbatim PRD coverage that uniquely derives its asserted outcome.

**Design-index vs PRD divergences (test follows the PRD in each case)**

1. `state_machines/archive_seal_retires_stems_and_locks_the_project_out` asserts `ERR_ALREADY_ARCHIVED` for a second seal. PRD §3.8 line 333 says every post-seal write "including any further archival attempt" is `ERR_PROJECT_ARCHIVED`, and rung 17 outranks rung 43, so test_09 asserts `ERR_PROJECT_ARCHIVED`. The PRD itself is in mild tension here: the archival precondition list still names `ERR_ALREADY_ARCHIVED` for "no archive package may already exist".
2. `state_machines/adr_cancel_client_request_leaves_both_overlap_and_cap_sets` proposes a replacement 09:30–10:30 session that strictly overlaps a still-`CONFIRMED` 09:00–10:00 session; test_09 uses 10:30–11:30 so the cancellation, not the overlap guard, is what is observed.
3. Several difficulty asserts spell the QC verdict `PASSED` / `REJECTED`; PRD §3.7 declares `PASS` | `FAIL`, so all tests use `QC_VERDICT_PASS` / `QC_VERDICT_FAIL`.
4. Two corner instances assert `active_cue_count` on a stem package; that field does not exist in the PRD (`cue_count` exists but is pinned only at conform, staying 0 on a DRAFT package). test_15 substitutes the PRD-declared `GET /stem-packages/{id}/music-cues?status=ACTIVE` listing (total_count) plus the `SUPERSEDED` listing for the same claim.

No other PRD gaps surfaced: the pagination contract, all 43 precedence rungs cited, the nine-step billing roll-up, the hour-ledger identity and the two OCC parents were all uniquely derivable from the PRD text.

Orchestrator verification: `test_helpers/` (2018 lines) and `test_suite/` (5093 lines, 16 files) both exist at the TASK ROOT; `find workspace/ -name test_suite -o -name test_helpers` returns nothing, so the known "test dirs written under workspace/" failure did not occur. 98 `Design:` tags across test_suite; zero `pytest.mark.skip` / `xfail` occurrences.

## Step 7: Run tests and iterate — 2026-09-06T00:05:00.000Z

All 8 rounds green at 98/98. Done.

## Summary

**Iterations run:** 2 (iteration 1 diagnosis, iteration 2 verification).

**Tests deleted:** None. Both failures were test-artifact assertion defects that PRD verbatim-covers, so both were fixed rather than removed.

**Fixes applied to `test_suite/`:**

1. `test_01_stage_bookings_and_hour_ledger.py` → `TestProvisionalAndFinalStageCost::test_completion_charges_the_quarter_hour_overrun_at_time_and_a_half` — final assertion demanded `pipeline_stage == "QC"` after closing a `FINAL_MIX` booking, but the test's project (`world.locked_project`) never conforms a stem package, so it sits at `EDITORIAL`, never `PREMIX`/`FINAL_MIX`. PRD §3.6 gates the advance on "the project sits at `FINAL_MIX`", and §3.2 pins the consequence verbatim: "if the triggering event occurs while the project sits at some other stage, `pipeline_stage` is simply left untouched, with no skip and no regression." Changed the expectation to `"EDITORIAL"` with the two PRD quotes inline — this makes the test *more* faithful, since it now asserts the no-skip rule. The implementation was correct.

2. `test_11_validation_guards_and_precedence.py` → `TestArchiveGatesCheckDeliveredBeforeStillOpen::test_the_delivery_gate_answers_first_and_the_open_gate_answers_next` — asserted an exact `ERR_NO_DELIVERED_DELIVERABLE` on an archival attempt against a project still at `pipeline_stage == "QC"`. Two independent §3.8 preconditions fail simultaneously there, and PRD assigns no error code to the first one ("The project's `pipeline_stage` must be `DELIVERED`"), so a faithful implementer may route it through rung 19 `ERR_INVALID_STATE` (which by the §2.11 rung ordering then wins over rung 40) — which is what this implementation does. Not uniquely derivable → ERROR-PRECEDENCE relaxation to `validate_error_is_one_of([ERR_NO_DELIVERED_DELIVERABLE, ERR_INVALID_STATE])`, the one relaxation the cardinal rules permit. Added the `validate_error_is_one_of` and `ERR_INVALID_STATE` imports. Every other assertion in the test (the later `ERR_DELIVERABLE_STILL_OPEN` at rung 41, `total_count == 0` on the archive-package list, package still `CONFORMED`) was left exactly as it was and now passes.

Worth flagging for the record: the PRD is arguably self-inconsistent here. If the pipeline-stage precondition is an `ERR_INVALID_STATE` rung-19 gate, rung 40 becomes permanently unreachable — `pipeline_stage == DELIVERED` is attainable only by delivering a deliverable, and `DELIVERED` is a terminal deliverable status. That is precisely the "permanently shadowed rung" hazard §2.11 warns about and scopes rung 25 to avoid. The relaxation accepts either reading rather than legislating one.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:** None. No implementation defect was found; both failures traced to the test layer.

**Final sweep evidence** (all 8 rounds, `results.1.json` … `results.8.json`):

| Round | Passed / Total | Failed | Errors |
| --- | --- | --- | --- |
| 1 | 98 / 98 | 0 | 0 |
| 2 | 98 / 98 | 0 | 0 |
| 3 | 98 / 98 | 0 | 0 |
| 4 | 98 / 98 | 0 | 0 |
| 5 | 98 / 98 | 0 | 0 |
| 6 | 98 / 98 | 0 | 0 |
| 7 | 98 / 98 | 0 | 0 |
| 8 | 98 / 98 | 0 | 0 |

Iteration 1 was already highly stable (96/98 in all 8 rounds, identical failure pair every round), so there was no flakiness signal to chase — no load-induced or infrastructure failures were observed in either sweep. `worklog.md` was not touched.

Orchestrator verification: independently re-read all 8 `results.$i.json` — 8 files present, each `passed=98 total=98 failed=0 errors=0`. No `pytest.mark.skip` / `xfail` anywhere in `test_suite/`. Step 8 is NOT skipped: the skip condition requires zero fixes in every layer, and Step 7 applied 2 `test_suite/` fixes, both of which mark genuine PRD under-determination (the pipeline-stage-advance no-op branch, and the missing error code for the archival `pipeline_stage == DELIVERED` precondition).

## Step 8: Finalize PRD — 2026-09-06T00:12:00.000Z

Done. PRD_FINALIZED.md created with a single surgical edit.

## Summary

**Line counts:** PRD.md 444 lines / 99,935 bytes → PRD_FINALIZED.md 444 lines / 100,324 bytes. Line delta 0 (0.00%); byte delta +389 (+0.39%). 27 `^#` headings in both; file ends at the `ERR_ALREADY_SIGNED_OFF` row of the §5 table.

**Changes**

- §3.8 (Delivery, the Billing Roll-Up and the Archival Seal) — revise — the first of the five archival preconditions ("The project's `pipeline_stage` must be `DELIVERED`") had no error code assigned; pinned it to rung 19 `ERR_INVALID_STATE`, noted that it therefore answers ahead of the rung-40/41 deliverable gates on a request that fails both, and noted that an already-`ARCHIVED` project is intercepted earlier by rung 17 `ERR_PROJECT_ARCHIVED` — `implementation/routes/projects.py:155-167` (gate order: `gate_posture` → `gate_archived` → `pipeline_stage != "DELIVERED"` → `ERR_INVALID_STATE`, then delivered/open/already-archived), with `implementation/middleware.py:113-116`.

**Step 7 item 1 (FINAL_MIX close on an `EDITORIAL` project) — no PRD edit.** PRD already determines this verbatim in two places: §3.6 "When the closed booking's `booking_type` is `FINAL_MIX` **and the project sits at `FINAL_MIX`**, `pipeline_stage` advances to `QC`", and §3.2's no-skip rule. `derive.advance_pipeline` (`implementation/derive.py:135-141`) is a pure guarded advance, and all six callsites pass an explicit `from_stage`. Pure test-artifact bug; nothing to pin.

**Per-edit pre-edit search log**

Edit 1 (§3.8 archival stage gate):
- (a) Subject: the archival precondition set — specifically which error code the `pipeline_stage != DELIVERED` check emits and where it sits relative to the other archival rungs and the project-wide gates.
- (b) Paths enumerated / read: `implementation/routes/projects.py:146-191` (the whole `create_archive_package` handler, including body validation order and the delivered / still-open / already-exists sequence); `implementation/middleware.py:103-116` (`gate_posture`, `gate_archived` — established that an `ARCHIVED` project short-circuits with `ERR_PROJECT_ARCHIVED` before the new sentence's rung-19 path can be reached); `implementation/derive.py:135-141` plus all six `advance_pipeline` callsites (`routes/projects.py:104,188`, `routes/deliverables.py:253`, `routes/stems.py:182`, `routes/bookings.py:184,237`) to confirm no other endpoint reports a `pipeline_stage` precondition as `ERR_INVALID_STATE`, so the new clause stays scoped to archival; `derive.OPEN_DELIVERABLE_STATUSES` usage at `routes/projects.py:164`; grepped PRD for every other mention of the archival codes (§2.11 rungs 40/41/43, §4 endpoint table line 361, §5 catalogue) to confirm no other passage contradicts the new clause.
- (c) Wording adjustments made: (i) scoped the clause to "a project sitting at an **earlier** stage" rather than "any stage other than `DELIVERED`", because `ARCHIVED` is handled by rung 17, not rung 19; (ii) added the explicit rung-17 parenthetical so the `ARCHIVED` case is not mis-described; (iii) phrased the precedence as "answers ahead of the deliverable gates at rungs 40 and 41 **when those would fail on the same request**" rather than declaring rungs 40/41 unreachable — the implementation does still evaluate both, and asserting permanent shadowing would be a claim the code does not exhibit; (iv) deliberately said nothing about rung 43 / `ERR_ALREADY_ARCHIVED`, which Step 7 never exercised and which the pre-existing §3.8 and §2.11 text already covers.

Orchestrator verification: `PRD_FINALIZED.md` exists, differs from `PRD.md` (+389 bytes), retains all 27 headings, and ends at the complete §5 table — not truncated. Note per the skill: a byte-identical PRD_FINALIZED.md would have been legitimate here since Step 7 made no implementation fixes, but the archival-gate silence was a real one and got pinned.

## Step 9: Complete PRD — 2026-09-06T00:40:00.000Z

Step 9 was run as THREE SEQUENTIAL module-partitioned passes over one shared `workspace/PRD_COMPLETED.md` (pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were forbidden to re-copy). Partition: pass 1 = the global/cross-cutting modules, pass 2 = calc/derive + facility/projects/stems routes, pass 3 = adr/bookings/deliverables routes. Total: **47 pins/revisions, 444 lines, 100,324 → 119,296 chars (+18,972, +18.9%)**, all in-paragraph, zero new sections.

### Pass 1 of 3 — global/cross-cutting modules (app.py, errors.py, clock.py, db.py, response.py, validation.py, middleware.py, serialize.py)

Pass 1 created `workspace/PRD_COMPLETED.md` via `cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md`, then edited only that copy.

- Source `PRD_FINALIZED.md`: 444 lines / 100,324 chars. After pass 1: 444 lines / 107,858 chars (**+7,534 chars**, +0 lines).
- Counts: **14 ambiguity-pins, 1 mismatch-revision**.

- §2.1 — insert — ambiguity — a whitespace-only `X-User-ID` counts as empty (401); role names matched exactly/case-sensitively; a non-blank user id is otherwise accepted verbatim — middleware.py:14-19
- §2.2 — revise — ambiguity — `api_request_id` is `req_` plus exactly 20 chars from `A`–`Z`/`0`–`9` (24 chars, no lower case) — response.py:10-15
- §2.2 — revise — ambiguity — pagination keys appear on list responses only; every other 2xx and every error carries exactly `api_request_id` + `api_request_timestamp` — response.py:18-50
- §2.3 — insert — ambiguity — window past end of set → empty `data`, full `total_count`, `has_more` false; list filters are exact case-sensitive raw-string compares, an out-of-vocabulary or empty filter value matches nothing rather than erroring, repeated params read first occurrence — response.py:39,53-56 / validation.py:233-237
- §2.3 — insert — ambiguity — ties on the leading sort key are broken by an internal monotonic creation-sequence number (descending for newest-first, ascending for the chronologies); never serialised — db.py:31-33,64-73
- §2.4 — insert — ambiguity — accepted instant input grammar (trimmed, `T`/`t`/space separator, `Z`/`z`/`±HH:MM`/`±HHMM` offsets normalised, any-width fractional retained at microsecond resolution, bare `YYYY-MM-DD` = midnight UTC; missing designator/non-string/out-of-range → schema violation) and output **truncates** fractional seconds — validation.py:55-106, clock.py:27-32
- §2.5 — revise ×2 — ambiguity — `id` is a random v4 UUID in canonical lower-case 8-4-4-4-12 form (36 chars); `updated_at` equals `created_at` at creation — db.py:39-55
- §2.6 — insert — ambiguity ×3 + **mismatch** — non-spine addressable records (`/platform-specs`, `/mix-stages`, `/mixers`, `/voice-talents`, `/asset-usages`) 404 as `ERR_REFERENCE_NOT_FOUND`; trailing slash tolerated; unrouted path → `ERR_REFERENCE_NOT_FOUND` 404; **mismatch fixed:** a declared path with an undeclared method answers `ERR_INVALID_REQUEST` with HTTP **405**, the one case where §5's 400 for that id does not apply — middleware.py:66-72, app.py:24,41-50
- §2.6 — insert — ambiguity — body reference resolution inspects only a present non-empty string; absent/null/wrong-type/`""` falls through to the schema rung (`ERR_INVALID_REQUEST`) despite rung 9 preceding rung 12 — middleware.py:76-87
- §2.8 — insert — ambiguity — decimals and cents are JSON numbers not strings, trailing zeros not preserved (2.00 → `2.0`), unpopulated decimals `null`, inbound decimals quantised half-up to 2 dp after range bounds are checked against the raw value — serialize.py:11-15, validation.py:143-160
- §2.11 rung 12 — insert — ambiguity — explicit `null` treated as absent; `Content-Type` not consulted; absent/zero-length body = `{}`; non-object body rejected; undeclared fields ignored; strict typing (integer fields reject `90.0`/`"90"`, decimals reject numeric strings, booleans/numbers not interchangeable, string min-length, array type/min-items) — validation.py:65-74,109-206
- §3.1 — revise — ambiguity — `min_call_minutes` is ignored only in cost math for `NON_UNION` talent; it is still stored (default 60) and returned in the payload — serialize.py:71-80
- §3.2 — insert — ambiguity — the project resource omits `conform_fee_total_cents` and all four roll-up intermediates; those exist only on the ledger read — serialize.py:99-127 vs 282-306
- §3.8 — insert — ambiguity — the ledger field list is exhaustive; it is a computed projection with no `id`, `created_at`, `updated_at` or `version` — serialize.py:282-306

Verification (all passed): 444 lines / 107,858 chars; `tail -3` ends at `ERR_ALREADY_SIGNED_OFF`; `grep -c "^#"` = 27. Cross-checks: all 44 error ids and statuses in §5 match `errors.py` exactly; every member of all 23 enum vocabularies in `validation.py` appears in the PRD; every field name emitted by `serialize.py` is documented.

### Pass 2 of 3 — computation/derivation + facility/projects/stems routes (calc.py, derive.py, routes/facility.py, routes/projects.py, routes/stems.py)

- Line count on exit: 444 (unchanged). Chars on entry 107,858 → on exit 115,589. **+7,731 chars.**
- Counts: **14 ambiguity-pins, 7 mismatch-revisions** (21 changes).

- §2.8 — insert — ambiguity — every duration is the whole-second difference of its two instants (microseconds truncated toward zero) before division into minutes/hours — calc.py:68
- §2.9 — insert — ambiguity — the FROZEN child-write list is exhaustive; stem-package creation and asset-usage creation carry no posture gate — derive.py:23, routes/stems.py:34,201
- §2.10 — insert — ambiguity — a cascade bumps each affected **project** row exactly once per request (not once per stale package); child rows bump individually — routes/projects.py:133-134, routes/stems.py:131-132, routes/facility.py:236-237
- §2.11 rung 12 — insert — ambiguity — the three uniqueness constraints (`room_code`, `asset_code`, per-project `reel_label`) report `ERR_INVALID_REQUEST` 400, not a conflict code — routes/facility.py:72,152, routes/stems.py:33
- §2.11 rung 29 — revise — mismatch — scoped `ERR_CROSS_PROJECT_REFERENCE` to deliverable creation only — routes/stems.py:189-245 (only raise site is routes/deliverables.py:44)
- §3.1 — revise — mismatch — mixer `max_daily_hours` minimum is 0.01 as supplied (bound checked pre-quantisation) — routes/facility.py:104
- §3.1 — revise — mismatch — `daily_cap_minutes` and `min_call_minutes` are whole-minute **integers** — routes/facility.py:129-132
- §3.2 — revise — mismatch — project `stage_hours_authorized` minimum is 0.01 as supplied — routes/projects.py:24
- §3.2 — insert — ambiguity — `picture_lock_note` is 0–2000 chars, validated then discarded (never persisted or returned) — routes/projects.py:94
- §3.2 — insert — ambiguity — `break_reason` likewise validated then discarded; a non-`LOCKED` picture reports `ERR_INVALID_STATE` — routes/projects.py:118,124
- §3.3 — insert — ambiguity — `composer_delivery_ref` is 0–200 chars — routes/stems.py:90
- §3.3 — insert — ambiguity — cue creation bumps the package `version` by exactly 1 **even when** the same request stales it; the cascade adds no second bump — routes/stems.py:116-124
- §3.3 — insert — ambiguity — a cue on a DRAFT/STALE package leaves the project row untouched — routes/stems.py:122-132
- §3.3 — insert — ambiguity — `cue_number` ordering is a case-sensitive string comparison, so `"10M1"` precedes `"2M1"` — routes/stems.py:147
- §3.4 — revise — mismatch — deleted the claimed `ERR_CROSS_PROJECT_REFERENCE` rejection on asset-usage creation (unimplementable: no project reference in the body); pinned the archival gate as the only project-level gate — routes/stems.py:189-201
- §3.4 — insert — ambiguity — both licence-risk scores refresh on exactly two events (usage creation, asset revocation) and no others — derive.py:73-75,122-128
- §3.4 — insert — ambiguity — revocation is a facility-level write with no project gate, reaching FROZEN and ARCHIVED projects; a second revoke reports `ERR_INVALID_STATE` — routes/facility.py:194-202
- §3.5 — revise — mismatch — `scheduled_minutes` is whole-seconds/60 rounded half up to 2 dp, not "whole minutes" (2730 s → 45.50) — calc.py:111
- §3.6 — revise — mismatch — `elapsed_hours` comes from the whole-second difference, and a negative elapsed (clock moved backwards) is clamped to zero — calc.py:139-141
- §3.8 — insert — ambiguity — `archived_stem_package_ids` ties broken by insertion sequence — routes/projects.py:169
- §3.8 — insert — ambiguity — retiring the conformed packages drops their `conform_fee_cents` and their cleared usages' `accrued_fee_cents` out of the roll-up, so the seal normally lowers `billing_total_cents` in the same request — routes/projects.py:185-189, derive.py:107-117

Confirmations: the file was **not** re-copied; pass 1's edits spot-verified present (6 distinctive markers). 444 lines / 115,589 chars, 27 headings, tail intact.

### Pass 3 of 3 — ADR/booking/deliverable routes (routes/adr.py, routes/bookings.py, routes/deliverables.py)

- 444 lines / **119,296 chars** (entry 115,589 → **+3,707 chars**), 27 headings, tail still ends at the `ERR_ALREADY_SIGNED_OFF` row.
- Counts: **19 ambiguity-pins, 1 mismatch-revision** (20 changes).

- §3.5 — revise — ambiguity — talent overlap set is facility-wide, not project-scoped — routes/adr.py:23,49
- §3.5 — revise — ambiguity — daily-cap set is facility-wide, keyed on the requested `window_start_utc`'s UTC day; a total exactly **on** the cap is accepted (strict excess only) — routes/adr.py:56-65
- §3.5 — insert — ambiguity — ADR scheduling leaves the project row untouched — routes/adr.py:81-82
- §3.5 — insert — ambiguity — `lines_recorded` is a required integer of at least 0 — routes/adr.py:137
- §3.5 — insert — ambiguity — recording writes only the session row — routes/adr.py:148-151
- §3.5 — revise — ambiguity — cancel-out-of-`PROPOSED` branch leaves the project row entirely alone — routes/adr.py:177,181-183
- §3.5 — insert — ambiguity — `TALENT_NO_SHOW` branch likewise touches no project field — routes/adr.py:170-173
- §3.6 — insert — ambiguity — each superseded booking bumps its own `version`, and its `release_reason` stays **null** — routes/bookings.py:92-94
- §3.6 — insert — ambiguity — booking creation bumps the project's `version` by exactly 1, once per request however many siblings it supersedes — routes/bookings.py:119-120
- §3.6 — insert — ambiguity — Opening also requires `pipeline_stage` not `ARCHIVED` — routes/bookings.py:198
- §3.6 — insert — ambiguity — Opening writes only the booking row — routes/bookings.py:204-207
- §3.6 — insert — ambiguity — Closing also requires `pipeline_stage` not `ARCHIVED` — routes/bookings.py:218
- §3.6 — insert — ambiguity — non-`REMOTE` attendance on sign-off reports `ERR_INVALID_STATE` — routes/bookings.py:252-253
- §3.6 — insert — **mismatch** — sign-off is the only write beneath a project carrying **neither** the posture nor the archival gate (rung 17's "every child write" over-claimed), and it touches no project field — routes/bookings.py:243-262
- §3.6 — insert — ambiguity — `release_reason` is at least one character with no upper bound — routes/bookings.py:271
- §3.7 — insert — ambiguity — the round's submitter is internal and appears on no deliverable payload (only as the report's `submitted_by_user_id`); submission bumps no project field — routes/deliverables.py:71,141-143
- §3.7 — insert — ambiguity — evaluation never parses a body at all, so a malformed/non-object body is not a schema violation — routes/deliverables.py:146-151
- §3.7 — insert — ambiguity — the 201 body is the new QC report, not the updated deliverable; the deliverable bumps, the project does not — routes/deliverables.py:167-191
- §3.7 — revise — ambiguity — `remediation_note` is 0–2000 chars, validated then discarded; remediation bumps no project field — routes/deliverables.py:214,224-228
- §3.8 — insert — ambiguity — `delivery_reference` is 1 to 200 characters — routes/deliverables.py:237

Cross-checks: every guard's position in the three route files matches the §2.11 rung order already documented; all 201-vs-200 choices, occupancy/buffer/window inclusivity boundaries, cap comparisons, sort orders, list filters and role lists already matched the PRD and needed no change. The file was not re-copied; passes 1 and 2 markers verified present.

### Orchestrator final verification

- `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (+18,972 chars) — the scan genuinely ran (the known "identical file means the scan never happened" failure did not occur).
- 444 lines, 27 headings, ends at the complete §5 table — not truncated.
- All 8 `workspace/implementation/results.$i.json` files still present from the final green sweep (98/98 each).
- Pipeline complete through Step 9.
