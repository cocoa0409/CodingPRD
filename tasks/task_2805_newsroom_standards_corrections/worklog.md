## Step 1: Create Task Directory — 2026-09-04T23:50:00.000Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2805_newsroom_standards_corrections and its workspace/ subdirectory. Index 2805 was pre-assigned by the orchestration harness (no ./tasks/ scan performed, per instruction, to avoid collisions with the ~32 concurrent pipelines on this host).

## Step 2: Generate Scaffold — 2026-09-05T00:56:00.000Z

All three scaffold artifacts are complete, parse cleanly under PyYAML, and the scaffold linter reports a clean verdict.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2805_newsroom_standards_corrections/`)

| file | lines | top-level key(s) |
|---|---|---|
| `SCAFFOLD.yaml` | 2697 | scenario, domain_name, api_prefix, response_envelope, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles (no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1763 | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3545 | `scaffold_corner_design` only |

**Surface counts (§1.0–§1.7)**: 13 entities (2 with `common_fields: false`) · 55 endpoints (31 POST / 24 GET) · 10 state machines across 2 parallel Story dimensions · 2 concurrency rules (`expected_story_version` → ERR_STALE_STORY_VERSION, `expected_reviewer_version` → ERR_STALE_REVIEWER_VERSION) · 8 calculations · 35 ordered validations (unique priorities 1–35) · 44 errors · 5 roles (4 entity-backed, PublicEditor opaque) · `api_prefix: /standards-desk` · logical clock default `2026-08-01T00:00:00Z`.

**§1.8 difficulty design**: 20 instances over all 9 required rules (2/3/2/2/3/2/2/2/2), every one with pre-computed literal asserts.

**§1.9 corner design**: 83 instances = 65 full `test_recipe` instances + 18 `excluded_because:` stubs, spread over all nine taxonomy sections — entities 11, state_machines 8, calculations 8, validations 12, endpoints 5, errors 24, rbac 8, cross_cutting_layers 6, consistency_model 1. All `section:`/`claim_type:` values are taken verbatim from `references/claim-extraction-guide.md`.

**Lint** (`scaffold_lint.py`): 55 endpoints, 13 entities, 20 §1.8 instances, 65 §1.9 instances, 664 calls scanned → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

**Notes worth relaying**
- Error-catalog coverage was verified programmatically: all 44 error ids appear in §1.8 or §1.9 (16 raised by §1.9 recipes directly, 8 delegated to §1.8 via stubs, the rest raised by dedicated §1.9 error/rbac/OCC recipes). No instance names collide.
- One lint quirk drove a file-wide convention: FK reverse-reachability (check f) only recognises sub-resource routes whose parent path parameter is literally `{id}`, so every braced path parameter in all three files is `{id}`.
- The "harder than expert level" directive does not appear anywhere in `SCAFFOLD.yaml` (checked case-insensitively).
- Two consistency defects in `SCAFFOLD.yaml` found while grounding §1.9 were fixed in place: the Story `standards_status` retraction edge had `from: PUBLISHED` (a value from the other state dimension) and is now `from: CLEAN | UNDER_INQUIRY | CORRECTED` with an explicit `publication_status == PUBLISHED` precondition; `StandardsAuditEvent.newsroom_id` was `source: input` with no create endpoint and is now `source: system`.
- Reachability check worth remembering for the PRD/test phase: ERR_SEGREGATION_OF_DUTIES is only reachable through the misconduct open-vs-decide and decide-vs-appeal pairs — the correction/story path is unreachable because a story's lead journalist is always role_title REPORTER and therefore can never act as StandardsEditor. ERR_JOURNALIST_SUSPENDED is asserted via review submission (not story creation) because priority 11 pre-empts priority 25 on `POST /stories`.

_Orchestrator verification_: all three files present; `grep -i "expert level|harder than" SCAFFOLD.yaml` → no match (difficulty directive did not leak).

## Step 3: Copy Shared Files — 2026-09-05T00:56:30.000Z

Copied ./INSTRUCTION.md to tasks/task_2805_newsroom_standards_corrections/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-05T01:03:00.000Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — **482 lines**, written incrementally (1 Write + 7 heredoc appends), so no truncation risk.

**Top-level sections emitted:**
- `## 1. Introduction` (3 paragraphs)
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Acting Identities and RBAC, 2.2 API Response Structure, 2.3 Pagination, 2.4 Resource Identity/Timestamps/Version Counters, 2.5 The Logical Newsroom Clock, 2.6 Identifier Resolution and Cross-Newsroom Referential Integrity, 2.7 Numeric Precision, 2.8 Stale-View Protection, 2.9 The Desk-Wide Standards Posture, 2.10 Segregation of Duties, 2.11 Cascade Discipline and the Transparency Log, 2.12 Order of Precedence Among Validations (all 35 priorities as a normative ladder)
- `## 3. Business Logic & Workflows` — 3.1 Standing Up the Desk, 3.2 Opening a Story File and Authorising Anonymous Sources, 3.3 The Pre-Publication Review Cycle, 3.4 Reviewer Time as a Conserved Resource, 3.5 Clearing, Publication and Removal from the Site, 3.6 Correction Intake/Investigation/Adjudication, 3.7 Plagiarism, Fabrication and the Disciplinary Ledger, 3.8 Conflicts, Outside Work and Standards Training
- `## 4. Endpoint Definitions` — 4-column table, all writes + reads
- `## 5. Error Code Catalogue` — 2-column table, all 44 error IDs

