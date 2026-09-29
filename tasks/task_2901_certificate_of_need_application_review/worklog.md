## Step 1: Create task directory — 2026-09-05T13:44:40.408143228Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2901_certificate_of_need_application_review and its workspace/ subdirectory. Index 2901 was pre-assigned by the orchestrating prompt (no scan/auto-allocation performed, per concurrency constraint).

## Step 2: Generate scaffold — 2026-09-05T15:12:04.816868757Z

Done — all three scaffold artifacts for task 2901 are complete and the lint is clean.

**Files** (in `/home/ubuntu/github/CodingPRD/tasks/task_2901_certificate_of_need_application_review/`):

| file | lines |
|---|---|
| `SCAFFOLD.yaml` | 2814 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1841 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4659 |

`ls -la` confirms only those three plus the pre-existing `worklog.md` and `workspace/`; sizes 143679 / 120581 / 304640 bytes.

**Verdict block, verbatim:**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    56
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     63
  Calls scanned (§1.8+§1.9):  957

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Shape of the output**
- `SCAFFOLD.yaml` top-level keys: scenario, domain_name, api_prefix, complexity_profile, difficulty_level, response_envelope, entities (15), state_machines (7), concurrency_rules (3), calculations (6), validations (30), endpoints (56), errors (57), roles (7). Neither `scaffold_difficulty_design` nor `scaffold_corner_design` appears in it.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`: single key, 9 rule_ids × 2 instances = 18.
- `SCAFFOLD_CORNER_DESIGN.yaml`: single key, all nine §1.9 sections — entities 10, state_machines 9+3 stubs, calculations 6+5, validations 13+1, endpoints 3+2, errors 14+6, rbac 3, cross_cutting_complexity_layers 4+2, consistency_model 1 → 63 recipes + 19 `excluded_because` stubs. Every instance has exactly one of `test_recipe` / `excluded_because`; names are unique within the file and disjoint from the §1.8 names.

**Notable design decisions**
- The "Generate task harder than expert level!" directive was deliberately kept out of `scenario:` (encoded only as `difficulty_level: expert_plus`) so it cannot leak into PRD.md; a grep for "harder" in SCAFFOLD.yaml returns nothing.
- Error-catalog coverage: every one of the 57 error ids is now triggered by a §1.8 or §1.9 recipe except `ERR_APPLICANT_STANDING_RESTRICTED`, which needs two independent compliance strikes; a YAML comment in the errors section records that this corner rides on the §1.8 instance `transitive_cascade / progress_report_breach_depth_three_suspension_strike_cascade` rather than getting its own ~60-call chain.
- Two lint/consistency bugs found and fixed while writing: an assert referenced a non-existent `PublicHearing.cancellation_reason`, and the consistency_model instance captured `$.data.decided_at` from `POST /batching-cycles/{id}/comparative-decision`, but §1.1 BatchingCycle has no `decided_at` (replaced with `reopened_count`, and the decision timestamp is now asserted as `Application.decision_at`).
- All arithmetic in the new sections is pre-computed: expenditure ceiling 1050000000 (1.05 × 1000000000), boundary walk 1000000000 → 1050000000 → 1050000001, extension grants 365 then min(200,365,175)=175 with milestones 2028-06-29 and 2028-12-21 (verified with date arithmetic), unallocated pool 19 − 12 = 7, comparative scores 78.65 (one sheet) / 79.40 (two sheets).

**Orchestrator verification:** all three files parse as YAML; SCAFFOLD.yaml contains no difficulty-directive text (only `difficulty_level: expert_plus`); workspace/ and worklog.md survived the subagent.

## Step 3: Copy shared files — 2026-09-05T15:12:04.834949677Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-05T15:28:32.111279202Z

PRD.md is complete at `workspace/PRD.md`.

**Final line count: 483 lines** (109,494 chars, 28 headings). **Last section heading: `## 5. Error Code Catalogue`** — the file ends with the final error row `| `ERR_EXPENDITURE_LIMIT_EXCEEDED` | 422 |`, a real section boundary, no truncation, no audit footer.

Written in 10 calls (1 `Write` + 9 `cat >>` heredocs), each well under the output cap. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced; no sibling task directory was read. All worked examples in the prose were taken from `SCAFFOLD.yaml`'s own `calculations[].note` / `variants[].difference` text.

Structure: §1 Introduction; §2 with 11 subsections (2.1 RBAC, 2.2 verbatim response envelope, 2.3 pagination/filters, 2.4 logical clock and inclusive deadlines, 2.5 identity/audit/version bookkeeping, 2.6 numeric precision and rounding, 2.7 version pinning and stale writes, 2.8 the full 30-rank order of evaluation, 2.9 segregation of duties, 2.10 uniqueness and conserved quantities, 2.11 cascades and the two certificate axes); §3 with 9 workflow subsections (3.1 programme setup -> 3.9 appeals and the reversal cascade); §4 endpoint table; §5 error table.

**Hard Contract reports** (verified with a script against the scaffold, then discarded):

