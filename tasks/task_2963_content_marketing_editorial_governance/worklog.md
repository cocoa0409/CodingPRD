## Step 1: Create task directory — 2026-09-05T22:56:15.18985112Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2963_content_marketing_editorial_governance and its workspace/ subdirectory. Index 2963 pre-assigned by the orchestrating prompt (no auto-allocation).


## Step 2: Generate scaffold — 2026-09-06T00:56:11.000Z

All three scaffold artifacts are complete and lint clean.

## Files

| File | Lines |
|---|---|
| `.../SCAFFOLD.yaml` | 2885 |
| `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2009 |
| `.../SCAFFOLD_CORNER_DESIGN.yaml` | 5255 |

## SCAFFOLD.yaml element counts (§1.0–§1.7)
`domain_name: content-marketing-editorial-governance`, `api_prefix: /editorial`; top-level keys are `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles, difficulty_notes` — **no** `scaffold_difficulty_design` / `scaffold_corner_design` keys.

- 12 entities, 13 FK fields (all reverse-reachable)
- 9 state machines / 60 transitions (Claim now has 7 after the self-loop fix)
- 2 §1.2.1 concurrency rules (`content-item-create-stale-campaign`, `brief-assign-sme-stale-expert`)
- 10 calculations, 41 ordered validations, 50 endpoints, 56 error codes, 6 roles (each with `identity:`)
- `difficulty_level: expert_plus`; layers `cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, optimistic_concurrency`; `role_model: segregation_of_duties`; `consistency_model: immediate`

## §1.8 — 9 rule groups × 2 instances = 18
`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant` — 2 differentiated instances each.

## §1.9 — 9 sections, 106 instances (68 full recipes + 38 `excluded_because` stubs)
entities 13 (13/0) · state_machines 12 (9/3) · calculations 16 (10/6) · validations 16 (10/6) · endpoints 13 (7/6) · errors 24 (13/11) · rbac 3 (3/0) · cross_cutting_complexity_layers 8 (2/6) · consistency_model 1 (1/0). Section and claim_type values come from the claim-extraction guide; the errors and rbac labels (which the guide states as prose bullets, not tables) are documented in YAML comments at those sections.

## Verification
- **Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (Coverage: 50 endpoints, 12 entities, 18 §1.8 instances, 68 §1.9 instances, **1191 calls scanned**.) Lint was clean at every intermediate append (1038 → 1092 → 1109 → 1166 → 1191).
- Machine-checked: no duplicate `name` across both design files; all 38 stub citations resolve to real §1.8 instance names and none carries a `test_recipe`; all 56 error codes are referenced by a validation or transition **and** triggered by at least one instance; **all 50 endpoints are now called by at least one structured call** (the last six list endpoints were only named in prose, so a `Listing` instance covering them was added); no forbidden concurrency vocabulary; every ISO-8601 literal carries exactly three fractional digits.
- **Tails end at clean structural boundaries:** SCAFFOLD.yaml ends inside the `difficulty_notes` block scalar (numbered point 6, complete sentence); both design files end on a final quoted `assert:` list item.

## Self-consistency defects found and fixed in SCAFFOLD.yaml this session
(A) renewal stamping `status = LICENSED` contradicted `asset_license_status`'s thresholds — pinned with a `note:` and the corner instance rewritten; (B) Asset renewal precondition mis-attributed the `> clock` leg to `ERR_INVALID_REQUEST` instead of priority 34; (C) Claim had no `EVIDENCE_PENDING → EVIDENCE_PENDING` transition, making multi-row dossiers illegal — self-loop added and three precondition lists widened; (D) four sweep step texts pinned so `items_flagged_refresh`, `distributions_suppressed`, `campaigns_restricted` and `campaigns_frozen` are deterministic on replay; (E) the assign-sme side effect referenced `body.expert_id` where §1.5 declares `sme_expert_id`.

Scratch cleanup: `rm -rf .scratch/step2` only — the parent `.scratch/`, `worklog.md` and `workspace/` are untouched. No sibling task directory was read at any point.

ORCHESTRATOR NOTE: verified all three files present (2885/2009/5255 lines). Grepped SCAFFOLD.yaml for the difficulty directive ("harder than expert", "expert level") — zero hits, so the "Generate task harder than expert level!" line did NOT leak into the scenario key and cannot reach PRD.md.

## Step 3: Copy shared files — 2026-09-06T00:56:11.000Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-06T01:11:11.000Z

Step 4 complete.

## Deliverable

`workspace/PRD.md` — **430 lines, 104,105 bytes**; `grep -c '^## '` → **5** top-level sections. §4 endpoint table: 52 table lines = header + separator + **50 rows**. §5 error table: 58 table lines = header + separator + **56 rows**. §2.2 verified byte-identical to `section-2.2-response-structure.md`.

**Tail boundary: clean.** Ends on the complete final table row `| `ERR_SLOT_CAPACITY_EXCEEDED` | 409 |`, closing the §5 catalogue. Built with 11 sequential quoted-heredoc appends plus 3 surgical mid-document Edit calls, never a whole-file rewrite.

## Top-level sections in order
1. `## 1. Introduction`
2. `## 2. Global Specifications & System-Wide Principles` — 2.1 RBAC; 2.2 API Response Structure (verbatim); 2.3 Pagination; 2.4 Resource Identity, Auditing Fields and the Logical Clock; 2.5 Nested Path Resolution and the Ordered Validation Ladder (all 41 rules in priority order); 2.6 Version Pinning on Capacity-Consuming Writes; 2.7 Numeric Precision and Order-Pinned Arithmetic; 2.8 The Two Campaign Axes and Governance Posture; 2.9 Cascade Discipline; 2.10 Windows, ISO Weeks and Interval Arithmetic
3. `## 3. Business Logic & Workflows` — 3.1 Planning a Campaign and Its Editorial Calendar; 3.2 The Expert Bench and the Weekly Reservation Ledger; 3.3 Brief Development, Effort Scoring and Assignment; 3.4 Committing a Content Item to the Calendar; 3.5 The Review Fork, Turnaround SLAs and the Join Back; 3.6 Claim Substantiation and the Evidence Dossier; 3.7 The Asset Library, Usage Rights and Exclusivity; 3.8 Publication, Metadata and Channel Distribution; 3.9 Measurement, Attribution and Decay; 3.10 Retraction, Refresh and Pruning; 3.11 The Ordered Governance Sweep
4. `## 4. Endpoint Definitions`
5. `## 5. Error Code Catalogue`