**Tail verification (explicit):** ran `wc -l` and `tail -40`. The file ends at a real section boundary — the last row of the §5 error table, `| ERR_REVIEWER_CAPACITY_EXCEEDED | 422 |` — with no mid-sentence cut, no audit footer, and every planned section present (heading dump confirms 1→5 in order).

**Hard Contract Reports**

Field coverage check: entities[].fields 113/113, endpoints[].request_body 78/78, endpoints[].query_params 22/22 → PASS (two passes; second used strict whole-backtick-token matching, diff still empty).

Rule coverage check: 35/35 validations, 2/2 OCC rejections, 41/41 transitions, 8/8 calculations, 35/35 validation conditions matched to error_id, 31/31 write-endpoint side effects, 113/113 entity fields reconstructible from prose, 7/7 sibling-branch symmetry groups with equal prose density → PASS.

Path purity check (§3 only): 301 backtick tokens scanned, 0 starting with `/`, 0 bare HTTP-method tokens, 0 method+path tokens → PASS.

Additional checks: §2.2 matches the canonical response-classification source byte-for-byte (incl. `req_RANDOMALPHANUM123456` and `"data": { }`); all 44 `errors[].id` appear in §2 or §3 narrative, not only in the §5 table; all 5 role names present; grep for fuzzy/approximating words returned zero hits.

Two judgement calls worth flagging: (1) the scaffold constrains `Journalist.email` to be unique per newsroom but nominates no error ID for a duplicate, so the PRD states the constraint without assigning a code rather than inventing one; (2) recording a legal verdict on a round whose `requires_legal_review` is false has no declared transition, so the PRD routes it to `ERR_INVALID_STATE` per validation priority 11.

_Orchestrator verification_: 482 lines / 89529 bytes; heading dump shows sections 1–5 in order; tail ends on the final error-table row (not mid-sentence) → not truncated. §4 table has 55 endpoint rows, §5 table has 44 error rows, matching the scaffold surface. `grep -i "expert level|harder than expert"` on PRD.md → 0 hits (difficulty directive did not leak into the PRD).

## Step 6: Generate Implementation — 2026-09-05T01:47:00.000Z

(Steps 5 and 6 were launched concurrently; Step 6 returned first, so its entry is recorded first. The Step 5 entry follows below.)

Implementation complete and verified.

## Files written (all under `workspace/implementation/`)

| file | lines |
|---|---|
| `app.py` | 82 |
| `auth.py` | 78 |
| `calc.py` | 446 |
| `envelope.py` | 95 |
| `errors.py` | 80 |
| `helpers.py` | 72 |
| `serialize.py` | 163 |
| `store.py` | 113 |
| `validation.py` | 206 |
| `routes/__init__.py` | 1 |
| `routes/setup.py` | 274 |
| `routes/stories.py` | 202 |
| `routes/sources.py` | 152 |
| `routes/reviews.py` | 228 |
| `routes/assignments.py` | 133 |
| `routes/corrections.py` | 223 |
| `routes/misconduct.py` | 246 |
| `routes/conflicts.py` | 246 |
| `start.sh` | 10 |
| `requirements.txt` | 1 |

3040 lines of Python across 18 modules, 3051 including `start.sh`/`requirements.txt`. `__pycache__` removed; no other files exist in the directory.

## Endpoint parity: exact

Programmatic diff of Flask's `url_map` against the PRD §4 table: **55 routes = 31 POST + 24 GET**, zero missing, zero extra (path params normalised). All registered under the `/standards-desk` prefix.

## Boot confirmation

`bash start.sh` does a guarded `pip install` (only when Flask is absent, to avoid 8-round reboot contention) then `exec python3 app.py`, which reads `PORT` from the environment, binds `0.0.0.0`, and runs Flask in the foreground with `use_reloader=False`. Cold boot on `PORT=18072` came up in under 5 s and returned the correct envelope with `meta.api_request_id` / `api_request_timestamp` and `response_type: object`.

Store is empty on every boot (verified: `GET` collections return nothing until clients create entities; nothing is seeded), logical clock starts at `2026-08-01T00:00:00Z`, and a source grep confirms no file I/O, no sqlite, no `/tmp` cache — memory only.

## Verification performed (5 end-to-end smoke suites, all green)