```
Field coverage check:
- entities[].fields: 148 required, 148 present, 0 missing
- endpoints[].request_body (scaffold key `input`): 154 required, 154 present, 0 missing
- endpoints[].query_params: covered within the 154 `input` identifiers, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 30 checked, 30 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 50 checked (8 machines incl. both Certificate axes), 50 fully expressed, 0 missing
- calculations[]: 6 checked plus 4 variants, 10 fully expressed, 0 missing
- validations[] conditions: 30 checked, all matchable to their error_id in prose; all 57 error IDs appear in §1-§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 78 side-effect items and 30 applies_to scopes checked, all expressed, 0 missing
- entities[].fields[] structured content: 148 checked, all reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 groups checked (LOI project/aggregated basis, occupancy base/high-volume, CASH/ACCRUAL, award full/partial/denied, appeal AFFIRMED/REVERSED/REMANDED, hold APPLY/LIFT, cert modify bed/money/date, hearing cancel/reschedule, threshold cost/bed/always-reviewable), 9 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 973
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional cross-checks: §4 has exactly 56 rows x 4 columns and its method/path/role sets match `endpoints[]` exactly (0 mismatches); §5 has exactly 57 rows x 2 columns matching `errors[]` id/http exactly. Two wording passes removed a meta use of the word "difficulty" from §1 and two uses of "endpoint" meaning an interval bound in §3.2.

**Orchestrator truncation check (mandated by the run prompt):** `wc -l` = 483; `tail -25` shows the file ending on the complete final row of the §5 error table, i.e. a real section boundary, not mid-sentence. A grep for `harder`, `expert level`, `scaffold`, `test_recipe` returns zero hits — no difficulty-directive or test-index leakage. PRD accepted without regeneration.

## Step 5: Generate unit tests — 2026-09-05T16:39:01.318467239Z

Stage 5 is complete. All 19 test modules plus `conftest.py` are generated at the task root, and both audits pass clean.

## Output (all at the task root, nothing under `workspace/`)

**`test_helpers/`** — `__init__.py` 74, `api_client.py` 310, `api_errors.py` 131, `assertions.py` 337, `constants.py` 166, `factories.py` 198, `fixtures.py` 599, `test_users.py` 78, `types.py` 436.

**`test_suite/`** — `conftest.py` 61; queue A: `test_01` 181, `test_02` 218, `test_03` 179, `test_04` 199, `test_05` 187, `test_06` 199, `test_07` 147, `test_08` 154, `test_09` 214, `test_10` 203; queue B: `test_11_entity_shapes` 426, `test_12_state_machines` 414, `test_13_calculations` 410, `test_14_validations` 600, `test_15_endpoint_behaviour` 179, `test_16_error_codes` 842, `test_17_role_access` 118, `test_18_concurrency_layers` 399, `test_19_consistency_model` 98. Total 7757 lines including helpers.

## Coverage audit
- **Difficulty (queue A): 18/18 non-stub instances covered**, every one by >=2 tests (the skill's queue-A minimum) — 47 tests.
- **Corner (queue B): 63/63 non-stub instances covered**, exactly one test each — entities 10, state_machines 9, calculations 6, validations 13, endpoints 3, errors 14, rbac 3, cross_cutting_complexity_layers 4, consistency_model 1. The 19 `excluded_because:` stubs were not translated.
- **110 tests, 110 `Design:` tags** — one per test, always the docstring's last line, zero dangling/unknown tags, zero dual-tags.

## Verification run over all files
- `ast.parse` clean on every file; 270 `PRD §...: "..."` citations all survive whitespace-normalised literal matching against `PRD.md` (0 misses); zero unused imports (fixed 4 stale ones in `test_01`); all 56 `ApiErrorId` members asserted appear in PRD *prose*, not just the §5 table; no `skip`/`skipif`/`xfail`; no test docstring lacks a PRD citation; no file mentions "scaffold"; every symbol imported from `test_helpers` and every `api_client.<method>` (56) resolves statically.

## Design-index deviations applied this session (PRD wins)
- `Corner/rbac/applicant_cannot_run_the_comparative_decision...`: the design asserts cycle status `ANNOUNCED` and `decided_at == null`. Neither exists in the PRD — asserted `OPEN_FOR_LOI` and dropped the `decided_at` clause (the cycle has no such field).
- `Corner/cross_cutting_complexity_layers/occ_score_sheet_revision...`: the design's follow-up asserts the resent sheet moves `comparative_score` to **79.40**, but its own actor is reviewer `rev-1` twice, so §3.7 supersession leaves exactly one ACTIVE sheet and the PRD uniquely derives **79.25**. Kept the design's actor, corrected the number, and added the PRD-derived `SUPERSEDED` assertion on the first sheet.
- `Corner/cross_cutting_complexity_layers/occ_certificate_reissue...`: deliberately did **not** assert the addressed row's `expenditure_status` after the successful reissue — §3.8 line 333 ("when the limit rose ... `LIMIT_AMENDED`") and line 335 (reachable only from `OVER_LIMIT_PENDING_AMENDMENT`/`LIMIT_BREACHED`) conflict for a `WITHIN_LIMIT` predecessor, so the outcome is not uniquely derivable. The design's `?superseded_certificate_id=` list filter *was* used — §2.3 explicitly declares it.

## Constraints honoured
Scratch confined to `/tmp/task_2901_tests/`; no `pkill`; no server started or stopped; `worklog.md` never read or written; no sibling task directory touched. Removed a generated `test_helpers/__pycache__/`.

**Orchestrator verification:** `test_helpers/` (9 files) and `test_suite/` (20 files) are at the task root; no stray copy exists under `workspace/`.

## Step 6: Generate implementation — 2026-09-05T16:39:01.325075030Z

Implementation complete and verified.

## Deliverable

`workspace/implementation/` — 18 Python modules + `requirements.txt` (`flask>=3.0`) + executable `start.sh`, 2854 lines total. Per-file line counts:

| file | lines | file | lines |
|---|---|---|---|
| start.sh | 7 | shape.py | 199 |
| auth.py | 47 | cascades.py | 226 |
| envelope.py | 65 | r_participation.py | 232 |
| r_scoring.py | 66 | r_cycles.py | 246 |
| store.py | 77 | r_applications.py | 252 |
| errors.py | 80 | services.py | 258 |
| app.py | 88 | r_certificates.py | 270 |
| r_loi.py | 122 | clock.py | 123 |
| r_config.py | 184 | calc.py | 161 |
| r_appeals.py | 150 | | |

`start.sh` reads `$PORT`, installs Flask only if missing, and `exec python3 app.py` in the foreground; `app.py` binds `0.0.0.0` with `threaded=True`, no reloader. Storage is module-level Python dicts in `store.py`, empty on every boot — `grep` for `sqlite3|shelve|pickle|open(...,'w')|json.dump` returns nothing, and there is no seeding path. `__pycache__` was removed so the directory holds only source.

## Structure

`errors.py` (all 57 error IDs -> HTTP status), `clock.py` (logical clock defaulting to `2026-08-01T00:00:00Z`, Decimal/ROUND_HALF_UP helpers), `envelope.py` (meta/data envelope, pagination meta, `public()` stripping `_`-prefixed keys), `store.py`, `auth.py` (401-then-403 over the 7 roles), `shape.py` (body/field/pagination validation), `calc.py` (the 6 calculations), `services.py` (typed 404s, guards, recomputation), `cascades.py` (progress-report application, lapse sweep, reversal/remand, comparative decision), plus 8 route blueprints covering all 56 endpoints.

## Verification

Three end-to-end smoke scenarios, each against a freshly booted server (ports 27413/27414/27415, all killed by exact PID afterwards; zero listeners remain and no broad kill was used). ~200 assertions total, all green, with 0 tracebacks and 0 500s in the server logs.

Confirmed values include: need methodology 135000 / 493.1507 / 0.85 / 436 / 336 and the base-tier variant 30000 / 109.589 / 110; comparative_score 79.70 (per-criterion means rounded to whole points before weighting — not 79.45); waterfall full 100 + partial 62 with the pool driven to 0; `appeal_window_closes_at` = decision + 30 days; ceiling 1,050,000,000; extension `min(400, 365, 540) = 365`; accrual breach -> LIMIT_BREACHED + SUSPENDED + strike; modification -> old row SUPERSEDED/LIMIT_AMENDED with lineage on the successor; the 5-link REVERSED cascade unwinding beds, cents, score, sheets (STALE) and cycle `reopened_count`/pool; formula amendment -> stale pin -> `ERR_FORMULA_VERSION_STALE` -> re-pin on recompute; 24-month LOI aggregation (550,000,000 / 6 beds -> REVIEWABLE, `AGGREGATED_24_MONTH`) and always-reviewable service types; lapse sweep flipping the certificate to LAPSED while unwinding the area conserved quantities and charging a strike; pagination `has_more`/`total_count` and filter behaviour.

Ambiguity resolutions are noted where relevant in module docstrings; the notable ones were placing `ERR_NEED_EXHAUSTED` between ranks 20 and 25 per §3.8, reporting the intervention self-filing mismatch as `ERR_NOT_AFFECTED_PARTY` per §3.6, and mapping the application-withdrawal state violation to `ERR_APPLICATION_NOT_SUBMITTABLE` (rank 8 defines no dedicated code).

**Orchestrator note:** Steps 5 and 6 were launched concurrently in a single assistant message, so `test_suite/` did not exist when the implementation subagent started — physical isolation held. The two subagents independently report different comparative-score arithmetic (tests 79.25, impl 79.70); that divergence is left for Step 7 to adjudicate against PRD prose.

## Step 7: Run tests and iterate — 2026-09-05T16:53:29.988102240Z

All 8 rounds are green. Exit criterion met.

## Summary

**Iterations run: 2**

### Iteration 1 (baseline)
8/8 rounds: `110 total, 109 passed, 1 failed, 0 errors` (~197s/round). No flakiness, no `ServerStartError`, no load-induced timeouts — the same single test failed deterministically in all eight rounds:

`test_12_state_machines.py :: TestCompletenessReviewLoopGuards :: test_an_open_deficiency_notice_blocks_the_deem_complete_declaration`
`AssertionError: Expected error_id 'ERR_COMPLETENESS_REVIEW_NOT_OPEN', got 'ERR_APPLICATION_NOT_IN_COMPLETENESS_REVIEW'`

### Tests deleted: none

### Fixes to `test_suite/`: 1
`test_suite/test_12_state_machines.py` — `test_an_open_deficiency_notice_blocks_the_deem_complete_declaration`, classified **ERROR PRECEDENCE SILENCE** (STEP 1b, non-unique derivability), relaxed per the protocol's explicit `validate_error_is_one_of` exception:

- `validate_error(response, ERR_COMPLETENESS_REVIEW_NOT_OPEN, 409)` -> `assert response.status_code == 409` plus `validate_error_is_one_of(response, [ERR_COMPLETENESS_REVIEW_NOT_OPEN, ERR_APPLICATION_NOT_IN_COMPLETENESS_REVIEW])`. The 409 check is retained explicitly because the runner's `validate_error_is_one_of` does not cross-check HTTP status; every other assertion in the test (refusal, `status == "INCOMPLETE"`, `completeness_round_count == 1`, review still `DEFICIENCY_NOTICE_ISSUED`) is unchanged, so no state-invariant strength was lost. Added the `validate_error_is_one_of` import; corrected the docstring, whose old claim "the application's own status is fine" was contradicted by the test's own `assert application["status"] == "INCOMPLETE"`.

**Why not an implementation change:** PRD §3.5 (line 266) states the notice/cure loop is `COMPLETENESS_REVIEW -> INCOMPLETE on each new notice`, so an application with an open `DEFICIENCY_NOTICE_ISSUED` review is *always* in `INCOMPLETE`. Deem-complete's own gate (§3.5 line 268) admits only `SUBMITTED` or `COMPLETENESS_REVIEW`, so both rules are violated by the same request. PRD §2.8 rank 8 carries both identifiers at the *same* rank, at 409, with no tiebreak — and that rank's text attaches `ERR_APPLICATION_NOT_IN_COMPLETENESS_REVIEW` to the deem-complete state gate while attaching `ERR_COMPLETENESS_REVIEW_NOT_OPEN` only to "a cure". Since §2.8 is declared authoritative for precedence ("Text order elsewhere in this document does not imply precedence; this list does"), `implementation/r_applications.py::deem_complete` checking `_require_completeness_stage` before the open-notice loop is a faithful PRD-only reading. PRD does not uniquely determine which of the two ids wins, so the test, not the implementation, was the defect.

### Fixes to `test_helpers/`: none
No shared-setup-error cluster appeared (0 errors in every round). The >=5-shared-error triage hint never triggered.

### Fixes to `implementation/`: none
No PRD-traceable implementation defect was found. Nothing was added, seeded, or persisted; storage remains in-memory dicts.

### Adjudication of the flagged 79.25-vs-79.70 divergence: non-issue, no change made
`SCORE_AFTER_REVISION = 79.25` (test_15 line 31, test_18 line 35) is correct for a **single** surviving `ACTIVE` sheet holding `SHEET_REV_2` (91/80/65/85/62): 91*0.30 + 80*0.25 + 65*0.20 + 85*0.15 + 62*0.10 = 79.25. With one contributing sheet the per-criterion means are already whole numbers, so PRD §3.7's round-then-weight order is inert. 79.70 is a different scenario — the PRD's own three-sheet worked example, which §3.7 pins verbatim ("The programme's answer is 79.70; the pinned order is the specification"). All four constants re-derived independently: 78.65 (one sheet), 79.40 (two sheets), 79.70 (three sheets), 79.25 (revised single sheet). All correct; the two figures were never in conflict.

### Final 8 rounds (iteration 2)
| round | passed / total | duration |
|---|---|---|
| 1 | 110 / 110 | 206.1s |
| 2 | 110 / 110 | 206.1s |
| 3 | 110 / 110 | 206.0s |
| 4 | 110 / 110 | 206.1s |
| 5 | 110 / 110 | 206.1s |
| 6 | 110 / 110 | 206.1s |
| 7 | 110 / 110 | 206.0s |
| 8 | 110 / 110 | 206.0s |

`failed 0, errors 0, skipped 0` in all eight. Test count held at 110 — nothing was deleted, skipped, or xfailed. `worklog.md` was not read or written.

**Orchestrator verification (mandated — a Step 7 agent can claim a clean sweep with no artifacts on disk):** independently re-read all 8 `workspace/implementation/results.$i.json` (present, ~35.6 KB each, mtime 16:51). Every round parses as `total 110 / passed 110 / failed 0 / errors 0 / skipped 0`, durations 205.96-206.09s. The claim is corroborated by real artifacts; no re-run needed. The sweep ran via the orchestrator-supplied `workspace/sweep.sh` under `setsid nohup`, so the reaping and inline-quoting hazards were both avoided.

**Step 8 gating decision:** Step 7 made 1 `test_suite/` fix (and 0 deletions / 0 `test_helpers/` fixes / 0 `implementation/` fixes), so the zero-change skip condition does NOT hold. Step 8 runs, with that single ERROR-PRECEDENCE-SILENCE site as its focus list.

## Step 8: Finalize PRD — 2026-09-05T16:56:27.728426961Z

Done. `PRD_FINALIZED.md` is a one-sentence-site patch.

**Line counts:** PRD.md 483 lines / PRD_FINALIZED.md 483 lines — 0.0% line delta (1 of 483 lines revised in place, 0.21% of lines touched; +500 bytes, +0.46% by size).

**Changes (1):**
- §3.5 (Completeness Review — deem-complete paragraph, PRD_FINALIZED.md line 268) — revise — the open-uncured-notice refusal was stated as unconditionally `ERR_COMPLETENESS_REVIEW_NOT_OPEN`; now pins that the state gate is evaluated first, so an application left in `INCOMPLETE` by its own notice (the ordinary case) is refused with `ERR_APPLICATION_NOT_IN_COMPLETENESS_REVIEW`, and `ERR_COMPLETENESS_REVIEW_NOT_OPEN` remains reachable only for an application still in `SUBMITTED`/`COMPLETENESS_REVIEW` with an open round — `implementation/r_applications.py:208-212` (gate at `:128-134`).

**Pre-edit search log (edit 1):**
- (a) Subject: which error id a deem-complete request receives when both the application-state gate and the "no open `DEFICIENCY_NOTICE_ISSUED` round" rule are violated; and, more broadly, every producer/consumer of those two identifiers and of application status `INCOMPLETE`/`SUBMITTED`/`COMPLETENESS_REVIEW`.
- (b) Paths enumerated (grepped `*.py` for both error ids, `COMPLETENESS_SOURCES`, `reviews_of_application`, `completeness_reviews`, and every literal write of `"SUBMITTED"`/`"COMPLETENESS_REVIEW"`, then read each hit):
  - `r_applications.py:128-134` `_require_completeness_stage` — shared gate, also used by `issue_deficiency_notice` (`:144`); raises `ERR_APPLICATION_NOT_IN_COMPLETENESS_REVIEW`, including when the cycle row is missing.
  - `r_applications.py:205-217` `deem_complete` — order is gate -> open-round loop -> `ERR_FILING_WINDOW_CLOSED`.
  - `r_applications.py:137-167` `issue_deficiency_notice` — the only creator of `DEFICIENCY_NOTICE_ISSUED` rows, and it always sets the parent application to `INCOMPLETE` (`:165`). This is what makes the `INCOMPLETE` claim in the wording universal rather than incidental.
  - `r_applications.py:179-201` `cure_review` — the other `ERR_COMPLETENESS_REVIEW_NOT_OPEN` site (unchanged; PRD §3.5 cure sentence and §2.8 rank 8 already match it) and the only writer of `"COMPLETENESS_REVIEW"` (`:199`), which closes the round in the same call.
  - `r_applications.py:105` — the only writer of `"SUBMITTED"` (from `DRAFT`, before any round can exist).
  - `r_cycles.py:137,166` — advance gate on `SUBMITTED`/`COMPLETENESS_REVIEW` and the expiry sweep over `completeness_reviews`; neither writes those two ids nor resurrects an application into a completeness-source status.
  - `r_participation.py:88-97` `decide_intervention` — a second, unrelated producer of `ERR_APPLICATION_NOT_IN_COMPLETENESS_REVIEW` (grant vs `LIVE_INTAKE_STATES`); confirmed the sentence stays inside the deem-complete paragraph and makes no exclusivity claim about that id.
  - `r_scoring.py:33-37` — consumes `reviews_of_application` for segregation of duties only; unaffected.
  - `services.py:10,51,88-90`, `errors.py:36-37` — helper/status-code definitions, no ordering content.
- (c) Wording adjustments made: (i) dropped a planned trailing clause asserting both checks precede the completeness-deadline check — true of the impl but unobservable, so omitting it keeps the patch minimal and avoids an over-specified ordering claim; (ii) kept `ERR_COMPLETENESS_REVIEW_NOT_OPEN` described as still-applicable-in-principle for a `SUBMITTED`/`COMPLETENESS_REVIEW` application rather than deleting it, because the impl retains that check even though the enumeration shows no path currently reaches it — deleting it would have contradicted `r_applications.py:209-212`; (iii) scoped the sentence with "here"/"this declaration" so it cannot be read as re-scoping the cure-filing use of the same id at `r_applications.py:188-190` or the intervention-grant use of the other id at `r_participation.py:94`.

No other Step 7 item produced a PRD edit: the diff contains zero implementation fixes, and the flagged 79.25-vs-79.70 comparative-score comparison was adjudicated as arithmetically consistent with the PRD's own worked examples, so it revealed neither silence nor mismatch. §2.8 rank 8 was left verbatim — its existing text already attaches `ERR_APPLICATION_NOT_IN_COMPLETENESS_REVIEW` to deem-complete's state gate and `ERR_COMPLETENESS_REVIEW_NOT_OPEN` to the cure, matching the implementation.

**Orchestrator verification:** PRD_FINALIZED.md exists and is NOT byte-identical to PRD.md — `diff` shows exactly one changed line (§3.5 line 268), consistent with the reported single-site patch and with Step 7's single test_suite fix being the only focus item.

## Step 9: Complete PRD — 2026-09-05T17:22:19.421395190Z

Run as **three sequential module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md` (pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden to re-copy and made in-place `Edit`-tool changes only). Partition: pass 1 = cross-cutting layer (`app.py`, `auth.py`, `envelope.py`, `store.py`, `errors.py`, `shape.py`, `clock.py`) + `r_config.py` + `r_cycles.py`; pass 2 = intake path (`r_loi.py`, `r_applications.py`, `r_participation.py`, `r_scoring.py`, `calc.py`); pass 3 = certificates/appeals/cascades (`r_certificates.py`, `r_appeals.py`, `cascades.py`, `services.py`). Each pass handed forward findings that fell in a later pass's sections.