## Hard Contracts
**Contract 1 — Field-Name Coverage: PASS.** entities[].fields 105/105/0 missing. request_body 61/61/0. query_params 22/22/0. Stricter 140-identifier pass also 0 missing.
**Contract 2 — Rule Coverage: PASS.** All 60 state transitions present (56 non-NONE with explicit `A → B` arrows; 4 NONE-origin creations covered in §3.4/§3.5/§3.8). All 41 validations in priority order with error ids. All 10 calculations including both dual variants (`claim_evidence_score` STANDARD/STRICT_REGULATED, `content_pipeline_attribution` LAST_TOUCH/ASSISTED_FRACTIONAL) and three order-pinned ones as numbered step sequences. Every numeric constant reproduced literally. Identical-effect sibling transitions stated explicitly.
**Contract 3 — §3 Path Purity: PASS.** 1,056 backtick tokens scanned in §3, 310 unique: 0 `/`-leading paths, 0 bare HTTP method words, 0 method+path pairs.

## Five scaffold self-contradictions resolved (doc-generator adjudications)
1. **`revision_number` on resubmit.** Submit-for-review `side_effects` says resubmit increments it; the field description and the `CHANGES_REQUESTED → IN_REVIEW` transition both say otherwise. Followed the 2-source majority — §3.5 states `revision_number` is NOT advanced by resubmission and counts refreshes only. Flagged as the likeliest implementer divergence.
2. **Brief state for content-item create.** Endpoint description says "APPROVED-or-earlier"; the `NONE → DRAFT` precondition says `state == APPROVED` with `ERR_BRIEF_NOT_APPROVED`. Followed the state machine (it carries the error id).
3. **`Campaign.breached_gate_count`.** Field description counts PENDING gates with `due_at < clock`; `campaign_governance_posture` counts gates with `sla_breached == true`. Used the calculation; reconciled by documenting `sla_breached` is set either at decision time (`decided_at > due_at`) or by sweep step 7.
4. **`ContentBrief.primary_keyword` per-campaign uniqueness** has no error code in the 41-rule ladder. Documented as a planning convention with an explicit note that no dedicated conflict code is defined — no error id invented.
5. **`ERR_ASSET_CHANNEL_NOT_LICENSED` at publish.** Validation 37's `applies_to` lists only asset-usages, but the `READY → PUBLISHED` precondition lists it too. Included both, ordered last in the publish sequence consistent with priority 37.

Constraints honoured: never opened either design yaml; read no sibling task directory; worklog.md untouched; no test/impl dirs created; no broad process kills; `.scratch/step4` removed, parent `.scratch` left in place.

ORCHESTRATOR VERIFICATION: independently confirmed 430 lines / 104,105 bytes; 5 `^## ` headings at lines 3, 11, 176, 312, 369; tail -12 shows twelve complete `| `ERR_*` | NNN |` rows ending the error catalogue — clean section boundary, NOT truncated mid-sentence. Grep for "harder than expert|scaffold|test_recipe" → 0 hits, so neither the difficulty directive nor design-index vocabulary reached the PRD.


## Step 5: Generate unit tests — 2026-09-06T02:25:12.000Z

Test infrastructure for task_2963 is complete.

## Output locations (both at the TASK ROOT)
- `test_helpers/`, `test_suite/`

## Files and line counts
`test_helpers/`: `__init__.py` 26, `api_client.py` 460, `api_errors.py` 180, `assertions.py` 349, `constants.py` 207, `factories.py` 334, `fixtures.py` 653, `test_users.py` 117, `types.py` 231.

`test_suite/`: `conftest.py` 18, `test_01_dual_variant_calculations.py` 274, `test_02_combinatorial_formulas.py` 221, `test_03_non_linear_state_machines.py` 276, `test_04_transitive_cascades.py` 240, `test_05_validation_priority_conflicts.py` 225, `test_06_boundary_precision.py` 257, `test_07_cross_entity_state_dependency.py` 209, `test_08_resource_temporal_overlap.py` 275, `test_09_compensating_invariants.py` 230, `test_10_entities_and_listing.py` 772, `test_11_state_machines.py` 425, `test_12_calculations.py` 599, `test_13_validations.py` 683, `test_14_endpoints.py` 515, `test_15_errors.py` 1452, `test_16_rbac.py` 359, `test_17_cross_cutting_layers.py` 321, `test_18_consistency_model.py` 168. Total 10,076 lines across both dirs.

## Coverage
- **104 tests**, confirmed by `pytest --collect-only -q` (104 collected, so every import and fixture resolves).
- **Queue A (Difficulty §1.8): 18 instances → 36 tests** (2 per instance, 4 per rule across the 9 rules).
- **Queue B (Corner §1.9): 68 instances → 68 tests** — entities 13, state_machines 9, calculations 10, validations 10, endpoints 7, errors 13, rbac 3, cross_cutting_complexity_layers 2, consistency_model 1.
- **SKIPPED instances: 0.** All 86 non-stub instances passed the PRD-first two-condition filter. The 38 `excluded_because:` stubs emitted nothing (verified: no tag matches any stub name).
- Where a design instance contradicted the PRD (4 cases: revision_number on resubmit, decay-window audit trigger, errors-3 DRAFT-brief create, errors-4 APPROVED-brief close cascade), the PRD's outcome is asserted with an explanatory comment while the instance's discriminating claim is preserved — no weakening, no xfail.

## Required confirmations
1. **Every test file parses** — `ast.parse` clean on all 19 `test_suite/` files and all 9 `test_helpers/` files; `pyflakes` reports nothing except the deliberate `from . import api_errors  # noqa: F401` re-export in `test_helpers/__init__.py`.
2. **Every test docstring carries exactly one `Design:` tag** — AST sweep over all 104 test functions found exactly one `Design:` line each, all well-formed, all 86 instance names resolving to real `name:` entries, no instance tagged twice.
3. **Neither directory exists under `workspace/`** — `ls workspace/` shows only `INSTRUCTION.md`, `PRD.md`, `implementation`.

Housekeeping: `workspace/implementation/` never read or written, `worklog.md` untouched, no processes killed, no server started; scratch stayed in `.scratch/step5/` and only that subdir was removed.