- Round gates: `ERR_LEGAL_VERDICT_REQUIRED` on a standards verdict before legal, standards `BLOCK` → `ERR_INVALID_STATE`, a legal verdict on a non-legal round → `ERR_INVALID_STATE`, a second legal verdict → `ERR_REVIEW_ROUND_NOT_OPEN`.
- Publish ladder in PRD order (12 → 19 → 23 → 24 → 25): a HIGH-tier story (45.00, from 10 defamation + 5 privacy + 1 unverified doc) refused with `ERR_TRAINING_NOT_CURRENT` **before** `ERR_SOURCE_NOT_APPROVED`; after filing the SOURCING module → `training_current: true` and publish succeeds with `risk_index_actual` 45.00. Both `REQUESTED` and `REVOKED` sources refuse publication with `ERR_SOURCE_NOT_APPROVED`; a `DENIED` source does not.
- Sources: `ERR_INSUFFICIENT_SOURCE_DOCUMENTATION`, `ERR_SOURCE_ALREADY_DECIDED`, revoke → story back to `UNDER_INQUIRY` with `risk_index_actual` rising 47.00 → 52.00 while `risk_index_estimate` falls back to 45.00, double revoke → `ERR_INVALID_STATE`.
- Corrections: `ERR_CORRECTION_NOT_INVESTIGATED`, `ERR_NOTICE_TEXT_REQUIRED` in both directions (missing for `CORRECTION`, present for `NO_ACTION`), and the `NO_ACTION` dismissal returning the story to `CLEAN` with `open_correction_request_count` back to 0 and `placement` null; intake against a `RETRACTED` story → `ERR_INVALID_STATE`.
- Unpublish: `ERR_UNPUBLISH_NOT_JUSTIFIED` with nothing on the record, then after a `SUSTAINED` PLAGIARISM/MINOR case (2 points, `disclosure_obligation: EDITORS_NOTE`, journalist stays `ACTIVE`) the removal succeeds writing both dimensions (`UNPUBLISHED` + `RETRACTED`), `unpublished_at`, recomputed `risk_index_actual`, `version` 5; second attempt → `ERR_STORY_NOT_PUBLISHED`; StandardsEditor → `ERR_UNAUTHORIZED`.
- Audit trail via the newsroom audit-events read: occurrence order `REVIEW_CLEARED(Story) → STORY_PUBLISHED → INVESTIGATION_SUSTAINED → STORY_UNPUBLISHED`, `event_type` filter works, and records carry no `version`/`updated_at` (append-only).

Two apparent failures during smoke were traced to the agent's own test scripts, not the server: `claimed_error_category: "FACT"` (the enum is `FACTUAL`) and a wrong audit path, plus an omitted required `removal_reason`. No implementation defects surfaced; nothing needed fixing.

Isolation held: wrote only inside `workspace/implementation/`, never read `test_helpers/`, `test_suite/`, either SCAFFOLD design file, or any sibling task; `worklog.md` untouched. Both smoke servers were killed by captured PID with the ports confirmed released — no pattern kills were used.

## Step 5: Generate Unit Tests — 2026-09-05T02:15:00.000Z

Generation is complete and verified.

## Files written

**`test_helpers/`** (9 files, 3,200 lines)
| file | lines |
|---|---|
| `__init__.py` | 53 |
| `api_client.py` | 401 |
| `api_errors.py` | 116 |
| `assertions.py` | 410 |
| `constants.py` | 329 |
| `factories.py` | 419 |
| `fixtures.py` | 1129 |
| `test_users.py` | 86 |
| `types.py` | 257 |

**`test_suite/`** (19 files, 5,103 lines)
| file | lines | tests |
|---|---|---|
| `conftest.py` | 88 | — |
| `test_01_dual_risk_and_severity_variants.py` | 190 | 4 A |
| `test_02_pinned_arithmetic_orders.py` | 243 | 6 A |
| `test_03_story_dimensions_and_bounded_review_cycle.py` | 187 | 4 A |
| `test_04_transitive_cascades.py` | 231 | 4 A |
| `test_05_competing_refusals.py` | 281 | 6 A |
| `test_06_inclusive_boundaries.py` | 219 | 4 A |
| `test_07_gates_owned_by_another_record.py` | 194 | 4 A |
| `test_08_calendars_and_buffers.py` | 199 | 4 A |
| `test_09_conserved_ledgers.py` | 210 | 4 A |
| `test_10_desk_records_and_reads.py` | 428 | 11 B |
| `test_11_state_transitions.py` | 337 | 7 B |
| `test_12_deadlines_and_indices.py` | 275 | 5 B |
| `test_13_gates_and_refusals.py` | 535 | 11 B |
| `test_14_desk_reads_and_bookings.py` | 284 | 4 B |
| `test_15_unknown_identifiers.py` | 276 | 9 B |
| `test_16_stake_and_state_refusals.py` | 345 | 7 B |
| `test_17_role_admission_and_identity.py` | 298 | 7 B |
| `test_18_stale_views_and_immediate_reads.py` | 283 | 4 B |

## Tests per queue

- **Queue A (Difficulty)** — 40 tests covering all 20 instances across 9 rule_ids, exactly 2 tests each: `boundary_precision_check` 4, `combinatorial_formula` 6, `compensating_invariant` 4, `cross_entity_state_dependency` 4, `dual_variant_calc` 4, `non_linear_state_machine` 4, `priority_pair_validation_conflict` 6, `resource_temporal_overlap` 4, `transitive_cascade` 4.
- **Queue B (Corner)** — 65 tests, one per non-stub instance: entities 11, state_machines 7, calculations 5, validations 11, endpoints 4, errors 16, rbac 7, cross_cutting_layers 3, consistency_model 1.
- **Total 105 tests.** 105 `Design:` lines, all unique, all resolving to a real `name:` in the source yaml; zero untagged and zero dual-tagged tests.

## Instances skipped

**None.** Every one of the 20 Difficulty instances and all 65 non-stub Corner instances passed the PRD-first two-condition filter and was translated. The 18 `excluded_because:` stubs in the corner index were correctly left untranslated (verified: no tag contains `excluded`).