**Totals: 483 lines -> 483 lines (all edits in place, 0 structural change, 28 headings preserved). 110,053 -> 133,031 chars, +22,978 (+20.9%). 68 edits over 58 lines: 55 ambiguity-pins, 13 mismatch-revisions.**

### Pass 1 — cross-cutting + config/cycles (22 edits: 19 ambiguity, 3 mismatch; 110,053 -> 117,867 chars)
- §2.1 — revise — ambiguity — headers trimmed before examination, so whitespace-only counts as absent — `auth.py:24-28`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — `envelope.py:18`
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from the host wall clock, not the logical clock — `envelope.py:21-23`
- §2.3 — insert — ambiguity — bad/out-of-range `limit`/`offset` -> `ERR_INVALID_REQUEST` (400); empty-string param = omitted; `created_at` ties broken by insertion order — `shape.py:163-182`, `store.py:69-71`
- §2.3 — insert — ambiguity — filters compare as exact case-sensitive strings; empty-string filter and unknown query params ignored — `shape.py:185-199`
- §2.4 — insert — ambiguity — instants accept `Z`/offset/naive(=UTC)/date-only, stored and echoed verbatim, compared in UTC; clock call answers 200 with empty `data` — `shape.py:116-126`, `clock.py:36-51`, `r_config.py:147-153`
- §2.5 — insert — ambiguity — `created_at`/`updated_at` come from the logical clock, so rows written without a clock move share a stamp — `store.py:47-61`
- §2.6 — insert — ambiguity — numbers transported in shortest form (no trailing zeros; integral values without a decimal part) — `clock.py:106-116`, `app.py:36-47`
- §2.8 rank 3 — insert — ambiguity — absent body = `{}`; non-object body rejected; explicit `null` = absent; strings non-empty/non-blank; integer fields reject booleans, accept `5.0`; extra fields ignored — `shape.py:21-113`
- §2.8 rank 9 — revise — **mismatch** — "three operations" -> two (cycle advance, comparative decision); need recomputation is not status-gated — `r_cycles.py:182-190`
- §2.10 — revise — ambiguity — the three conserved totals are clamped at zero rather than the request being refused — `services.py:202-217`
- §3.1 — revise — **mismatch** — `RETIRED` planning area is not enforced; cycle creation never inspects area `status` — `r_cycles.py:36-92`
- §3.1 — insert — ambiguity — non-amendable fields (`service_type`, `effective_from_date`) accepted and ignored; a no-field amendment still bumps `updated_at`/`version` — `r_config.py:88-119`
- §3.1 — insert — ambiguity — `contact_email` is only a non-empty string, no format check — `r_config.py:164`
- §3.2 — insert — ambiguity — overlap test precedes the calendar-ordering test; service-type coherence (position 7) precedes both — `r_cycles.py:50-70`
- §3.2 — insert — ambiguity — need figures written as part of creation, so a new cycle returns with `version` 1 — `r_cycles.py:91-92`
- §3.2 — insert — ambiguity — recompute-need takes no body, gated only on cycle existence, available at any stage, overwrites the pool over live allocations — `r_cycles.py:182-190`
- §3.2 — insert — ambiguity — `to_status` outside the six statuses is a rank-3 `ERR_INVALID_REQUEST`; `DECIDED` from `COMPARATIVE_REVIEW` / anything from `CLOSED` is `ERR_INVALID_CYCLE_STATUS_TRANSITION` — `r_cycles.py:115-120`
- §3.2 — insert — ambiguity — `COMPARATIVE_REVIEW` gate order: unresolved-applications before mandatory-hearing, both before either sweep — `r_cycles.py:135-176`
- §3.2 — insert — ambiguity — cycle close: `ERR_APPEAL_PENDING` outranks `ERR_APPEAL_WINDOW_OPEN`; apps with null `appeal_window_closes_at` skipped — `r_cycles.py:122-133`
- §3.2 — insert — ambiguity — need-analysis re-derives nothing; every figure but the two version fields is read off the stored cycle, `unallocated_bed_need` alone being live — `r_cycles.py:193-210`
- §3.7 — revise — **mismatch** — `decision_note` validated when supplied but never persisted; added the §2.8 precedence (14 -> 26 -> 27) impl follows — `r_cycles.py:216-243`
- §4 — insert — ambiguity — trailing slash tolerated on every path — `app.py:53`
- §5 — insert — ambiguity — unrouted path/method answers `ERR_INVALID_REQUEST` at 404/405 rather than 400 — `app.py:62-74`