Work done in the final session segment: `test_16_rbac.py` (3 rbac instances — seven-probe exclusive-write denial matrix, AnalyticsService write/read surface with closed governance surface, legal SoD spanning both claim deciders), `test_17_cross_cutting_layers.py` (OCC version sequencing incl. child-insert and rejected-write no-bumps; usage-count level trigger arming/disarming/re-arming across four sweeps and a renewal), `test_18_consistency_model.py` (read-your-writes across attach, READY join, publish, distribution fan-out, recomputed posture — no sweep anywhere).

## Step 6: Generate implementation — 2026-09-06T02:25:12.000Z

Step 6 complete.

## Implementation directory
`workspace/implementation/`

## Files (21 total, 3058 Python lines)
`app.py` 60, `auth.py` 58, `calc.py` 244, `envelope.py` 98, `errors.py` 69, `governance.py` 477, `listing.py` 37, `serialize.py` 208, `store.py` 65, `timeutil.py` 95, `validate.py` 180, `r_assets.py` 131, `r_briefs.py` 198, `r_campaigns.py` 192, `r_claims.py` 117, `r_experts.py` 103, `r_gates.py` 86, `r_items.py` 608, `r_ops.py` 32, `start.sh` 8 (executable), `requirements.txt` 1.

## Endpoint count: 50 = PRD §4 row count (50)
Per blueprint: campaigns 10, experts 4, briefs 6, items 17, gates 2, claims 4, assets 5, ops 2. Verified mechanically: a script parsed all 50 rows out of the PRD §4 table and probed every one against the live server — **0 unrouted** (no row answered generic `ERR_NOT_FOUND` or 405), and a 50x6 role probe (every row x every role) found **0 RBAC mismatches** against the table's Authorized Role(s) column.

## Smoke test
- Port **41879** (also 41880, 41881 for reboot tests), all in the 20000-60000 band, no collisions.
- `start.sh` `exec`s, so the PID `bash start.sh` returns *is* the server: launched pid **4152912**, first request served **0.574 s** after invocation, then `SIGTERM` to that exact pid -> clean exit (rc -15), port free.
- Earlier instances (pids 4124168, 4151548, 4152599/4152637/4152672) each killed individually by exact pid. **No pattern/broad kill was ever run.** Ports 41871/41873 belonging to other pipelines were left untouched.
- Three consecutive cold boots each answered `GET /editorial/campaigns` with `total_count=0`, proving state is wiped per reboot.
- Functional smoke: two end-to-end scenarios passed with 0 unexpected results — (1) campaign -> slot -> expert -> brief -> assign-sme -> approve -> item (OCC-pinned) -> claim -> 2 evidence rows (score 4.50) -> legal substantiation -> asset + usage -> 4-gate fan-out -> join to `READY` -> publish with SoD editor -> distributions `LIVE` -> snapshot -> decay audit -> sweep -> close; (2) rights lifecycle: sweep at T+31d -> `EXPIRING`; sweep at T+50d -> `assets_expired:1, usages_lapsed:1, distributions_suppressed:1, items_flagged_refresh:1, campaigns_restricted:1`, usage `RIGHTS_LAPSED`, distribution `SUPPRESSED/ASSET_RIGHTS_LAPSED`, item `NEEDS_REFRESH`, campaign `RESTRICTED`; renew -> usage `ACTIVE`, distribution back to `LIVE` with reason cleared, campaign back to `OPEN`, **item deliberately left `NEEDS_REFRESH`** (partial compensation); second renewal in the warning window correctly `ERR_ASSET_STATE_INVALID`; retract -> distributions `RETRACTED`, usages `RELEASED`. Also verified all 8 not-found codes, `ERR_UNAUTHENTICATED` for an unknown role, `ERR_CLOCK_REWIND` (equal value = no-op), pagination bounds, and that `decay_pct`/`utilization_pct` serialize as bare 2-dp JSON numbers (`0.00`, `11.11`). Zero 500s in the server log.

## Required confirmations
- **(a)** All 19 modules pass `ast.parse` (PARSE_OK x19).
- **(b)** Storage in-memory only — 12 plain dicts in `store.py`, all length 0 at import time, clock at `2026-08-01T00:00:00Z`. No SQLite/JSON/pickle//tmp persistence. Zero seeded entities.
- **(c)** Never read, listed, globbed or grepped `test_suite/`, `test_helpers/`, any sibling task directory, or either `SCAFFOLD_*_DESIGN.yaml`. Inputs were only `INSTRUCTION.md`, `SCAFFOLD.yaml`, `PRD.md`. `worklog.md` untouched.

Scratch: worked only in `.scratch/step6/`, removed exactly that subdir; the concurrent Step 5 agent's `.scratch/step5/` intact. `__pycache__` removed.