Two design recipes had assertions that contradicted the PRD, so the generator asserted the PRD-derivable value rather than skipping the instance:
- `Corner/entities/...` in `test_10` — the yaml expected `risk_index_estimate` 13.00 where PRD §3.2's arithmetic yields 12.00.
- `Corner/consistency_model/adjudication_response_already_carries_every_recomputed_field` in `test_18` — the yaml expected `Story.open_correction_request_count == 0` after adjudication, but PRD §3.6 puts that decrement at *resolution*, not adjudication, so the test asserts 1.

## Verification

- `python3 -m py_compile` on all 28 files: clean.
- `python3 -m pytest --collect-only -q test_suite`: **105 tests collected**, no collection errors.
- No `xfail`, `pytest.mark.skip`, `unittest` or mocking anywhere; zero occurrences of "scaffold" in any generated file.
- `ls -la` on `workspace/` shows only `INSTRUCTION.md`, `PRD.md` and `implementation/` — **nothing landed under `workspace/`**, and a `find` for stray `test_helpers`/`test_suite` beneath it returned nothing. `worklog.md` and `workspace/implementation/` were never read or written.

_Orchestrator verification_: `test_helpers/` and `test_suite/` both present at the task root; `find workspace -maxdepth 2 -type d -name "test_*"` returned nothing (no stray test dirs under workspace/).

## Step 7: Run Tests and Iterate — 2026-09-05T02:45:00.000Z

All 8 result files from the final clean sweep are on disk.

## Summary

**Iterations run:** 2

**Iteration 1** — 8/8 rounds at 102/105, the same 3 tests failing deterministically in every round (no flakiness; the union equalled the per-round set).

**Iteration 2** — 8/8 rounds at **105/105**, zero failures, zero errors, empty failure union.

### Tests deleted
None. All three failures were STEP 2 test-fixture bugs (setup constructing a precondition the PRD forbids, or introducing a second higher-precedence violation). Every asserted rule was verbatim in the PRD and uniquely derivable, so nothing qualified for deletion.

### Fixes applied to `test_helpers/`
None — the shared helpers were already PRD-faithful. Both bugs lived in test-local setup helpers inside `test_suite/`.

### Fixes applied to `test_suite/`
- **`test_suite/test_06_inclusive_boundaries.py`** — `TestPostureTripsAtTheThresholdItself`: replaced the `_two_investigating_identification_complaints` helper (which filed a second complaint against a story already driven to `UNDER_INQUIRY` by the first, so the PRD-faithful server correctly returned `ERR_INVALID_STATE`) with `_carrier_story` + `_adjudicated_identification_complaint`, which runs file → investigate → adjudicate to completion per complaint. PRD §3.6: "Intake is admissible while the story's `standards_status` is `CLEAN` or `CORRECTED`" — adjudicating returns the story to `CORRECTED`, which is the edge the next intake requires. Both tests' assertions (count 1 → `OPEN`; count 2 → `HEIGHTENED`, score 21 / band `SEVERE`, `severe_correction_count` 2) were kept exactly as written.
- **`test_suite/test_16_stake_and_state_refusals.py`** — `test_a_late_legal_read_on_a_closed_round_is_refused`: the setup built a round with `requires_legal_review` **false**, which breaks two rules at once. PRD §3.3 gives that case its own refusal ("Recording a legal verdict on a round whose `requires_legal_review` is false has no declared transition and is refused with `ERR_INVALID_STATE`"), and PRD §2.12 reports it first — step 11 (`ERR_INVALID_STATE`) outranks step 14 (`ERR_REVIEW_ROUND_NOT_OPEN`). The implementation was correct. Fixed the setup to drive a **legal-track** round (`high_risk_declared=True`, legal `PASS`, standards `PASS`) to `STANDARDS_CLEARED`, so the round-open rule is the only one violated. The `ERR_REVIEW_ROUND_NOT_OPEN` assertion was preserved unweakened; the follow-up "nothing was written" check became `legal_verdict == PASS` (the earlier verdict of record) instead of `is None`, which proves the refused `BLOCK` wrote nothing with identical force.

### Fixes applied to `implementation/`
**None.** No implementation defects were found — both diagnoses traced to test setup violating a PRD precondition or precedence rule, and per the cardinal rules no PRD-required check (the `CLEAN`/`CORRECTED` intake gate, the §2.12 step-11-before-step-14 ordering) was removed or weakened to accommodate a faulty fixture.

_Orchestrator verification_: all 8 `workspace/implementation/results.{1..8}.json` exist (timestamped 02:40, same sweep) and each reports `passed=105 / total=105, failed=0, errors=0`. Grep for `pytest.mark.skip` / `xfail` across `test_suite/` and `test_helpers/` → no hits; suite still holds 105 tests, so the clean sweep was not bought by skipping or deleting anything.

_Step 8 decision_: NOT skipped. The skip condition requires zero deletions AND zero `test_suite/` fixes AND zero `test_helpers/` fixes AND zero `implementation/` fixes; Step 7 applied 2 `test_suite/` setup fixes, so Step 8 runs with those two items as its `<step_7_diff>` focus list (both are pure test-setup bugs, so Step 8 may legitimately conclude that neither warrants a PRD edit).

## Step 8: Finalize PRD — 2026-09-05T02:52:00.000Z

