# Worklog — task_3127_residential_addiction_treatment_admission_level_care_step

## Step 1: Create task directory — 2026-09-30T00:00:00.000Z

Task directory `./tasks/task_3127_residential_addiction_treatment_admission_level_care_step/` was pre-allocated by the pipeline and already contained `workspace/` (empty). No index computation or directory creation was performed — the pre-allocated path was used verbatim as the task directory.

## Step 2: Generate scaffold — 2026-09-30T01:54:18.572Z

Done. All three scaffold artifacts are generated, lint-clean, and self-consistent.

**Files written** (all in `/home/ubuntu/github/CodingPRD/tasks/task_3127_residential_addiction_treatment_admission_level_care_step/`):
- `SCAFFOLD.yaml` — 3,637 lines (§1.0–§1.7; no difficulty/corner key)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 5,043 lines (single top-level key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 9,096 lines (single top-level key `scaffold_corner_design`)

**Counts**
- Entities 18 · state machines 7 (46 transitions, incl. two parallel dimensions on `TreatmentEpisode` and a self-loop release/re-occupy cycle on `LevelOfCareChange`) · concurrency rules 4 (all OCC, verified to name `expected_*_version` in their endpoint `input:` and bump the parent `version`) · calculations 14 · validations 53 · endpoints 97 · error codes 68 · roles 7
- §1.8 difficulty instances: **18** — 9 rules × 2 (`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`)
- §1.9 corner instances: **42** (41 active + 1 `excluded_because` stub) across all nine taxonomy sections

**Design summary** — archetype `compliance_audit` × `quota_allocation`, layers OCC / cascading side effects / ops-run checkpoint / deferred actions; `hybrid` topology, compound + parallel + cyclic state shapes, `segregation_of_duties` role model. Hardness levers: two dual-variant calculation pairs across different entity domains (ASAM placement; step-down urgency), two different combinatorial modes (tiered non-linear deduction; pinned nested-rounding order), three transitive cascades of depth 3, two compensating invariants over different conserved quantities (live bed-occupancy count vs audit-row count), interval-semantics divergence between bed windows (leading turnaround buffer) and recovery-housing windows (right-open when the barrier is zero), and a deterministic four-element ranked housing selector.

**Constraint honored**: no sibling task under `tasks/` was listed, globbed, grepped, or read — generation used only the scenario text, SKILL.md, its `references/claim-extraction-guide.md`, `examples/`, and `scaffold_lint.py`.

**Verification**: `scaffold_lint.py` reports `VERDICT: clean lint`; separately verified 1,664 structured calls all resolve to declared endpoints with matching roles/payloads, captures resolve to declared `output:` fields, every OCC version input is a `${var}`, zero unbound `${…}` placeholders in either design file, zero forbidden concurrency vocabulary, and all 34 declared FKs have reverse-reachability GETs. Generator scripts and part files used during assembly were removed, leaving only the three deliverables.

## Step 3: Copy shared files — 2026-09-30T01:55:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T02:31:30.836Z

The Step 4 subagent was interrupted when the host session ended; its returned summary was never recorded. `workspace/PRD.md` was nevertheless present on disk (87,746 bytes, 498 lines, mtime 02:01), so the orchestrator verified completeness structurally rather than re-running the step:

- Structural integrity: file opens with `# Residential Addiction Treatment Stepdown API — Product Requirements Document`, contains all five required sections (`## 1. Introduction`, `## 2. Global Specifications & System-Wide Principles`, `## 3. Business Logic & Workflows`, `## 4. Endpoint Definitions`, `## 5. Error Code Catalogue`), and terminates on a well-formed final catalogue table row (`ERR_AUTHORIZATION_DAYS_EXHAUSTED`) — no truncation.
- Endpoint coverage: scaffold declares 97 endpoints (53 GET / 42 POST / 2 PUT); PRD §4 table carries exactly 97 rows with the identical method histogram. A sorted path-level diff of the two sets is **empty** — identical endpoint sets, no missing or extra operations.
- Error catalogue: scaffold declares 68 error codes; PRD §5 catalogue lists 68 matching `| \`ERR_…\` | <status> |` rows.

Verdict: Step 4 output is complete and valid; the step was NOT re-run (re-running would have needlessly regenerated an intact 87 KB artifact and risked a different scatter). The design files `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not read by the PRD generator (constraint carried forward to Step 5/6 prompts).

## Step 5: Generate unit tests — 2026-09-30T03:41:18.926Z

The Step 5 subagent was interrupted when the host session ended; its returned summary was never recorded. Its output was nevertheless fully present on disk (`test_helpers/` 02:39–02:53, `test_suite/` 02:41–02:59), so the orchestrator verified the artifact contract structurally rather than re-running the step:

**Files written**
- `test_helpers/`: `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py` (35,078 B) — all nine canonical modules present.
- `test_suite/`: `conftest.py` + 10 `test_*.py` files (`test_01_assessment_placement` … `test_10_additional_targets`).

**Verification results**
- Syntax: `python3 -m py_compile` over all `test_helpers/*.py` and `test_suite/*.py` → **ALL COMPILE OK**.
- Collection: `pytest --collect-only` → **84 tests collected**, 0 errors.
- Design-tag contract: **84 tests, 84 design tags, 0 tests with ≠1 tag** (no untagged, no dual-tagged tests).
- Tag resolution: **0 unresolved tags** — every tag names a real non-stub instance in the corresponding design index.
- Coverage: **Difficulty 18/18** valid instances covered (9 rules × 2). **Corner 40/41** valid instances covered; the single uncovered instance is `calculations/bed_night_bank_and_session_ledger_round_with_half_up`, which was correctly **skipped, not weakened** — PRD §2.11's rounding paragraph names only the step-down pressure score, the compliance multiplier and the housing-savings arithmetic ("Rounding is always half up… the rules that round to a fractional precision are called out where they occur"), and never declares a rounding mode for the bed-night bank or session ledger → **PRD-first condition 1a (coverage) fails → skip**. The one `excluded_because` stub instance carries no test tag.
- No `skip` / `xfail` markers anywhere in `test_helpers/` or `test_suite/` (the only textual match is the word "skips" inside a comment about skipping a rung of the ASAM continuum).

Verdict: Step 5 output is complete, well-formed and contract-compliant; the step was NOT re-run.

## Step 6: Generate implementation — 2026-09-30T04:07:18.607Z

Implementation complete and verified.

## Files written (`workspace/implementation/`, 4700 lines)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 9 | guarded launcher: `exec python3 app.py`, reads `$PORT`, binds `0.0.0.0` |
| `app.py` | 63 | Flask app, blueprint registration, error handlers |
| `db.py` | 100 | in-memory store (18 tables), single logical clock |
| `common.py` | 259 | envelope/pagination helpers, enums, request-shape validators, `round_half_up` |
| `errors.py` | 154 | 68-code catalog with HTTP statuses + messages |
| `response.py` | 49 | `meta`/`response_type`/`data` envelope |
| `middleware.py` | 117 | `X-User-ID`/`X-User-Role` auth, RBAC, idempotency, path resolution |
| `services/calc.py` | 398 | all 14 calculation rules |
| `services/facility.py` | 110 | licensure, `as_level_max`, posture derivation, accreditation expiry |
| `services/engine.py` | 662 | admission/discharge gates, change ledger, 7-stage ops batch |
| `services/duties.py` | 31 | segregation-of-duties log |
| `routes/{facilities,people,episodes,clinical,changes}.py` | 499/551/508/540/650 | all 97 endpoints |

## Verification
- **Endpoint coverage: 97/97** — normalized audit of `SCAFFOLD.yaml` paths against `app.url_map` reports `MISSING: NONE, UNMATCHED: NONE` (98 rules incl. Flask's static rule).
- **Fresh-boot isolation:** launched via `PORT=<n> bash start.sh`; after building state, killed only my own saved PID, relaunched, and confirmed `total_count` went 2 → 0 with `data: []` and the clock back to `2026-09-01T00:00:00.000Z`. No seeding/preload paths exist (grep for `seed|preload|bootstrap|fixture` is empty); no SQLite/JSON-dump/pickle/tmp persistence.
- **Readiness:** HTTP 200 in ~3 ms, `Running on all addresses (0.0.0.0)` confirmed on a fresh `$PORT`.
- **Behavioural suites (all passing, each on its own fresh server):** full intake→assessment→authorization→clearance→admission→sessions→completion→discharge→alumni lifecycle; 22 error-code/precedence checks; accreditation lifecycle (suspend/reinstate/renew/revoke with licence and posture recompute); ranked housing resolution (worked example resolves to H_B) plus pool exhaustion and capacity ceiling; multi-step descent with `MAX_STEP_DOWNS_REACHED`; bed-window overlap; same-epoch compensating cancel restoring `committed_bed_nights`; `ERR_EPOCH_STALE` after an intervening ops run; deferred `AWAITING_DISCHARGE` release row.
- **Calculations:** all worked examples from the scaffold reproduce exactly — placement bands and both variants (incl. `withdrawal_risk=4` → ASAM_3_7), urgency A=61.0 / B=51.0 with agreement at review count 0, the pinned clearance rounding (35.7 h → 36 h → 2 days), posture boundaries 44/45/59/60, billing multipliers and the 900-cent cap, weekly requirements, and coverage-map savings.

## Known deviations (deliberate, flagged)
1. **Two scaffold conflict resolutions**, both needed to make the graph reachable: treatment-plan and withdrawal-management authoring are accepted in `AWAITING_ADMISSION` as well as `IN_TREATMENT` (the scaffold makes both admission preconditions yet gates their creation on `IN_TREATMENT` — otherwise no test can ever admit an episode). `ERR_EPISODE_NOT_IN_TREATMENT` still fires in every other state.
2. **`bed_id` on a level-of-care change is treated as the target bed**; the source is derived from the episode's held bed. The scaffold's literal reading (source) is unreachable, since the only endpoint that can occupy a target bed after admission is the change-completion itself.
3. **Admission rests its bed hold on the authorization's hold flag** rather than re-deriving from `Bed.status`, because completing an earlier change re-points the episode to a new bed while the original authorization's bed legitimately reads `CLEANING`. An intervening ops run that releases it still yields `ERR_BED_NOT_HELD`.
4. **`ERR_WITHDRAWAL_MANAGEMENT_NOT_STABLE`** (absent from the error catalog but named in PRD §3.7) is mapped to 409.
5. Scaffold-internal contradictions left as declared, not "fixed": clinical-status cancel causes `AWAITING_ASSESSMENT` with a null `assigned_level`; suspected typos (`CARE_HOLD` carry-over status, `Authored_days`); `revcap` pre/post snapshots are frozen to the same recomputed value; compliance risk is recomputed before expiry inside the ops run so a lapsed-but-`GRANTED` row scores at the 12-point expired rate on the run that detects it.

## Step 7: Run tests and iterate — 2026-09-30T05:53:50.677Z

Clean 8-round sweep: **84/84 in all 8 rounds, zero failures across the union.**

### Summary

**Iterations run:** 6 full 8-round parallel sweeps (plus 1 initial foreground diagnostic round and many live-server probes), starting from 24/84.

**Tests deleted:** none. Every failure traced to a fixture/factory bug or an implementation gap, not to PRD silence, so the PRD-First contract kept all 84 tests.

**Fixes applied to `test_helpers/`**
- `constants.py` — `SCORES_ASAM_3_5` weighted total was 33, not the asserted 40 (the whole suite's default scorecard was one band low: ASAM_3_1 instead of ASAM_3_5). Corrected to 40. Added `CLOCK_2026_09_05/_09_10/_09_14`, a set of `*_ISO` constants (PRD §2.11: "three fractional digits throughout"), and made `BED_LABEL_21`'s bed carry a non-zero turnaround so each bed row has a distinct turnaround and the ASAM_3_1 bed is a usable, unclaimed target.
- `api_client.py` — `list_episodes` passed `headers=`/`params=` as keywords, landing the dict in `payload`; now follows the standard positional convention.
- `fixtures.py` — the dominant change. Reordered the admission preamble (clearances → approve → withdrawal-management → plan → **admit** → status move), because PRD §3.3 requires WM `ACTIVE` at admission while §3.7 requires `MEDICALLY_STABLE` for completion, so the status move cannot precede admission. Approving *before* the clearances contradicted §3.2's promotion ("once every clearance… still reads `CLEARED`"). Split `setup_claimed_episode` into an admitted default plus `setup_staged_episode` for the `AWAITING_AUTHORIZATION` staging state; added `fund_step_down_authorization` (funds at a *different* level — §3.2 stacks by level — then burns days so §3.6's unused-days rule is satisfied); reworked `setup_exhausted_episode` to a zero-day payer grant; pinned `setup_curriculum_episode`'s clock so its 14 rows stay inside the current treatment week; added `clock`/`burn_after_admission`/`second_run_clock` knobs; `setup_unreachable_episode` reordered to the PRD state.

**Fixes applied to `implementation/`**
- `services/engine.py` — `last_ops_run_at` now stamped at the run's *start* (§3.5), with the outgoing anchor threaded into stage one's burn; admission's FROZEN check hoisted ahead of the clearance checks and the CLEARED-but-lapsed TB branch reordered so §3.3's 410 lapse wins over the 409 not-cleared code (§2.7a); implemented §3.2's gated `AWAITING_AUTHORIZATION → AWAITING_ADMISSION` promotion on both the approval and clearance-clearing paths; implemented §3.6's exhaustion cascade (coverage-map promotion, `care_level_status` → `STEP_DOWN_PENDING`, plan supersession); moved the step-down bed release into stage five's second clause; implemented §3.7's deferred-release hold/release alternation in stage seven; gated the `PENDING_DISCHARGE_ORDER` branch on the funding authorization and charged `step_down_count` on the allocation branch only.
- `services/calc.py` — added `_granted_days`; §3.2's persisted urgency and the projected variant both measure against the days *granted at approval* ("the denominator is the granted days alone"), not the running total a concurrent review widens.
- `routes/clinical.py` — POST assessment now enforces §3.1's usable-credential rule on the named assessor (completion also checks the acting clinician); session `duration_minutes <= 0` is a shape failure ahead of the state gate.
- `routes/changes.py`, `routes/episodes.py`, `routes/facilities.py`, `middleware.py`, `common.py` — body-shape/level validation ahead of the state gate; body references that exist at another facility now return `ERR_INVALID_REFERENCE` (§2.7); §3.6's route rule ordered ahead of the fiscal rule (§2.7a); authorization request permitted on an `IN_TREATMENT` episode (without it §3.6's whole step-down pathway is unreachable); zero-barrier recovery housing treated as open-ended (§2.9); added a server-owned-field tolerance so a body carrying a declared derived field is answered with the server's value rather than refused.

### Orchestrator independent verification

The subagent's own `results.*.json` files were **not** present on disk at hand-back (it had cleaned them up; only its source edits remained, timestamped 05:02–05:15). The orchestrator therefore **did not accept the PASS claim on trust** and re-ran the full 8-round parallel sweep itself at 05:48–05:51:

- rounds 1–8: **each `{'passed': 84, 'failed': 0, 'errors': 0, 'skipped': 0, 'total': 84}`**, per-round wall time ~172 s.
- `results.{1..8}.json` are now on disk in `workspace/implementation/` as the durable evidence of the final sweep.
- Zero skips/xfails; storage remains in-memory only.

## Step 8: Finalize PRD — 2026-09-30T06:46:19.971Z

PRD_FINALIZED.md is written. Summary below.

### Sizes
- `PRD.md`: 498 lines; `PRD_FINALIZED.md`: 500 lines; **+2 lines / +0.40%**. 20 prose edits (10 inserted sentences, 10 revised paragraphs); no new sections; no deletions of PRD-determined behavior.
- Orchestrator check: `diff` reports 42 changed lines (21 removed / 21 added) — consistent with the 20 reported edits.

### Changes (PRD section — insert/revise — what — impl anchor)
1. **§2.7 — insert** — a body value for a server-owned field (`id`/`created_at`/`updated_at`/`version` and the state/derived/stamped fields) is tolerated rather than refused as undeclared input — `common.py:169-189` (`check_allowed`/`SERVER_OWNED_FIELDS`), e.g. `routes/clinical.py:445-446`.
2. **§2.8 — revise** — the burn interval opens at the *previous* run's `last_ops_run_at`, not the stamp this run just wrote; empty span when neither anchor exists — `services/engine.py:549-550,716-731`.
3. **§2.9 — revise** — committed-bed-nights ledger rewritten around the direct-`COMPLETED` branch: `PENDING_DISCHARGE_ORDER` allocates/releases nothing; the same-epoch cancel reverses the branch's moves — `services/engine.py:494-521`, `routes/changes.py:309-333`.
4. **§2.9 — revise** — zero-`grab_barrier_hours` house reads an existing `ACTIVE` plan's window as open-ended at draft time — `routes/changes.py:463-477` (creation `routes/facilities.py:279`).
5. **§3.1 — revise** — the assessor's usable-credential check is enforced at assessment *filing*, not only at completion — `routes/episodes.py:150`; check at `services/engine.py:147-163`.
6. **§3.1 — revise** — completion checks the acting `Clinician` as well as the named assessor — `routes/episodes.py:245-246`.
7. **§3.2 — revise** — authorization request also accepted on an `IN_TREATMENT` episode — `routes/episodes.py:337-338`.
8. **§3.2 — revise** — `AWAITING_AUTHORIZATION → AWAITING_ADMISSION` is gated on APPROVED auth *and* all-clearances-CLEARED, tested on both the approve and the clearance-clearing path (≥1 clearance required) — `routes/episodes.py:450`, `services/engine.py:189-207`, `routes/clinical.py:127`.
9. **§3.2 — revise** — both urgency variants measure the denominator against the days granted at approval (`granted_days`), not the running `authorized_days` — `services/calc.py:94-137`, `routes/episodes.py:442`.
10. **§3.3 — revise** — withdrawal-management authoring is accepted at `AWAITING_ADMISSION` as well as `IN_TREATMENT` — `routes/clinical.py:183-184`.
11. **§3.3 — revise** — FROZEN refusal settled ahead of the clearance conditions; the TB lapse (410) beats the not-cleared code — `services/engine.py:233-268`.
12. **§3.4 — revise** — treatment-plan drafting also accepted at `AWAITING_ADMISSION` — `routes/clinical.py:313-314`.
13. **§3.4 — revise** — non-positive `duration_minutes` is a shape failure (`ERR_INVALID_REQUEST`) settled ahead of the state gate — `routes/clinical.py:458-459`.
14. **§3.5 — revise** — `last_ops_run_at` overwritten before any stage reads it, but stage one burns from the prior value — `services/engine.py:549-550`.
15. **§3.5 — revise** — stage-five promotion also moves an `ACTIVE` episode to `STEP_DOWN_PENDING`; the release clause runs later in the same stage — `services/engine.py:598-631`.
16. **§3.5 — revise** — stage seven alternates hold/release on every arrived run, not a repeated release — `services/engine.py:642-672`.
17. **§3.6 — revise** — first branch redefined (incl. non-step-down with a bed); `PENDING_DISCHARGE_ORDER` is a resting status no completion operation advances — `services/engine.py:447-478`.
18. **§3.6 — revise** — second branch requires a supplied `bed_id` *and* a residential target *and* a strict rank drop — `services/engine.py:447-455,494-521`.
19. **§3.6 — revise** — cancel from `PENDING_DISCHARGE_ORDER` (and `PLANNED`) returns the episode to `ACTIVE` — `routes/changes.py:334-339`.
20. **§3.6 — revise** — a payer step-down demand creates **no** change row; the coverage level is recorded on the authorization only on the exhaustion path — `services/engine.py:743-761`, `routes/episodes.py:484-488`, `routes/changes.py:230-231`.

### Pre-edit search log
**1 (§2.7 server-owned)** — (a) subject: undeclared-field refusal vs server-owned tolerance. (b) `common.py:155-189` (`check_allowed`, `body_of`, `SERVER_OWNED_FIELDS`); every route's `check_allowed` call; `routes/clinical.py:442-446` (sessions lists `status/attended/billing_amount_cents` explicitly); `public()` `common.py:139-148` strips private keys. (c) Scoped to fields the server holds; added "whether or not the operation happens to list the field" to cover both declared and undeclared cases.

**2 (§2.8 burn anchor)** — (a) subject: `last_ops_run_at` used by the burn. (b) `services/engine.py:542-556,716-731` (`run_ops`, `_burn_authorization`); `services/calc.py:259-267` (`whole_days_in_intersection`); `db.py` clock. (c) Reworded to "the value held before this run restamped it" and added the empty-span case (`start == now`, matching `_burn_authorization`'s `start = now` fallback).

**3 (§2.9 ledger)** — (a) subject: committed-bed-nights conservation. (b) `services/engine.py:90-106` (`episode_bed`), `447-521` (`change_branch`, `complete_change`, `_finalize_change`); `routes/changes.py:287-345,348-406` (cancel/step-up); `services/calc.py:353-354` (`committed_bed_nights`). (c) Rewrote to avoid the false claim that a non-bed completion releases the source bed (Step 7's fixtures confirm it does not), and to avoid claiming the count reaches a specific value — the cancel restores whatever the completion left.

**4 (§2.9 housing)** — (a) subject: zero-barrier housing window. (b) `routes/changes.py:463-477` (draft overlap, `grab_barrier_hours == 0 ⇒ oend = None`), `546-593` (activate path, no barrier handling); `services/facilities.py:263-286` creation; `calc.py:368-401`. (c) Scoped to "at draft time" and to "the housing row named in the request" so the activation path is not mis-described.

**5–6 (§3.1 credentials)** — (a) subject: credential checks on assessment file/complete. (b) `routes/episodes.py:124-184` (create), `228-266` (complete, `user_id` and assessor), `269-301` (cancel); `services/engine.py:140-163` (`authoring_credential_ok`); `routes/clinical.py:319` (plan author). (c) Filing edit phrased to mirror the completion precondition; completion edit softened "two preconditions" → "on two identities" to cover the acting clinician.

**7 (§3.2 request state)** — (a) subject: authorization-request episode gate. (b) `routes/episodes.py:308-378` (create), `464-525` (deny/review); `services/engine.py:774-781`; `routes/changes.py:204` / `test_10` step-down path. (c) Added `IN_TREATMENT` and rewrote "not AWAITING_AUTHORIZATION" → "any other state".

**8 (§3.2 promotion)** — (a) subject: AWAITING→ADMISSION promotion. (b) `services/engine.py:177-207` (`clearances_all_cleared`, `promote_to_awaiting_admission`), `36-45` (`active_authorization`); `routes/clinical.py:115-128` (clear); `routes/episodes.py:449-450` (approve); `test_04` single-clearance case. (c) Added "operative authorization is `APPROVED`" and "at least one clearance" to match `clearances_all_cleared`'s empty-row and non-`APPROVED` refusal.

**9 (§3.2 urgency denominators)** — (a) subject: `urgency_score` / `projected_step_down_urgency` denominators. (b) `services/calc.py:94-137`; `routes/episodes.py:432-446` (`granted_days` write); `routes/people.py:266-275` (summary); `test_02:130,159` (persisted 56.7 vs projected 48.1). (c) Replaced "`authorized_days`" with "days granted at approval" in both variants and noted it is fixed at approval.

**10 (§3.3 WM authoring)** — (a) subject: withdrawal-management authoring gate. (b) `routes/clinical.py:168-208` (create), `243-272` (update — no state gate); `engine.py:48-53,270-272`. (c) Scoped the `ERR_EPISODE_NOT_IN_TREATMENT` refusal to create (the update path has no such gate).

**11 (§3.3 admission order)** — (a) subject: admission check order (frozen vs clearance; lapse vs not-cleared). (b) `services/engine.py:224-299` (incl. duplicated hoisted frozen check at 233 and 256); `routes/changes.py:67-79`; `test_04:221-273`, `test_10:73-95`. (c) Avoided asserting the exact §2.7a rank; phrased as "settled ahead of the clearance conditions" and gave the TB lapse/not-cleared order explicitly.

**12 (§3.4 plan drafting)** — (a) subject: treatment-plan create episode gate. (b) `routes/clinical.py:286-347` (create), `382-409` (edit), `412-428` (cosign); `engine.py:274-276`; `engine.py:56-64` (`active_treatment_plan`). (c) Softened "has not reached IN_TREATMENT" → "in any other state".

**13 (§3.4 duration)** — (a) subject: session `duration_minutes` validation. (b) `routes/clinical.py:435-485` (create), `513-539` (record — no duration gate); `calc.py:334-341`. (c) None needed; scoped to the create path.

**14 (§3.5 stamping)** — same subject as #2; (b) `services/engine.py:542-556`; (c) "overwritten before any stage reads it" to keep the epoch-uniformity sentence intact while pinning the burn anchor.

**15 (§3.5 stage five)** — (a) subject: stage-five promotion consequences. (b) `services/engine.py:598-631`; `routes/episodes.py:477-490` (deny, non-in-treatment). (c) Added the `care_level_status` move and the same-run ordering, both matching the code.

**16 (§3.5 stage seven)** — (a) subject: AWAITING_DISCHARGE cycling. (b) `services/engine.py:642-672` (incl. the `OCCUPIED`/`AVAILABLE` → `CLEANING` branch); `engine.py:372-399` (`_defer_release`); `test_07:70-105`. (c) Generalized §3.5's release-only description to the observed alternation and added the not-yet-due skip, consistent with the §3.7 hold/release text.

**17–18 (§3.6 branches)** — (a) subject: completion branch classification. (b) `services/engine.py:447-455` (`change_branch`), `458-521` (`complete_change`/`_finalize_change`); `routes/changes.py:134-234` (appoint); `test_05:184-295`, `test_02:283-340`, `test_10:132-181` (PDOrder; count only on the allocation branch). (c) Added the third disjunct (non-step-down with a bed), the `bed_id`/residential requirement on branch two, kept the APPROVED gate on both branches (code checks it before classifying), and removed the unsupported "advances to COMPLETED"/"drops by one" claims.

**19 (§3.6 cancel)** — (a) subject: cancel state machine. (b) `routes/changes.py:287-345`; `engine.py:488` (`_completed_epoch`). (c) Used "reverses the moves the completion branch made" for the COMPLETED case (branch-conditional) and added `PENDING_DISCHARGE_ORDER` → `CANCELLED`/`ACTIVE`.

**20 (§3.6 demand)** — (a) subject: what a step-down demand does. (b) `services/engine.py:598-631,625-630` (bed release), `743-761` (exhaustion: `coverage_forced_level`); `routes/episodes.py:477-490` (deny); `routes/changes.py:230-231`; `test_03:214-245`, `test_09:216-245`. (c) Removed the false "fresh change row is created at PLANNED"; scoped the coverage-level recording to the exhaustion path only (the deny path records none); named both triggering paths.

### Step 7 items intentionally left unpatched (PRD already determines them / pure fixture or test bugs, no PRD silence)
- `test_helpers/constants.py` (33→40, added clock/ISO constants, `BED_LABEL_21` turnaround), `api_client.py` positional-args, and several `fixtures.py` reorderings (clearances-before-approve, `setup_staged_episode`, `setup_exhausted_episode`, `setup_curriculum_episode` clock) are fixture/config corrections, not PRD gaps.
- Body-reference `ERR_INVALID_REFERENCE` for a foreign-facility `bed_id`/`service_id` (§2.7 line 124 literally already states it), body-shape/enum-before-state ordering for level changes and CC plans, the `ERR_LEVEL_ROUTE_NOT_ALLOWED`-before-`ERR_AUTHORIZATION_UNUSED` ordering (§2.7a), and `coverage_forced_level`'s internal field name need no new prose: they are already entailed by §2.7/§2.7a and observable field names.

No files other than `workspace/PRD_FINALIZED.md` were created or modified.

## Step 9: Complete PRD — 2026-09-30T07:09:04.301Z

PRD_COMPLETED.md is complete. Final report:

### Deliverable
`/home/ubuntu/github/CodingPRD/tasks/task_3127_residential_addiction_treatment_admission_level_care_step/workspace/PRD_COMPLETED.md`

- Source: `PRD_FINALIZED.md` — 500 lines / 93,587 chars
- Output: `PRD_COMPLETED.md` — 502 lines / 114,035 chars
- Char delta: **+20,448**; line delta **+2**. 46 original paragraphs revised in place; no sections added, no new paragraphs inserted (the two added lines are a single paragraph reflow).

### Counts
- **30 ambiguity-pins** (PRD silent; impl pinned)
- **28 mismatch-revisions** (PRD described a different behaviour; revised to match impl)

### Changes (PRD section — insert|revise — kind — what changed — impl file:line)

- §2.4 — revise — mismatch — `expected_*_version` supplied on an operation outside the four gated ones is an undeclared field → `ERR_INVALID_REQUEST` — `common.py:163`,`routes/*`
- §2.4 — insert — ambiguity — a facility-scoped child is matched to the path facility; network-wide terminal-id reads are unscoped — `middleware.py:91-97`,`routes/facilities.py:96`
- §2.5 — revise — mismatch — `is_accepting_admissions` also requires a `GRANTED` `ACCREDITATION_BODY` row, not merely non-FROZEN + licensed — `services/facility.py:81-85`
- §2.5 — insert — ambiguity — credential starts `ACTIVE`; created at the body's `facility_id`; unknown facility → `ERR_FACILITY_NOT_FOUND` — `routes/people.py:89-97`
- §2.5 — insert — ambiguity — unknown clinician → `ERR_CLINICIAN_NOT_FOUND` ahead of `ERR_ASSESSOR_CREDENTIAL_INSUFFICIENT`; usable test takes the first credential row (`STORE.first`) — `services/engine.py:147-163`
- §2.6 — insert — ambiguity — compliance score is also recomputed when an accreditation row is created — `routes/facilities.py:409`
- §2.7 — insert — ambiguity — unraisable `ERR_INVALID_REFERENCE` narrowed to bed/clearance/session body refs — `middleware.py:100-109`,`routes/episodes.py:330`,`routes/changes.py:159`
- §2.7 — insert — ambiguity — server-owned allowance is exhaustive; `ERR_INVALID_REQUEST` otherwise, incl. the unacknowledged session trio — `common.py:169-189`
- §2.7a/§2.1 — insert — ambiguity — `Clinician` identity resolves to a persisted clinician only on `Clinician`-permitted ops; else `ERR_INSUFFICIENT_PERMISSIONS` — `middleware.py:29-38`
- §2.9 — revise — mismatch — housing ceiling counts all facility `ACTIVE` plans, not only those per row; per-row ceiling is the RANKED_AUTO candidate test — `routes/changes.py:577-580`
- §2.9 — revise — mismatch — `RecoveryHousing.licensed` ignores `state_code` and is shared by all rows at the facility — `services/facility.py:89-94`
- §2.9 — insert — ambiguity — bed held in `CLEANING` with 0 turnaround until an ops run passes — `services/engine.py:358-362`
- §2.9 — insert — ambiguity — housing `grab_barrier_hours` defaults 0; unknown facility → `ERR_FACILITY_NOT_FOUND` — `routes/facilities.py:268-285`
- §2.10 — insert — ambiguity — replacements carry `replaces_session_id`, mirror source fields, `plan_version` null — `services/engine.py:683-713`
- §2.11 — insert — ambiguity — clock response is exactly `{current_utc, facility_count}` — `routes/facilities.py:114`
- §2.3 — insert — ambiguity — enumerated query-filter set, exact match, empty string ignored, unknown params ignored — `routes/*`
- §3.1 — insert — ambiguity — assessment `Idempotency-Key` scoped per episode — `routes/episodes.py:132`
- §3.1 — insert — ambiguity — `total_score`/`recommended_level` recomputed from frozen `dimension_scores` + row's own basis before placement — `routes/episodes.py:248-264`
- §3.2 — insert — ambiguity — auth occupancy hold only if the bed is `AVAILABLE`; unresolvable `bed_id` → `ERR_BED_NOT_FOUND` — `routes/episodes.py:328-374`
- §3.2 — insert — ambiguity — idempotency keys scoped per episode (authorizations/sessions/assessments) — `routes/episodes.py:317`,`routes/clinical.py:448`
- §3.2 — revise — mismatch — approval guard order is PENDING → level → payer floor; floor applied to facility `state_min_credential_tier` then plan author; row carries `granted_days` — `routes/episodes.py:411-445`
- §3.2 — insert — ambiguity — `ERR_AUTHORIZATION_UNUSED` applies only to APPROVED/REVIEW_DUE; `STEP_DOWN_REQUIRED` → `NOT_PENDING` — `routes/episodes.py:473-476`
- §3.2 — insert — ambiguity — concurrent review refusals, zero-remaining tested ahead of posture, no body — `routes/episodes.py:503-509`
- §3.3 — insert — ambiguity — clearance `window_*`/`effective_status` presence rule; `status` filter matches raw stored status — `services/engine.py:113-125`,`routes/clinical.py:104-109`
- §3.3 — insert — ambiguity — dose-record resolution; `ciwa_recorded_at` re-stamp; no OCC gate; latest WM row operative — `routes/clinical.py:148-272`,`services/engine.py:48-53`
- §3.3 — insert — ambiguity — admission on a `DISCHARGED` episode → `ERR_ALREADY_DISCHARGED` — `services/engine.py:225-228`
- §3.3 — insert — ambiguity — bed-hold test void when no `bed_id` / unresolvable bed — `services/engine.py:287-292`
- §3.4 — revise — mismatch — plan create guard order: state → revoked accreditation → credential; `cosign_granted` starts false — `routes/clinical.py:313-343`
- §3.4 — insert — ambiguity — plan key includes `supersedes_plan_id` (whole-body fingerprint) — `middleware.py:53-71`
- §3.4 — insert — ambiguity — curriculum requirement read from current `assigned_level`, fallback 5 — `services/calc.py:281-316`
- §3.4 — revise — mismatch — submit-for-cosign is not gated on `DRAFT`; sets `ACTIVE`+`cosign_granted` — `routes/clinical.py:412-428`
- §3.4 — insert — ambiguity — edit optional-field semantics; no extra preconditions — `routes/clinical.py:399-404`
- §3.4 — insert — ambiguity — session `service_id` cross-facility → `ERR_INVALID_REFERENCE`; frozen before revoked-accreditation; no-show bills 0; billing floor 1 unit — `routes/clinical.py:445-539`,`services/calc.py:338-341`
- §3.5 — revise — mismatch — stage 3 comment tag order 2→3a→3b; lapsed-but-GRANTED rows scored before flipping — `services/engine.py:558-577`
- §3.6 — insert — ambiguity — appointment resolves body authorization/`bed_id`; route before unused-days; `from_level`/`change_type` derivation — `routes/changes.py:151-210`
- §3.6 — revise — mismatch — completion checked in order status → effective_at → authorization; `ERR_CHANGE_BRANCH_NOT_APPLICABLE` never raised — `services/engine.py:458-471`
- §3.6 — revise — mismatch — `assigned_level` set to target; revcap both snapshots equal; same-bed source not released; `ERR_STEP_DOWN_MAP_EXHAUSTED` not raised — `services/engine.py:494-521`
- §3.6 — insert — ambiguity — compensation restores `assigned_level`, no-epoch path allowed, `CANCELLED` cancel → `ERR_CHANGE_NOT_PLANNED`, cleaning-bed fallback — `routes/changes.py:309-341`
- §3.6 — revise — mismatch — step-up level from bed's `level_of_care`, route test after WM/availability, `STEPPED_DOWN` set, same-bed release skipped — `routes/changes.py:362-405`
- §3.7 — insert — ambiguity — complete-treatment condition order — `routes/changes.py:96-106`
- §3.7 — revise — mismatch — deferred AWAITING_DISCHARGE row may carry null `to_level`/`authorization_id`; `IN_TREATMENT` discharge takes the deferred leg — `services/engine.py:326-339,372-399`
- §3.7 — revise — mismatch — committed-bed-nights ceiling measured before the release; plan-author credential failure → `ERR_FACILITY_ACCREDITATION_INVALID`; `ACCREDITATION_BODY` test ignores expiry — `services/engine.py:313-343`,`services/facility.py:31-35`
- §3.8 — insert — ambiguity — CC draft guard order; `RANKED_AUTO` stores no `housing_id` at draft — `routes/changes.py:439-508`
- §3.8 — insert — ambiguity — cadence before window shape; missing `housing_id` on EXPLICIT → `ERR_INVALID_REFERENCE`; supersede runs last — `routes/changes.py:458-486`
- §3.8 — revise — mismatch — activation order pool → window → capacity (count+1) → supersede; whole-facility count — `routes/changes.py:556-592`
- §3.8 — insert — ambiguity — ad-hoc contact dedup absent; `abstinent_at_contact` stored only when REACHED — `routes/changes.py:600-666`
- §3.8 — revise — mismatch — utilization summary member set, `authorization_days_bank`/version 1, no-auth fallback values, `authorization_id` selection — `routes/people.py:246-302`
- §3.9 — revise — mismatch — no prior-status precondition on renew/suspend/revoke/reinstate; demotion on every status change; no `CARE_HOLD`; `state_min_credential_tier` = lowest row floor — `routes/facilities.py:444-499`,`services/facility.py:52-86`
- §4 — revise — mismatch — every create (incl. assessment/authorization/clearance/plan/session/change/CC/contact/WM) is `201`, only transitions are `200` — all `routes/*`

### Orchestrator verification
`PRD_COMPLETED.md` (502 lines / 114,035 chars) present. `implementation/` confirmed **unchanged since the orchestrator's independently verified 84/84 sweep** — no `.py` file under `workspace/implementation/` has an mtime later than 05:48, so the passing sweep remains valid evidence for the final state of the code.