### Pass 2 — intake path (22 edits: 18 ambiguity, 4 mismatch; 117,867 -> 123,032 chars)
Confirmed pass 1's 22 changed lines still divergent and untouched; edit sites disjoint (lines 242-322).
- §3.3 — insert — ambiguity — lookback window opening instant is a day-clamped 24-month calendar step; priors qualify whatever their own `service_type` — `calc.py:31-47`, `clock.py:75-81`, `r_loi.py:22-38`
- §3.3 — insert — ambiguity — LOI withdrawal has no status precondition; `reason` validated non-empty when supplied but not persisted — `r_loi.py:113-122`
- §3.4 — insert — ambiguity — conversion is not gated on the cycle's stage; only the `COMPLETENESS_WINDOW` advance closes the door — `r_applications.py:24-50`
- §3.4 — insert — ambiguity — submission reads no input fields, so any body (even invalid JSON) is ignored — `r_applications.py:88-107`
- §3.4 — insert — ambiguity — withdrawal `reason` validated non-empty when supplied, not persisted — `r_applications.py:113-114`
- §3.4 — revise — **mismatch** — "Two guards" -> three, naming `ERR_APPLICATION_NOT_SUBMITTABLE` for a status outside the withdrawable set — `r_applications.py:117-119`
- §3.5 — insert — ambiguity — `deficiency_items` stored as supplied, not type-checked; no lower bound on `cure_deadline_at` (a past instant opens an uncurable round) — `r_applications.py:141-152`
- §3.5 — revise — **mismatch** — the open-round check fires before the completeness-deadline test, so an open round past the deadline yields `ERR_COMPLETENESS_REVIEW_NOT_OPEN`, not `ERR_FILING_WINDOW_CLOSED` — `r_applications.py:209-214`
- §3.5 — insert — ambiguity — deem-complete reads no input fields; a body is ignored — `r_applications.py:204-208`
- §3.5 — insert — ambiguity — the advance promotes `DEEMED_COMPLETE` only; a `REMANDED` application competes directly from `REMANDED` — `r_cycles.py:172-175`
- §3.6 — insert — ambiguity — comment filing inspects neither the application's status nor the cycle's stage — `r_applications.py:222-241`
- §3.6 — insert — ambiguity — the standing test precedes both eligibility rules on intervention filing; filing not gated on target status — `r_participation.py:35-41`
- §3.6 — insert — ambiguity — a `denial_reason` sent with a `GRANT` is accepted then discarded — `r_participation.py:91-99`
- §3.6 — insert — ambiguity — the mandatory-hearing demand counts any `GRANTED`+`requested_hearing` intervention on any application of the cycle whatever its status — `r_cycles.py:141-144`
- §3.6 — insert — ambiguity — hearing scheduling inspects neither the room's `status` (an `OUT_OF_SERVICE` room is bookable) nor the cycle's stage — `r_participation.py:124-139`
- §3.6 — insert — ambiguity — cancellation `reason` validated non-empty when supplied, not persisted — `r_participation.py:174`
- §3.6 — insert — ambiguity — on reschedule a bad `hearing_room_id` yields `ERR_HEARING_ROOM_NOT_FOUND` before the `CANCELLED` state test — `r_participation.py:193-201`
- §3.7 — revise — **mismatch** — score-sheet submission is gated on no state at all; `expected_application_version` must be a non-negative integer; `narrative` defaults to null; the pinned version is not persisted — `r_scoring.py:21-53`
- §3.7 — insert — ambiguity — the score-sheet sub-collection read returns `ACTIVE`, `SUPERSEDED` and `STALE` rows alike in `created_at` order — `r_scoring.py:60-66`
- §3.7 — revise — **mismatch** — `created_at` is not the final ranking tie-break; candidates tying on all three keys order by insertion order — `calc.py:106-112`
- §3.7 — insert — ambiguity — every decided candidate has `denial_reason` rewritten (`INSUFFICIENT_NEED` on denial, back to null on both award branches) — `cascades.py:219`
- §3.8 — insert — ambiguity — `latest_completion_pct` tie beyond `period_end_date` and `created_at` goes to the later insertion — `calc.py:144-148`