`PRD_FINALIZED.md` is written: **482 lines vs. 482 in PRD.md, 0% line delta — one line revised (§3.6), one sentence inserted.**

## Change list

- **§3.6 (Correction Intake) — insert — added the refusal identifier for an inadmissible intake: "An intake attempt against a story whose `standards_status` is `UNDER_INQUIRY` or `RETRACTED` is refused with `ERR_INVALID_STATE`." — `implementation/routes/corrections.py:53-55`**

## Per-item Step 7 analysis

**Item 1 — `test_06_inclusive_boundaries.py` / `TestPostureTripsAtTheThresholdItself` (residual silence → one edit).** Everything the fix's rationale cited is already uniquely determined by PRD.md and was left verbatim: the admissibility window itself (§3.6 "`CLEAN` or `CORRECTED`"), the `CORRECTED` return at adjudication (§3.6 non-`NO_ACTION` branch), the inclusive posture thresholds and the two-source `open_high_severity_count` (§2.9, matched by `calc.recompute_posture` / `open_high_severity_count`), and the severity arithmetic behind score 21 / band `SEVERE` (§3.6: 8 + 4 + 6 = raw 18 → `SEVERE` → +3). The one residual silence is the *error identifier* for a refused intake: PRD states admissibility but names no error, and §2.12 step 11 is scoped to "action endpoint[s]", which does not unambiguously cover the correction-request creation endpoint. The implementation pins `ERR_INVALID_STATE`, so that is now stated inline.

**Item 2 — `test_16_stake_and_state_refusals.py` / late legal read (no edit).** Both PRD sentences the fix relied on are already exact and exhaustive: §3.3 "Recording a legal verdict on a round whose `requires_legal_review` is false has no declared transition and is refused with `ERR_INVALID_STATE`", §3.3 "Which rounds are open" (`SUBMITTED` only for a legal verdict; `STANDARDS_CLEARED` closed → `ERR_REVIEW_ROUND_NOT_OPEN`), and §2.12's step-11-before-step-14 ordering — which `routes/reviews.py:102-107` implements in exactly that order. The reworked "nothing was written" assertion (`legal_verdict == PASS`, `defamation_findings == 0`) reads back values the fixture's own `record_legal_pass` payload supplied (`test_helpers/factories.py:189-202`), not implementation defaults, so it exposes no PRD silence about a round's initial `defamation_findings` / `privacy_findings`. Pure fixture bug — no edit.

## Pre-edit search log

**Edit 1 (§3.6 intake refusal)**
- (a) Subject: the story `standards_status` gate on correction intake, and the error identifier it raises.
- (b) Paths enumerated (grepped `standards_status` across all of `implementation/`, then read each site): `routes/corrections.py:53` (the gate — `not in ("CLEAN","CORRECTED")` → `ERR_INVALID_STATE`) and `:91` (sets `UNDER_INQUIRY`); `routes/corrections.py:161` (adjudication → `CORRECTED`) and `:185` (dismissal → `CLEAN`); `routes/sources.py:140-141` (revocation drives `CLEAN`/`CORRECTED` → `UNDER_INQUIRY`, so it too can close the intake window); `routes/stories.py:62` (`CLEAN` at creation), `:129` (unpublish → `RETRACTED`), `:157-163` (list filter); `serialize.py:35` (read exposure). Also confirmed the gate's position relative to earlier checks — `auth` → `resolve_body_ids` (404s) → `validate_body` (400s) → state gate — matching §2.12 steps 7/8 before step 11. No other endpoint in the implementation reads `standards_status` for admissibility.
- (c) Wording adjustments: the sentence was written to enumerate the two complement values (`UNDER_INQUIRY`, `RETRACTED`) rather than to say "any other status", because the implementation's gate is a complement test and `RETRACTED` is reachable only via unpublish (`stories.py:129`) — this keeps the retracted-story case correctly refused instead of silently unspecified. It deliberately makes no precedence claim (that is left to §2.12) so it cannot narrow the ordering the implementation exhibits, and it is phrased as an intake-only rule so it says nothing about the un-named state gates on other creation endpoints (e.g. review submission from `DRAFT`, `reviews.py:66-68`), which are outside the Step 7 scope.

_Orchestrator verification_: `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (line 301, §3.6) adding the quoted sentence — a genuine minimal patch, not a no-op copy and not a rewrite.

## Step 9: Complete PRD — 2026-09-05T03:35:00.000Z

_Orchestrator note on method_: Step 9 was executed as **three sequential, module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md`, because a single pass over a 3,040-line implementation reliably under-scans and can return a byte-identical file. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying so they could not destroy earlier edits. Partition: pass 1 = the cross-cutting core (`app.py`, `auth.py`, `calc.py`, `envelope.py`, `errors.py`, `helpers.py`, `serialize.py`, `store.py`, `validation.py`); pass 2 = `routes/{setup,stories,sources,reviews}.py`; pass 3 = `routes/{assignments,corrections,misconduct,conflicts}.py`.

**Net result: 482 lines / 89,659 chars → 482 lines / 105,984 chars (+16,325 chars, 52 changed lines, no new lines and no new sections). 56 ambiguity-pins + 12 mismatch-revisions across the three passes.**

### Pass 1 — cross-cutting core (16 ambiguity-pins, 1 mismatch-revision)