PRD-fidelity note flagged to Step 7: where the §3.7 prose ordering and the §2.5 numbered ladder disagreed (asset-usage checks, claim-decide expiry-before-insufficiency, refresh's campaign-state-before-not-required), the numbered ladder was implemented, since the PRD states the ladder is the tie-breaker when several rules fail at once.

ORCHESTRATOR VERIFICATION (Steps 5+6): launched in a single message so the impl generator could not see test_suite/ (it did not exist at its spawn time). Confirmed test_helpers/ (9 files) and test_suite/ (19 files) are at the TASK ROOT, not under workspace/; workspace/ contains only INSTRUCTION.md, PRD.md, implementation/ (21 files). Only one worklog.md exists in the tree (no cwd-drift stray).


## Step 7: Run tests and iterate — 2026-09-06T02:38:20.000Z

All 8 rounds green. worklog.md untouched by the subagent (mtime pre-dated its work).

## Summary

**Iterations run: 2**

**Per-iteration failure counts**
- Iteration 1: 100/104 in all 8 rounds — 4 deterministic failures (identical union in every round, so no load-induced flakiness).
- Iteration 2 (final): 104/104 in every round. Read independently from each file: `results.1.json` 104/104, `results.2.json` 104/104, `results.3.json` 104/104, `results.4.json` 104/104, `results.5.json` 104/104, `results.6.json` 104/104, `results.7.json` 104/104, `results.8.json` 104/104. Sentinel `SWEEP_DONE` = `2026-09-06T02:37:02Z`.

**Tests deleted**
None deleted outright. Two PRD-silent assertion groups removed via STEP 1c partial-coverage splits (below).

**Fixes applied to `test_helpers/`**
None. The four failures were not a shared fixture bug — no clustered setup error appeared, and the helper layer audited clean (`test_users.py` uses genuinely distinct editor identities and a true `""` blank header; `factories.py` sends whole-cent integers and three-fractional-digit instants).

**Fixes applied to `test_suite/`** — all four failures were test bugs; the implementation was PRD-faithful in every case and was not modified.

1. `test_11_state_machines.py` :: `TestCampaignMachine::test_a_closed_campaign_refuses_its_edges_and_its_dependent_writes` — removed the `create_calendar_slot` attempt from the refused-writes list (partial-coverage split; kept re-activate, re-close and create-brief). PRD 2.8 enumerates exactly what the `status` axis gates — "briefs and content items may only be created against an `ACTIVE` campaign, and a refresh requires the campaign to be `ACTIVE`" — and calendar slots are deliberately absent; PRD 3.1's slot-creation paragraph states no campaign-status precondition, and ladder rung 15 applies only to transition endpoints. **Category: PRD silence** on campaign-status gating of calendar-slot creation.

2. `test_13_validations.py` :: `TestSlotCreateLadder` — the test asserted that `ERR_SLOT_DUPLICATE_WEEK` outranks a campaign-state check on slot creation, but that second rule does not exist in the PRD (same silence as above), so the ordering premise was unfounded. Rather than delete — this was the **only** coverage of `ERR_SLOT_DUPLICATE_WEEK` anywhere in the suite — it was split into `test_duplicate_week_and_stage_is_refused_while_other_triples_are_allowed`, which tests the genuinely PRD-covered rung 7 uniqueness rule on an `ACTIVE` campaign: the duplicate campaign+week+stage triple is refused, while the same week at another stage and the same stage in another week both succeed (PRD 3.1: "a campaign may hold one awareness slot and one decision slot in the same week but not two awareness slots"). Dropped the now-unused `ERR_CAMPAIGN_STATE_INVALID` import.

3. `test_17_cross_cutting_layers.py` :: `TestVersionSequencing::test_version_moves_only_on_the_accepted_write_and_only_on_its_own_row` — `assert_version(after_slot, 1)` -> `2`. The test conflated "status stayed `OPEN`" with "row unchanged", but the commit rewrote the slot's `committed_points` (0->6) and `utilization_pct` (0.00->15.00). PRD 2.4 is explicit that `version` "increments by exactly 1 on every mutation of that row, including mutations the row receives as a cascade from some other request rather than as the direct target of the call."

4. `test_17_cross_cutting_layers.py` :: `TestRightsThresholdLevel::test_usage_count_trigger_disarms_on_renewal_and_arms_again_on_the_next_expiry` — three asset-version assertions were each low by one, all from the same omission: attaching a usage recomputes the asset's `active_use_count`/`remaining_licensed_uses` (PRD 3.7), which is itself a versioned mutation. Corrected the full ledger to create=1 -> attach=2 -> expiry=3 -> renewal=4 -> second expiry=5 (`expired_asset` 2->3, `renewed` 3->4, final read 4->5). The last two were never reached in iteration 1 (the test aborts at the first failure); they were traced ahead of time rather than spending an extra sweep discovering them.

**Fixes applied to `implementation/`**
None. No implementation defect was found. Notably, `store.touch()` is idempotent per row per request, so the apparent double-bump at `governance.py:394-395` (`refresh_asset_counts` followed by `touch`) yields exactly the one increment PRD 2.9 mandates for the expiry cascade — this was verified before concluding the version numbers were the tests' error and not the server's.

ORCHESTRATOR VERIFICATION: independently re-read all 8 results files from disk after the subagent exited — 8 files present, each `{"passed": 104, "total": 104, "failed": 0, "errors": 0}`; sentinel SWEEP_DONE = 2026-09-06T02:37:02Z. The sweep artifacts are real, not a claimed-clean-with-no-files case. Step 8 is NOT skipped: Step 7 made 4 test_suite fixes (including 2 partial-coverage assertion removals over a genuine PRD silence), so the skip condition (0 deletions AND 0 test_suite AND 0 test_helpers AND 0 implementation fixes) does not hold.


## Step 8: Finalize PRD — 2026-09-06T02:42:28.000Z

`PRD_FINALIZED.md` written. **One edit total.**

### Line counts
- `PRD.md`: 430 lines / 104,105 bytes; `PRD_FINALIZED.md`: 430 lines / 104,450 bytes. Line delta 0.0% (one long line revised in place). `diff` reports 1 changed line (`186c186`). Byte delta +345 (+0.33%). Last line byte-identical to PRD.md's, so the file still ends at the same clean §5 error-table boundary.

### Change
- **§3.1 (Planning a Campaign and Its Editorial Calendar), line 186 — insert — states that calendar-slot creation carries no campaign-`status` precondition (permitted against `PLANNING`, `ACTIVE` and `CLOSED` campaigns alike, never yielding `ERR_CAMPAIGN_STATE_INVALID`) — `implementation/r_campaigns.py:122-150`** (`create_slot` resolves the campaign at line 125 and never reads `campaign["status"]`). This single edit covers BOTH step_7_diff items 1 and 2, which share one root cause.

### Pre-edit search log
**Edit 1 — §3.1 slot creation**
- **(a) Subject:** campaign-`status` (operator axis) as a precondition on writes, specifically on calendar-slot endpoints.
- **(b) Impl paths enumerated** (`grep -rn 'CAMPAIGN_STATE_INVALID|campaign["status"]'`, then each site read): `r_campaigns.py:122-150` `create_slot` — no status check (Step 7 site); `r_campaigns.py:184-192` `lock_slot` — also no campaign-status check (only `slot["status"] not in ("OPEN","FULL")`); `r_campaigns.py:48-58` `activate_campaign` — guards `PLANNING`; `r_campaigns.py:61-99` `close_campaign` — guards `ACTIVE`; `r_briefs.py:56-58` `create_brief` — requires `ACTIVE`; `r_briefs.py:94-98` `assign_sme` — requires `ACTIVE` and calls `require_not_frozen`; `r_items.py:66-67` `create_item` — requires `ACTIVE`; `r_items.py:364-365` `refresh` — requires `ACTIVE`. Also checked ladder rungs 7 and 15 (`PRD.md:98,106`): rung 15 applies to transition endpoints only and slot creation is not one, so no contradiction; rung 7's site list already includes slot-create, untouched.
- **(c) Wording adjustments, both narrowing:** (1) rejected strengthening §2.8's `status`-axis sentence into an exhaustive list, because `r_briefs.py:96` (`assign-sme`) also requires `ACTIVE` and is absent from that enumeration — any exhaustiveness claim there would be a new false universal; §2.8 left verbatim. (2) dropped a drafted "the only 409 the endpoint can raise" clause and kept the sentence scoped to slot *creation* rather than "the calendar-slot endpoints" — `lock_slot` is also ungated but that extension has no step_7_diff warrant.

### Items that need NO edit
- **Item 3** (`assert_version(after_slot, 1)` -> `2`): no PRD silence. §3.4 step 7 already mandates every accepted create rewrites the slot's `committed_points` and `utilization_pct`, and §2.4 already says `version` increments by exactly 1 on every mutation including cascades. `r_items.py:94-97` writes both fields then calls `touch(slot)` unconditionally. The test mis-counted; §3.1 never claimed the bump was exclusive to the `OPEN -> FULL` edge.
- **Item 4** (three asset-version assertions low by one): no PRD silence. §3.7's attach paragraph already says `active_use_count` and `remaining_licensed_uses` are recomputed and re-derived at each new attachment; with §2.4 that fixes the +1. `governance.py:216-231` (`refresh_asset_counts`) bumps only when a field actually changed — §2.9's "genuine no-op, not a silent re-write" — and a successful attach always moves `active_use_count`. The corrected ledger (create=1 -> attach=2 -> expiry=3 -> renewal=4 -> second expiry=5) is already forced by §3.7's two explicit "The asset's `version` increments by 1." sentences, which also makes `touch()`'s per-row-per-request idempotency at `governance.py:394-395` the PRD-mandated reading rather than an unpinned choice.
- **`test_helpers/` fixes:** none applied, nothing to trace. **`implementation/` fixes:** none applied — consistent with a one-line Step 8 diff.

### Note handed to Step 9 (observed, deliberately not edited — out of Step 8 hard scope)
`PRD.md:160` asserts "Every other operation in the service is indifferent to the posture", but `implementation/r_briefs.py:98` calls `require_not_frozen` on `assign-sme`, which §2.8's four-operation `FROZEN` list does not include. Pre-existing PRD/impl divergence with no step_7_diff item behind it, so left untouched rather than widen scope.

ORCHESTRATOR VERIFICATION: independently confirmed 430 lines both files, `diff` = exactly one changed line at 186, the inserted sentence is the slot-creation/campaign-status clause as described, tail unchanged (`| `ERR_SLOT_CAPACITY_EXCEEDED` | 409 |`), 5 `^## ` headings intact. Step 8 was correctly NOT skipped and correctly produced a near-identical file (0 implementation fixes in Step 7). The `require_not_frozen` / §2.8 divergence has been forwarded to Step 9 as a mandatory reconciliation item.


## Step 9: Complete PRD — 2026-09-06T03:31:52.000Z

Run as FIVE sequential module-partitioned passes over one shared `workspace/PRD_COMPLETED.md` (a single monolithic pass cannot hold 3,058 impl lines plus a 104KB PRD; a single pass also historically produces a byte-identical no-op). Pass 1 did the `cp`; passes 2-5 edited in place and were forbidden from re-copying. Partition: pass 1 = global/cross-cutting layer (app, auth, envelope, errors, listing, store, timeutil, serialize, validate); pass 2 = calc + governance; pass 3 = r_campaigns/r_experts/r_briefs/r_gates/r_claims/r_assets/r_ops; pass 4 = r_items; pass 5 = reconciliation. Every pass was forbidden to read SCAFFOLD*.yaml and worklog.md.

**Cumulative result: 430 lines / 123,422 bytes (from PRD_FINALIZED.md's 430 / 104,450) — +18,972 bytes, 47 changed lines, 0 lines added or removed, 0 new sections, 57 edits.**

### PASS 1 — global layer (11 edits: 9 ambiguity-pins, 2 mismatch-revisions)
`cp` confirmed. 430/104,450 -> 430/108,973. Lines touched: 42, 43, 72, 74, 76, 80, 95, 148, 164, 314, 371.
- §2.2 (42) revise/ambiguity — `api_request_id` = `req_` + exactly 20 chars from `A`-`Z`/`0`-`9`, 24 total — `envelope.py:14,32-33`
- §2.2 (43) insert/ambiguity — `api_request_timestamp` is host real time, not the logical clock, unaffected by `set_current_utc` — `envelope.py:36-40`, `timeutil.py:93-95`
- §2.3 (72) insert/ambiguity — empty `limit`/`offset` falls back to default; non-integer is `ERR_INVALID_REQUEST` 400 like out-of-bounds; `offset` has no upper bound — `envelope.py:74-90`
- §2.3 (74) insert/ambiguity — universal tie-breaker for every stated ordering (`created_at` asc then `id` asc; `id` asc alone for the campaign collection) — `listing.py:25-37`, `store.py:39-40`
- §2.3 (76) insert/ambiguity — a filter value outside the declared set, or empty, is not a 400: it matches no rows (200, empty `data`, `total_count` 0); undeclared query params ignored — `listing.py:8-22`
- §2.4 (80) insert/ambiguity — `created_at`/`updated_at` are host-wall-clock audit stamps, not the logical clock; `updated_at == created_at` at creation; stamps strictly increase so `created_at` is unique and the default order total; `week_start_date` renders bare `YYYY-MM-DD`; array fields keep client order; store starts empty — `store.py:24-33,59-65`, `timeutil.py:65-68`, `serialize.py:35,48,62,95,163`, `app.py:3-4`
- §2.5 rule 4 (95) insert/ambiguity — accepted instant grammar (`T` or space separator, 1-9 fractional digits, optional `Z`/`+-HH:MM`, no designator = UTC, sub-ms truncated not rounded); strict zero-padded dates; absent/unparseable body treated as `{}` and `Content-Type` never inspected; non-object body rejected; explicit `null` == omitted; integer fields reject booleans and decimal-point numbers; string fields reject `""` except optional free-text notes — `timeutil.py:9-51`, `validate.py:36-46,49-66,69-81,106-131`
- §2.7 (148) revise/mismatch — decimals serialise as UNQUOTED JSON numbers retaining both places (`0.00`, never `0`, never `"0.00"`); evidence `weight` added to the 2-dp list — `envelope.py:25-46`, `serialize.py:150`, `calc.py:46-49`
- §2.9 (164) revise/mismatch — a row changed by two steps of the same cascade is stamped/bumped ONCE per request, reconciling the general rule with §3's "version increments by 1" — `store.py:43-56`, `auth.py:54`
- §4 intro (314) insert/ambiguity — unrouted path -> `ERR_NOT_FOUND` 404; declared path with wrong method -> `ERR_INVALID_REQUEST` with HTTP 405; both regardless of headers (routing precedes the ladder); trailing slash insignificant — `app.py:24,36-47`
- §5 intro (371) insert/ambiguity — `ERR_NOT_FOUND` (404) and `ERR_INTERNAL` (500) named as the two transport-level ids outside the table, plus the 405 carve-out — `app.py:38-52`, `errors.py:60`
Exhaustiveness evidence: machine-diffed every `@endpoint(...)` role tuple in all eight route modules against the §4 table — all 50 rows match exactly. `ERROR_HTTP` diffed against §5 — every catalogue row matches impl status; only `ERR_NOT_FOUND` was absent from the table (now pinned in prose). Every response key of all 12 serialisers machine-checked against the PRD — all present and backticked.

### PASS 2 — calc + governance (8 edits: 4 ambiguity-pins, 4 mismatch-revisions)
430/108,973 -> 430/110,624. Lines touched: 156, 238, 240, 266, 288, 302, 306, 308.
- §3.11 (306) revise/mismatch — step 6's decay recompute iterates only items still `PUBLISHED`, so step-3 flagged items are SKIPPED and keep their prior `decay_pct`/`refresh_required` (PRD said step 6 sees them) — `governance.py:437-438`
- §3.11 (308) revise/mismatch — step 8 reconciles EVERY campaign in the store, not only those touched by steps 1-7; untouched ones reconcile to identical values and are not `touch`ed — `governance.py:458-459,132-169`
- §3.7 (266) revise/mismatch — expiry-cascade step 4 accepts `SUPPRESSED` OR `RETRACTED` (PRD said every row is now `SUPPRESSED`); material because a refreshed-then-republished item still carries old `RETRACTED` rows — `governance.py:407-408`
- §3.10 (302) revise/mismatch — same widening for the sweep's `PUBLISHED -> NEEDS_REFRESH` edge; also pinned that the distribution test is step 3 and runs BEFORE step 4's claim-expiry suppressions — `governance.py:404-411,413-426`
- §3.5 (238) insert/ambiguity — voiding a gate rewrites only `state`, `decided_at`, `sla_breached`; `decided_by_user_id`, `decision_notes`, `turnaround_hours` are left standing — `governance.py:308-319`, `serialize.py:109-123`
- §3.5 (240) insert/ambiguity — reopening a gate at resubmit does NOT clear `decision_notes`; the superseded note survives into the new `PENDING` state — `governance.py:295-305`
- §3.9 (288) insert/ambiguity — an item with `published_at` null has no baseline window, falls into the baseline-sum-0 branch, reads `decay_pct` 0.00 — `calc.py:212-214`
- §2.8 (156) insert/ambiguity — every posture recompute also re-derives `committed_points_total` as the sum of slot `committed_points`, not incrementally — `governance.py:154,160-168`
**Pass-1 decimal-quantization hand-off: CHECK PASSES, no narrowing needed.** Exactly six Decimal fields reach a response (`utilization_pct`, `decay_pct`, `turnaround_hours`, `required_score`, `evidence_score`, `weight`); every write path produces exactly 2 dp via `rhu(...,2)`, `ZERO2`, or a 2-dp literal. The 3-dp intermediate `evidence_contribution` is never stored.

### PASS 3 — route modules except r_items (18 edits: 9 mismatch-revisions, 9 ambiguity-pins)
430/110,624 -> 430/115,668. Lines touched: 17, 100, 102, 113, 119, 160, 192, 198, 208, 210, 232, 234, 236, 246, 248, 252, 268.
- §2.1 (17) revise/mismatch — `ManagingEditor` was "the only role that creates resources and the only role that may waive a review gate"; both false (evidence rows also created by SME, snapshots only by AnalyticsService; a gate's own reviewer may submit `WAIVED`) — `r_claims.py:28`, `r_gates.py:36-38,58-60`
- §2.5 rung 9 (100) revise/mismatch — added `POST /editorial/briefs` to the body-FK rung — `r_briefs.py:30,56`
- §2.5 rung 11 (102) revise/mismatch — the `ManagingEditor` exception is NOT conditioned on waivability; a ME `WAIVED` clears rung 11 for any `gate_type` and is refused at rung 26 instead — `r_gates.py:36-38`
- §2.5 rung 22 (113) revise/mismatch — frozen-posture list extended with `assign-sme` and `submit-for-review` — `r_briefs.py:98`, `r_items.py:145`
- §2.5 rung 28 (119) revise/mismatch — `ERR_EXPERT_UNAVAILABLE` also guards `POST /briefs/{id}/approve` — `r_briefs.py:137`
- §2.8 (160) revise/mismatch — "refuses four operations" -> six, enumerated — five `require_not_frozen` sites plus the waiver's `require_open_posture`
- §3.2 (192) revise/mismatch — HAND-OFF 1 resolved: PRD loosened to match impl. Each `expertise_tags` entry is a 1-40-char string that must equal its own lower-cased form; the single-word/hyphen shape is an UNENFORCED naming convention (space and underscore accepted, no pattern check); no uniqueness rule — `r_experts.py:21-22`
- §3.2 (198) revise/ambiguity — HAND-OFF 2 resolved: supplying the status the expert already holds (either direction) is `ERR_INVALID_REQUEST` 400, not a state conflict — the catalogue declares no expert-state error and the check sits in the request-shape rung — `r_experts.py:42-44`
- §3.3 (208) insert/ambiguity — `expected_expert_version` carries no range; any non-matching integer incl. 0/negative is 412, not 400 — `r_briefs.py:86`
- §3.3 (210) revise+insert/ambiguity — approve's three checks in impl order (ownership 10 -> brief state 15 -> expert status 28); the expert's ledger is recomputed but unchanged so its `version` does NOT move (contrast assign-sme's unconditional stamp); request-changes `notes` <=2000 chars, empty allowed, validated before the ownership check, not stored — `r_briefs.py:133-141,150`
- §3.5 (232) insert/ambiguity — gate state tested before item state: `ERR_GATE_ALREADY_DECIDED` beats `ERR_ITEM_STATE_INVALID` — `r_gates.py:50-53`
- §3.5 (234) insert/ambiguity — an omitted `decision_notes` is written as null, replacing a note carried over from a superseded decision — `r_gates.py:24,65`
- §3.5 (236) revise/mismatch x2 — HAND-OFF 3 resolved: the join is evaluated over EVERY gate row the item holds (the fan-out three or four PLUS any `LEGAL` gate a resubmission added — the old "opened at fan-out" wording was independently wrong for that case), admitting only when each reads `APPROVED`/`WAIVED`, so any other state incl. `VOIDED` holds it in `IN_REVIEW`. Also: `WAIVED` is not reserved to `ManagingEditor` (a Brand/Accessibility reviewer may waive its own dimension) and posture (22/23) is tested BEFORE waivability (26) — `r_gates.py:37-38,54-60,74-77`
- §3.6 (246) insert/ambiguity — `collected_at` after the clock is `ERR_INVALID_REQUEST` 400 — `r_claims.py:36-37`
- §3.6 (248) insert+revise — claim state tested before the item-`PRUNED` check (a `SUBSTANTIATED` claim on a `PRUNED` piece gives `ERR_CLAIM_STATE_INVALID`); the posture recompute happens on ALL FOUR evidence edges, not only `EXPIRED -> EVIDENCE_PENDING` — `r_claims.py:41-46,67`
- §3.6 (252) insert/ambiguity — decide re-scores the claim after the state check and before both tests, and a call refused with `ERR_EVIDENCE_EXPIRED`/`ERR_EVIDENCE_INSUFFICIENT` LEAVES the recomputed `evidence_score` on the row without stamping `updated_at`/`version` (no rollback) — `r_claims.py:81`
- §3.7 (268) revise/ambiguity — "Steps 2 and 3 are genuine no-ops" -> "Steps 2, 3 and 4": step 4 reconciles exactly the campaigns behind the usages step 2 revived — `r_assets.py:76-102`

### PASS 4 — r_items.py (13 edits: 11 ambiguity-pins, 2 mismatch-revisions)
430/115,668 -> 430/120,940. Lines touched: 140, 216, 218, 228, 244, 262, 274, 290, 296, 298.
- §2.6 (140) insert/ambiguity — HAND-OFF 4: `expected_campaign_version` rangeless; any non-matching integer incl. 0/negative is 412, not 400 — `r_items.py:40`
- §3.4 (216) revise/mismatch — "they are only tested at publication time" was literally false: create DOES shape-check the three metadata fields with the same bounds (`meta_description` 1-200, `url_slug` 1-80 kebab, `tags` entries 1-40 lowercase, no cap on count); only the accessibility floor and slug-uniqueness are deferred — `r_items.py:43-48`
- §3.4 (218) insert x2/ambiguity — `ERR_BRIEF_NOT_APPROVED` precedes `ERR_CAMPAIGN_STATE_INVALID` on create; body FKs resolve `brief_id` before `slot_id` (both bogus => `ERR_BRIEF_NOT_FOUND`) — `r_items.py:56-57,64-67`
- §3.5 (228) insert/ambiguity — a submission from `DRAFT` always opens FRESH gate rows and never reopens existing ones, so a piece resubmitted after a refresh carries the refresh's `VOIDED` rows alongside new `PENDING` ones — `r_items.py:147,152-156`
- §3.6 (244) insert/ambiguity — attaching a claim has NO workflow-state precondition (DRAFT/RETRACTED/PRUNED all accepted), explicitly noted as the opposite of the evidence-filing rule — `r_items.py:169-181`
- §3.7 (262) insert/ambiguity — attaching a usage has no workflow-state precondition either, and exclusivity compares only against OTHER items, so one piece may hold several `ACTIVE` usages of one asset on one channel, each consuming a licensed use — `r_items.py:433-478`
- §3.8 (274) revise/mismatch — `channels` is 1-3 distinct entries (empty list/duplicate => 400); the three metadata fields are OPTIONAL at publish and each independently falls back to the value stored on the item when omitted or null, while a supplied value overwrites; an explicitly empty `tags` array replaces rather than falls back; kebab-case spelled out (no leading/trailing/doubled hyphen); `meta_description` min 1 — `r_items.py:205-227,246-251,278-280`
- §3.9 (290) revise+insert x3 — `accuracy_finding` required only for `ACCURACY`, still enum-validated on a `DECAY` audit (400 if bogus) then ignored; "live" dropped from "a judgement about a live piece". HAND-OFF 1: an accuracy audit ALSO rewrites `refresh_required`, re-derived from the STORED `decay_pct` + brief funnel stage + newly written `accuracy_status` without recomputing `decay_pct` (`INACCURATE` => true; `VERIFIED`/`UNVERIFIED` clears it when stored decay is below threshold). HAND-OFF 3: the audit has NO workflow-state precondition (DRAFT/IN_REVIEW/RETRACTED/PRUNED accepted); only a `PUBLISHED` item is moved by the verdict; a decay audit with `published_at` null takes baseline 0, stores `decay_pct` 0.00 and comes out `KEEP` unless already `INACCURATE` — `r_items.py:325-352`, `governance.py:348-352`
- §3.10 (296) insert/ambiguity — retract's `reason` is optional, <=2000 chars, accepts `""`, validated ahead of the state check, not stored and not in the response — `r_items.py:307`
- §3.10 (298) insert x2/ambiguity — refresh's three preconditions do NOT run in prose order: rung 15 campaign-state -> rung 18 eligibility -> rung 22 posture, both error pairs spelled out; refresh leaves `last_audit_type`, `last_audit_at` and `decay_pct` standing (only `last_audit_verdict`, `accuracy_status`, `refresh_required` and the publish/retract stamps reset) — `r_items.py:360-380`
HAND-OFF 2 (`PRUNE_DECAY_PCT` is `>=`): NO EDIT — §3.9's "has reached 85.00 percent" is the same inclusive idiom line 288 already uses for a `>=`, so the boundary is unambiguous. HAND-OFF 5 (frozen list): VERIFIED CORRECT, not touched — `require_not_frozen` fires at `r_items.py:74,145,237,370` plus `r_briefs` assign-sme and `r_gates` waiver = exactly pass 3's six. HAND-OFF 6: no conflict; `r_claims.py:44-47` fires only for a `PRUNED` owning item after the claim-state test, exactly as line 248 says.

### PASS 5 — RECONCILIATION (7 edits; closed every cross-pass item rather than re-reporting it)
430/120,940 -> 430/123,422. Superset check passed: of the 46 `>` lines pre-edit, 40 are verbatim and 6 were co-edited, each re-verified to still contain its prior pass's inserted text (15/15 substring probes OK).
- **A. §2.5 rung 4 false universal — FIXED, and the hand-off list was itself wrong.** Grepped every `v.body()` call site against every `@bp.post`: the real set of body-less write endpoints is EIGHT, not seven — the seven forwarded plus `POST /editorial/briefs/{id}/approve` (`r_briefs.py:129`). Second inaccuracy corrected: a body of the bare literal `null` is NOT rejected (`request.get_json(silent=True, force=True)` returns `None`, so `validate.body()` returns `{}` and it takes the absent-body path). Rewrote the clause to reject only "a JSON array, string, number or boolean", scoped both body rules to endpoints that read a body, and enumerated the eight.
- **B. §3.7 non-ladder enumeration — FIXED.** `r_items.py:453-478` runs 31 -> 32 -> 33 -> 37 -> 39; prose reordered to match with positions named, plus the one precedence consequence a reader would get backwards (`ERR_ASSET_RIGHTS_EXPIRED` beats `ERR_ASSET_CHANNEL_NOT_LICENSED`).
- **C. §2.5 rung 27 — FIXED.** `r_items.py:248-252` fails on three legs: `meta_description` present and >=50, `url_slug` PRESENT, `len(tags)` >=2. Added the slug leg and pinned that a null slug skips rung 7 entirely, so it fails at 27 rather than at uniqueness.
- **D. §2.8 "every other operation is indifferent" — VERIFIED TRUE, ambiguity closed.** The only posture reads in any request path are `require_not_frozen` (`r_briefs.py:98`, `r_items.py:74/145/237/370`) and `require_open_posture` (`r_gates.py:56`) — exactly pass 3's six. But it was ambiguous: the gate check sits inside `if waiver:`, so five refusals are endpoint-wide while the sixth is decision-scoped. Added that distinction.
- **E. §2.6 lines 140/144 — already consistent, no change.** `v_int(body,"expected_campaign_version")` carries no `minimum`/`maximum`; line 144 concerns OTHER endpoints and no validator rejects undeclared body keys, so "supplying one has no effect" is true.
- **F. Stale `RETRACTED` distribution rows — already consistent, no change.** `governance.distributions_of_item` (`governance.py:102`) filters on `content_item_id` only; `list_item_distributions` applies just `channel`/`state`. Nothing prunes or hides superseded rows and neither §2.3 nor §3.8 implies otherwise (§3.8 only says `RETRACTED` is terminal). Pass 2's §3.7/§3.10 revisions rest on solid ground.
- **G. Cross-pass sweep — 3 further defects found and fixed.**
  * §3.11 step 4 vs §3.8 (280): step 4 said claim expiry suppresses "the distribution rows of their PUBLISHED or NEEDS_REFRESH items" unqualified, but §3.8's edge set admits only `SCHEDULED -> SUPPRESSED` and `LIVE -> SUPPRESSED`; ground truth `governance.py:395-398` = only `SCHEDULED`/`LIVE`. Qualifier added. (Pre-existing in PRD_FINALIZED, not pass-introduced.)
  * §3.6 claim decide: prose named `ERR_EVIDENCE_INSUFFICIENT` before `ERR_EVIDENCE_EXPIRED`, but `r_claims.py:82-90` checks expiry first (rungs 36 < 38). Real precedence pinned.
  * §3.8 line 274 (pass-4 overstatement): "Every check in the next paragraph ... reads these post-fallback values" is false for the SoD, state, claim, `scheduled_at` and channel checks, which never touch the three metadata fields. Narrowed to the checks that read them.
- **Universals re-verified as TRUE (no change):** pass 1's `created_at` totality (`store.stamp()` force-bumps 1 ms, `now_wall()` truncates to ms, so rendered stamps strictly increase); empty-valued `limit`/`offset` -> default and out-of-set filters -> 0 rows; the tie-break rules (`sort_gates`/`sort_distributions`/`sort_by` all pre-sort `by_created`); `req_` + 20 chars; pass 3's per-request single `version` bump (`store.touch` dedupes on `g.touched`); pass 2's sweep step 6 (`PUBLISHED`-only) and step 8 (all campaigns); pass 4's rung-11/26 hedging, which survives rung 12 SoD firing before rung 26 on a ManagingEditor waiver of a LEGAL gate.
- **No known PRD-vs-implementation divergence remains unresolved.** One deliberate non-edit: sweep step 3 requires a non-empty distribution list (`if dists and all(...)`), where the PRD's "every distribution row" reads vacuously true for zero rows — unreachable, since publication mints 1-3 rows and is the only path into `PUBLISHED`, so narrowing there would document behavior no client can observe.

### ORCHESTRATOR VERIFICATION
- `workspace/PRD_COMPLETED.md` = 430 lines / 123,422 bytes; 5 `^## ` headings; tail is `| `ERR_SLOT_CAPACITY_EXCEEDED` | 409 |` (same clean §5 boundary as PRD.md).
- `cmp` vs PRD_FINALIZED.md: DIFFERS (not the byte-identical no-op failure mode). `diff` shows 47 changed lines.
- No re-sweep needed after Steps 8-9: newest mtime under `workspace/implementation/` is 01:39:35 and newest under `test_suite/`/`test_helpers/` is 02:33:40, both PRE-dating `results.1.json` at 02:37:02 — so the verified 8x 104/104 green sweep covers exactly the code now on disk, and Steps 8-9 modified only PRD documents.