### Pass 3 — certificates, appeals, cascades (24 edits over 18 lines: 18 ambiguity, 6 mismatch; 123,032 -> 133,031 chars)
Confirmed no re-copy and both earlier passes intact (58 divergent lines: 40 theirs, 18 mine; 483 lines, 28 headings). All seven of pass 2's handed-off items were pinned; none judged out of scope or already covered.
- §2.11 — revise — **mismatch** — "only one interaction couples the axes" was false; two do, both money->lifecycle (breach suspends; reissue restores the suspended lifecycle), and nothing runs the other way — `r_certificates.py:179-182`, `cascades.py:49-53`
- §3.8 — insert — ambiguity — `conditions` stored verbatim, entries type-unconstrained, attestation expectation recorded but never enforced — `r_certificates.py:37,74`, `shape.py:140-150`
- §3.8 — insert — ambiguity — the zero-bed `ERR_NEED_EXHAUSTED` is unranked in §2.8 and fires after the appeal-window test, before the single-live-certificate test — `r_certificates.py:49-61`
- §3.8 — revise — **mismatch** — issuance "writes across four records" -> exactly two (certificate + planning area); application and cycle untouched — `r_certificates.py:63-87`
- §3.8 — insert — ambiguity — report supersession is per certificate row, not per lineage; an ancestor's report for the same period stays `ACCEPTED` and both keep contributing — `cascades.py:28-34`
- §3.8 — insert — ambiguity — empty contributing set yields `latest_completion_pct` 0, not null; the successor's cumulative figures are lineage sums — `services.py:168-182`
- §3.8 — insert — ambiguity — the completion cascade is evaluated first and already stored when the breach test reads the lifecycle (one filing -> `IMPLEMENTED` then `SUSPENDED` with `lifecycle_status_before_suspension` `IMPLEMENTED`, `version` +3); a later in-limit report resets the money axis but never lifts the suspension and charges no second strike — `cascades.py:36-54`
- §3.8 — insert — ambiguity — `requested_days` is a required non-negative integer, 0 grants nothing yet still moves `version`; `justification` validated non-empty but not persisted — `r_certificates.py:114-131`
- §3.8 — insert/revise — ambiguity — "beds already released" means precisely that the addressed row is `IMPLEMENTED`; both new figures merely non-negative (no at-least-1 floor); position 29's three tests fire floor -> bed-reduction -> bed-ceiling — `r_certificates.py:139-173`
- §3.8 — insert — ambiguity — null `lifecycle_status_before_suspension` falls back to `ISSUED`; restoration is unconditional; basis/required-pct/conditions copied, milestone retained, `issued_by_user_id` stamped from the modifying officer — `r_certificates.py:179-208`
- §3.8 — insert — ambiguity — the area row is rewritten on every reissue (version moves on a no-op modification) while the cycle is untouched unless the bed count changed — `r_certificates.py:210-216`
- §3.8 — revise — **mismatch** — `LIMIT_AMENDED` was restricted to `OVER_LIMIT_PENDING_AMENDMENT`/`LIMIT_BREACHED`; impl writes it from any axis value, including `WITHIN_LIMIT`, whenever the new limit is strictly greater — `r_certificates.py:185-186`
- §3.8 — insert — ambiguity — lapse sweep body ignored unvalidated; `ISSUED` certificates evaluated in `created_at`-then-insertion order; `evaluated_count` counts all of them pre-filter; `lapsed_certificate_ids` inherits that order — `cascades.py:59-92`
- §3.8 — insert — ambiguity — on lapse the application keeps its `status`/`decision_at`/`appeal_window_closes_at`, staying `APPROVED` while holding no beds — `cascades.py:83-85`
- §3.9 — insert — ambiguity — `appellant_applicant_id` is a position-5 foreign key (`ERR_APPLICANT_NOT_FOUND`) resolved after `application_id`; a null `appeal_window_closes_at` counts as expired — `r_appeals.py:32-51`
- §3.9 — insert — ambiguity — `to_status` must be one of the seven declared statuses (else rank-3 `ERR_INVALID_REQUEST`) and only the immediate successor is legal — `r_appeals.py:17-18,90-94`
- §3.9 — insert — ambiguity — `rationale` validated non-empty but not persisted; the `disposition` enum is only the three values — `r_appeals.py:129-130`
- §3.9 — revise — **mismatch** — links 3-5 hang off the reversed-*approval* branch only; a `DENIED`->`DEEMED_COMPLETE` reversal stops at link 2; any other application status is left untouched — `cascades.py:122-148`
- §3.9 — insert — ambiguity — the bed debit always hits `approved_unimplemented_beds`, clamping at zero for an already-`IMPLEMENTED` certificate, and never reduces `existing_licensed_beds` — `cascades.py:136-142`, `services.py:202-211`
- §3.9 — revise — **mismatch** — reopening fires only when the cycle is exactly `DECIDED`; `reopened_count` increments on reversal too (PRD had omitted it); resurrected siblings get decision fields cleared; otherwise the cycle row is written only if beds returned to its pool — `cascades.py:143-163`
- §3.9 — revise — **mismatch** — "every other decided application" means exactly `APPROVED`/`APPROVED_WITH_CONDITIONS`/`DENIED` (a `REMANDED` sibling is skipped); the appellant's `denial_reason` is also cleared with no state precondition; only the status/`reopened_count` move is conditional on `DECIDED` — sibling resurrection and sheet staling run regardless — `cascades.py:166-205`
- §3.9 — insert — ambiguity — staling and rescoring sweep every application of the cycle, but rescoring mutates only where a figure changed (an unscored application's `version` never moves), and each row touched by one disposition cascade moves `version` exactly once however many links reached it — `cascades.py:9-22,97-104`, `services.py:119-127`

**Orchestrator verification:** `PRD_COMPLETED.md` exists, is 483 lines / 28 headings / 133,031 chars, ends on the complete final row of the §5 error table (no truncation), and is **not** byte-identical to `PRD_FINALIZED.md` — `diff` reports 58 changed lines, so the scan demonstrably ran across all three passes. `find` confirms no `implementation/*.py` file is newer than `results.1.json`, i.e. Step 9 edited documentation only and the verified 8x110/110 green state still stands. No stray `test_helpers/`/`test_suite/` under `workspace/`; `worklog.md` exists only at the task root.

### Pipeline complete
All nine steps finished. Final artifact set: SCAFFOLD.yaml + the two design indices; `test_helpers/` (9 files) and `test_suite/` (20 files, 110 tests) at the task root; `workspace/` holding INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, sweep.sh, sweep.log and `implementation/` (18 modules + start.sh + requirements.txt + results.1-8.json all at 110/110).