Copy performed: `cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md`. 482 lines / 89,659 chars → 482 lines / 96,898 chars (+7,214 chars, 17 lines changed).

- §2.1 ¶1 — revise — ambiguity — role header matched exactly/case-sensitively; empty header counts as absent — `auth.py:34-38`
- §2.1 last ¶ — insert — ambiguity — ownership binds only an acting `Reporter` (a StandardsEditor/ExecutiveEditor may file training for anyone), and is skipped when the id field is absent or non-string — `auth.py:62-70`
- §2.2 `api_request_id` bullet — insert — ambiguity — `req_` + exactly 20 upper-case-alnum characters — `envelope.py:19-20`
- §2.2 `api_request_timestamp` bullet — insert — ambiguity — read from the host's real UTC clock, not the logical clock — `envelope.py:23-28`
- §2.2 `data` bullet — insert — ambiguity — accepted-but-never-represented fields enumerated (`decision_note`, `findings_note`, `revision_note`, `advance_note`, `appeal_note`, `assigned_note`, `outreach_channel`, `outreach_note`, `resolution_note`, `removal_reason`) — `serialize.py:41-94`
- §2.2 pagination bullet — insert — ambiguity — pagination meta keys appear only on list responses — `envelope.py:38-50`
- §2.3 ¶1 — insert — ambiguity — empty param = default; non-integer / `limit` out of 1..100 / negative `offset` → `ERR_INVALID_REQUEST` 400 (no clamping); no `offset` max; params checked after auth and path resolution — `envelope.py:62-88`
- §2.3 ¶2 — insert — ambiguity — insertion-sequence tie-break on any ordering timestamp; `has_more` = `offset + len(window) < total_count`; filter semantics (exact string equality, empty ignored, out-of-enum matches nothing, unknown params ignored) — `store.py:104-110`, `envelope.py:48`, `envelope.py:91-95`
- §2.4 ¶1 — insert — ambiguity — millisecond digits are truncated, not rounded — `store.py:55-63`
- §2.4 recomputation ¶ — insert — ambiguity — a recompute landing on the stored value moves nothing for newsroom/journalist derived figures, while a reviewer ledger recompute always bumps `updated_at`/`version` — `calc.py:230-234,255-260,311-319,383-398`
- §2.5 ¶2 — revise — ambiguity — `current_utc` in three-fractional-digit form; caller-supplied instants accept `Z`, numeric offsets (normalised) and offset-free (read as UTC); unparseable → `ERR_INVALID_INTERVAL` only for `to_iso8601`, `ERR_INVALID_REQUEST` elsewhere; clock set writes nothing on corrections — `store.py:55-81`, `validation.py:142-148`, `calc.py:181-187`
- §2.6 ¶2 — insert — ambiguity — fixed body-id precedence order for competing 404s; absent/null/non-string ids deferred to body shape — `validation.py:179-206`
- §2.7 last line — insert — ambiguity — JSON numbers drop trailing zeros (`12.50`→`12.5`, `0.00`→`0.0`) — `serialize.py:97-104`
- §2.12 step 8 — revise — ambiguity — unknown-field check first; strict types (bool never an int); absent/empty/`null` body = `{}`; non-object JSON refused; `null` field treated as omitted — `validation.py:78-171`
- §3.4 cascade ¶ — insert — ambiguity — a cascade re-aggregates each reviewer exactly once (one `version` bump for three moved slots), reviewers processed in `created_at` order — `calc.py:263-266,436-446`
- §3.8 disclosure review ¶ — insert — ambiguity — restricted-beats union is ordered oldest-disclosure-first, first-seen, no repeats — `calc.py:333-343`
- §5 intro ¶ — insert — **mismatch** — unknown path / disallowed method answer `ERR_INVALID_REQUEST` with 404 / 405, the only exceptions to that identifier's 400 in the table; trailing slash tolerated — `app.py:49,57-67`

No mismatches found in the error-status catalogue (all 44 identifiers in `errors.py:3-54` agree with §5) or in the enumerations in `validation.py:19-35`.

### Pass 2 — setup / story / source / review routes (18 ambiguity-pins, 5 mismatch-revisions)

No copy made; 20 in-place `Edit` calls. All 17 of pass 1's edits verified intact (10 distinctive phrases each still present exactly once). 482 lines / 96,898 chars → 482 lines / 101,560 chars (+4,662 chars).

- §2.1 (Reporter ownership) — insert — ambiguity — story-mediated ownership (`story_id` → story's `lead_journalist_id`) is skipped when the `story_id` resolves to no story, so `ERR_STORY_NOT_FOUND` wins over the 403 — `sources.py:46-50`, `reviews.py:55-60`
- §2.5 (clock) — insert — ambiguity — `to_iso8601` is a required 1..64-char string; bound breaches are `ERR_INVALID_REQUEST` before any parse — `setup.py:135,141-145`
- §2.8 (stale-view) — insert — ambiguity — `expected_story_version` is an unbounded required integer; 0/negative are 412 not 400 — `reviews.py:21,63`
- §3.1 (journalists) — revise — ambiguity — `email` is 1..320 chars; uniqueness is exact, case-sensitive, newsroom-scoped, collision → `ERR_INVALID_REQUEST` — `setup.py:64,76-79`
- §3.1 (standards summary) — revise — **mismatch** — `published_story_count` counts only `publication_status == PUBLISHED` (removed stories excluded); `open_correction_request_count` is the sum of the stories' own counters; `breached_correction_count` counts only requests whose `breach_flag` is true; the whole read is computed live and writes nothing — `setup.py:163-184`
- §3.2 (story creation) — insert — ambiguity — risk figures are computed inside the creating operation, so the story returns with `version` 1 — `stories.py:74-76`
- §3.2 (requesting anonymity) — revise — ambiguity — `justification_text` required and may be empty; alias uniqueness spans the story's approvals in any status by exact comparison; no story-state precondition; `decided_by_user_id`/`decided_at`/`revocation_reason` start null — `sources.py:27,53-56,69-72`
- §3.2 (deciding) — insert — ambiguity — the approval's path id resolves before the segregation test, so `ERR_SOURCE_APPROVAL_NOT_FOUND` outranks it — `sources.py:81-85`
- §3.2 (revoking) — revise — ambiguity — `revocation_reason` required, 1..4000 chars — `sources.py:36`
- §3.2 (revoking) — revise — **mismatch** — `risk_index_actual` recomputed "whenever that figure already exists" rather than "when the story is `PUBLISHED`" — `sources.py:139`, `calc.py:104-107`
- §3.5 (retrospective index) — insert — ambiguity — every `risk_index_actual` recomputation is conditional on the figure existing; null stays null pre-publication, maintained after removal — `calc.py:104-107`
- §3.5 (publish) — insert — ambiguity — no body is read or validated, so unknown fields in a supplied body are ignored — `stories.py:79-100`
- §3.5 (unpublish) — insert — ambiguity — `removal_reason` and `editors_note_text` both required, 1..4000 chars — `stories.py:29-32`
- §3.5 (story reads) — insert — ambiguity — identifier-valued list filters are string-matched, never resolved; a non-existent id yields an empty page, not a 404 — `stories.py:154-164`, `envelope.py:91-95`
- §3.3 (submission) — insert — ambiguity — new round starts with `legal_verdict`/`standards_verdict`/`cleared_at` null but `defamation_findings`/`privacy_findings` at 0 — `reviews.py:86-89`
- §3.3 (submission) — revise — ambiguity — optional narrative notes accept up to 4000 chars and may be empty; the estimate is recomputed *before* `requires_legal_review` is pinned — `reviews.py:23,76-82`
- §3.3 (`requires_legal_review`) — revise — **mismatch** — never revisited, not even by a resubmission opening a further round on the same record — `reviews.py:213-217`
- §3.3 (legal track) — revise — ambiguity — a legal `PASS` does not write the story at all; a send-back returns it to `DRAFT` only from `IN_REVIEW` but bumps `version` either way — `reviews.py:41-48,113-115`
- §3.3 (standards track) — insert — **mismatch** — a standards `BLOCK` is a valid enum member with no declared transition: `ERR_INVALID_STATE`, decided ahead of the round-open and legal-precedence tests — `reviews.py:134-142`
- §3.3 (resubmission) — revise — **mismatch** — `defamation_findings`/`privacy_findings` are *not* cleared; the story is driven to `IN_REVIEW` whatever `publication_status` it held — `reviews.py:213-221`
- §3.3 (clearing) — insert — ambiguity — no body read or validated, contents ignored — `reviews.py:156-159`
- §3.3 (clearing) — revise — ambiguity — story goes to `CLEARED` only from `IN_REVIEW`, `version` bumps either way — `reviews.py:177-180`
- §3.3 (clearing) — insert — ambiguity — `REVIEW_CLEARED` names the story (`subject_type` `Story`, `subject_id` the story's id) because the subject enum has no review member — `reviews.py:186-189`

Behaviors checked and left alone as already uniquely pinned: bootstrap exemptions, newsroom/reviewer creation defaults and initial ledger, publish's five gates (impl order matches §2.12 exactly), unpublish justification, the `_send_story_back` booking cascade, audit-event ordering by `occurred_at`, and every list endpoint's role set and filter set.

### Pass 3 — assignment / correction / misconduct / conflict routes (22 ambiguity-pins, 6 mismatch-revisions)

No copy made; 22 in-place `Edit` calls. Passes 1–2 edits verified intact (seven distinctive insertions each found exactly once; their 34 modified lines still divergent from `PRD_FINALIZED.md`). 482 lines / 101,560 chars → 482 lines / 105,984 chars (+4,424 chars).

- §3.4 — insert — ambiguity — booking imposes no state precondition on the round (any stage, terminal included), writes neither review nor story, and starts with `cancellation_reason` null — `routes/assignments.py:45-96`
- §3.4 — revise — ambiguity — `cancellation_reason` is a required string of 1 to 4000 characters — `routes/assignments.py:28`
- §3.4 — insert — ambiguity — cascade-cancelled bookings leave `cancellation_reason` null — `routes/misconduct.py:67-71`
- §3.6 — revise — ambiguity — `submitter_email` bounded 1 to 320 characters — `routes/corrections.py:20`
- §3.6 — insert — ambiguity — intake nulls: `outcome_type`, `adjudicated_error_category`, `verified_reach`, `notice_text`, `notice_published_at`, `resolved_at` — `routes/corrections.py:74-87`
- §3.6 — insert — ambiguity — `outreach_channel` required, 1 to 200 characters — `routes/corrections.py:30`
- §3.6 — revise — ambiguity — `adjudicated_error_category` and `verified_reach` required whatever the outcome, reach non-negative, `notice_text` 1 to 4000 — `routes/corrections.py:34-39`
- §3.6 — insert — **mismatch** — path identifier resolved *before* the segregation test (§2.12 ladder puts step 5 first), so a bad `{id}` reports `ERR_CORRECTION_REQUEST_NOT_FOUND` — `routes/corrections.py:126-130`
- §3.6 — revise — ambiguity — `POSTURE_CHANGED` is appended *ahead of* `CORRECTION_ADJUDICATED` — `routes/corrections.py:166-172`
- §3.6 — insert — ambiguity — dismissal still writes the full verified account (category, reach, score, band) — `routes/corrections.py:176-177`
- §3.6 — revise — ambiguity — dismissal emits no audit event at all — `routes/corrections.py:173-186`
- §3.6 — revise — ambiguity — on resolve, `POSTURE_CHANGED` *follows* `CORRECTION_RESOLVED` — `routes/corrections.py:209-216`
- §3.6 — insert — ambiguity — resolve does not write `standards_status`; it stays `CORRECTED` and never returns to `CLEAN` — `routes/corrections.py:200-208`
- §3.7 — insert — ambiguity — investigation opens with `decided_by_user_id`, `decided_at`, `appeal_outcome` null — `routes/misconduct.py:99-102`
- §3.7 — insert — ambiguity — `prior_sustained_count` at opening is the real count, not 0 — `routes/misconduct.py:96`
- §3.7 — revise — **mismatch** — advancing from `RESPONSE_PENDING` is also refused, not only a decided case — `routes/misconduct.py:117-124`
- §3.7 — insert — **mismatch** — path resolution precedes segregation on decide — `routes/misconduct.py:132-135`
- §3.7 — insert — ambiguity — suspension cascade fires on the `ACTIVE → SUSPENDED` transition only — `routes/misconduct.py:170-171`
- §3.7 — revise — **mismatch** — non-terminal rounds of **every** story the journalist leads are blocked, not only those at `IN_REVIEW` — `routes/misconduct.py:54-66`
- §3.7 — revise — ambiguity — cascade audit order: `INVESTIGATION_SUSTAINED`, then `ACTIVITY_REVOKED` in `created_at` order, then `POSTURE_CHANGED` last — `routes/misconduct.py:174-183`
- §3.7 — insert — **mismatch** — path resolution precedes segregation on appeal — `routes/misconduct.py:190-193`
- §3.8 — insert — ambiguity — disclosure created with `reviewed_by_user_id` and `reviewed_at` null — `routes/conflicts.py:81-82`
- §3.8 — insert — ambiguity — `restricted_beats` supplied with `ACKNOWLEDGE`/`REJECT` is validated then ignored — `routes/conflicts.py:106-112`
- §3.8 — insert — ambiguity — the non-empty-beats requirement is `ERR_INVALID_REQUEST` and is decided *before* the state check — `routes/conflicts.py:95-101`
- §3.8 — insert — ambiguity — repeated labels in the payload collapse to first appearance in the stored array — `routes/conflicts.py:107-112`
- §3.8 — insert — ambiguity — activity created with `decided_by_user_id`, `decided_at`, `revocation_reason` null — `routes/conflicts.py:155-157`
- §3.8 — insert — ambiguity — `case_study_reference` 1 to 200 chars, may **not** be empty (unlike narrative notes), defaults null, is stored and returned — `routes/conflicts.py:48`
- §4 — revise — **mismatch** — investigations list row now names the `allegation_type` filter, matching §3.7 and the impl — `routes/misconduct.py:240`

Closing integrity check — **PASS**: 482-line structure preserved; 25 headings, sections 1–5 in order (`## 1` L3, `## 2` L11, `## 3` L209, `## 4` L371, `## 5` L433) with §2.1–2.12 and §3.1–3.8 present and sequential; file ends correctly on the last error-table row (no truncation); §4 endpoint table 57 rows all exactly 4 columns, §5 error table 46 rows; duplicate-sentence scan found only two legitimate pre-existing repeats — no sentence duplicated by any pass's edits.

Judgement call recorded by pass 3: §3.5's claim that `risk_index_actual` is recomputed "on every subsequent correction adjudication" was left untouched even though `routes/corrections.py:162-164` recomputes it only for `MAJOR`/`SEVERE` bands — the narrower §3.6 sentence is precise and the difference is unobservable (a `TRIVIAL`/`MINOR` adjudication contributes nothing to the figure), so revising it would have been churn.

_Orchestrator verification_: `PRD_COMPLETED.md` is 482 lines / 105,984 chars and differs from `PRD_FINALIZED.md` on 52 lines (`cmp` confirms NOT byte-identical, so the scan genuinely ran); tail ends on the final error-table row, not mid-sentence. `find workspace/implementation -newer results.1.json -name "*.py"` returned nothing — no implementation file changed after the clean sweep, so the 8/8 × 105/105 result recorded in Step 7 still describes the delivered code.

---

## Pipeline complete — 2026-09-05T03:35:00.000Z

All nine steps finished. Final state: 55 endpoints, 105 tests, 8/8 sweep rounds at 105/105, and `workspace/PRD_COMPLETED.md` written.
