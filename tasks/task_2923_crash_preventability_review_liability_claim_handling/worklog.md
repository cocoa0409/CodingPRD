# Worklog — task_2923_crash_preventability_review_liability_claim_handling

## Step 1: Create task directory — 2026-09-05T17:03:06.673Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2923_crash_preventability_review_liability_claim_handling` and its `workspace/` subdirectory. Index 2923 was pre-assigned by the invoking prompt; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-05T19:28:32.951278892Z

Scaffold generation for task 2923 is complete and lint-clean.

Output files (all in `/home/ubuntu/github/CodingPRD/tasks/task_2923_crash_preventability_review_liability_claim_handling/`)

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3,260 | 178,936 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2,208 | 162,971 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4,647 | 333,514 |

Lint verdict:

    §1.5 endpoints declared:    56
    §1.1 entities declared:     13
    §1.8 instances scanned:     18
    §1.9 instances scanned:     48   (48 with recipes; 65 total incl. 17 excluded_because stubs)
    Calls scanned (§1.8+§1.9):  975
    VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.

Contents:
- `SCAFFOLD.yaml` — §1.0–§1.7 only (verified: zero occurrences of `scaffold_difficulty_design` / `scaffold_corner_design`). 13 entities, 11 state machines, 2 concurrency rules, 10 calculations, 2 invariants, 33 validations, 56 endpoints, 63 errors, 8 roles; `api_prefix: ""`, money in integer cents, `round_half_up`, logical clock. Profile: `expert_plus` / `multi_party_negotiation` + `compliance_audit`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`, flat topology, cyclic state machines, `segregation_of_duties`, `immediate`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`, 9 rule groups × 2 = 18 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`, all nine guide sections present: entities 13, state_machines 16, calculations 13, validations 9, endpoints 5, errors 1, rbac 3, complexity_layers 4, consistency_model 1.

Verified invariants beyond the lint:
- 83 instance names unique across §1.8 ∪ §1.9; all 17 corner stubs cite an existing §1.8 name (no corner→corner citations); every instance has `claim_type`/`grounds`/`distinguishing_aspect` plus either a complete `test_recipe{setup,setup_api_calls,trigger,assert}` or a complete `excluded_because{difficulty_instance,rationale}`.
- Error-catalog census: all 63 errors are triggered. The last three holes were closed: `ERR_FUTURE_TIMESTAMP` (errors/triggerability instance), `ERR_CLAIM_VERSION_STALE` + `ERR_REVIEW_CASE_VERSION_STALE` (the `optimistic_concurrency` instance, with stale versions written as captured `${...}` expressions per lint check (e)), and `ERR_UNAUTHENTICATED`/`ERR_UNAUTHORIZED`/`ERR_SEGREGATION_OF_DUTIES` (the three rbac instances).

Two scaffold-consistency bugs found and fixed while writing §1.9: the `terminal_crash_rate` note contradicted its own half-open formula (edited in `SCAFFOLD.yaml`), and the corner file used a non-existent enum literal `THIRD_PARTY_PROPERTY_DAMAGE` where `Demand.claimant_type` declares `THIRD_PARTY_PROPERTY` (2 occurrences corrected).

Orchestrator note: after the subagent exited, the orchestrator stripped a trailing YAML comment on `complexity_profile.difficulty_level` that referenced the generation difficulty directive, so no difficulty-directive wording can reach PRD.md via SCAFFOLD.yaml. The `scenario:` key was verified to contain the scenario text only.

## Step 3: Copy shared files — 2026-09-05T19:28:32.966211126Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T19:48:47.258224049Z

PRD generation complete.

**Output**: `workspace/PRD.md` — **490 lines**, built entirely by chunked `cat >>` heredoc appends (12 chunks). The file ends at a completed final section: the last heading is `## 5. Error Code Catalogue` (line 422) and the last line is the final table row `| \`ERR_RESERVE_INSUFFICIENT\` | 422 |`. No truncation, no mid-sentence ending.

**Structure**: `# Title` / `## 1. Introduction` / `## 2.` with ten subsections (2.1 RBAC, 2.2 verbatim response block, 2.3 pagination and ordering, 2.4 identity/versioning/append-only, 2.5 logical clock and re-derived fields, 2.6 optimistic concurrency, 2.7 money and the conserved exposure ledger, 2.8 the 16-step validation ladder, 2.9 path resolution and reverse-reachability, 2.10 cascades and compensations) / `## 3.` with nine domain subsections (terminal network and roster, crash intake and filing clock, driver statement and evidence custody, committee deliberation/determination/appeal, driver accountability, claim setup, policy tower and negotiation ledger, settlement and rescission, subrogation/closure/analytics) / `## 4.` 4-column table, 56 rows / `## 5.` 2-column table, 63 rows. Table-line count 123 = 58 + 65, confirming both tables are complete.

**Hard Contract results (all mechanically verified against SCAFFOLD.yaml):**
- **Contract 1 — Field-Name Coverage: PASS.** 170 required identifiers (all `entities[].fields[].name`, all endpoint `input` names with `?` stripped, all `{id}` path params, all computed-read output keys, both OCC fields) all appear verbatim inside backticks. Missing count 0. Two late repairs were needed: `review_case_id` (added to the ballot-creation sentence in §3.4) and `demand_id` (added to the round-creation sentence in §3.7).
- **Contract 2 — Rule Coverage: PASS.** All 63 error IDs appear in §2/§3 prose in addition to the §5 catalogue (absent-from-body count 0). Every state-machine state across all dimensions, and every entity field enum value, appears in the prose (both absent-lists empty). Every numeric constant in every `calculations` block appears verbatim except `EXPENSE_RATIO 0.18`, which is expressed as "18 percent" — semantically exact. The 16-step ladder in §2.8 mirrors the scaffold's priority bands 1→72 including both OCC rules at band 28 and the coverage-before-reserve ordering (70 before 72). No pseudocode operators survive anywhere in the document.
- **Contract 3 — §3 Path Purity: PASS.** Zero backticked tokens in the §3 span start with `/`, are a bare HTTP method, or combine method and path.

**Corrections made during verification**: six §4 filter lists initially used invented names; they now match the scaffold's endpoint inputs exactly — `/drivers` uses `status` and `required_action_tier`, `/crashes` uses `reporting_status`, both evidence-item lists use `preservation_state`, `/review-cases` uses `appeal_evidence_item_id`, the ballot list uses `vote`, and `/disciplinary-actions` uses `action_type`. §3 prose had used the correct names throughout.

Neither design index was opened, grepped, or referenced.

Orchestrator verification: independently confirmed 490 lines, five `## ` headings ending at `## 5. Error Code Catalogue`, final line a complete table row, and zero occurrences of the difficulty-directive wording in PRD.md.

## Step 6: Generate implementation — 2026-09-05T20:27:37.872930707Z

(Steps 5 and 6 were launched concurrently in a single orchestrator message, per the skill. Step 6 returned first, so its entry is recorded first; Step 5's entry follows below.)

All four smoke suites pass and the implementation is complete. Servers stopped (ports 53923/53924 verified free).

## What was done in this session

Wrote and ran three additional end-to-end smoke suites (beyond the original happy-path one), plus an automated role-matrix probe, against `PORT=53923 bash start.sh`. **Every failure found was in my test expectations, not in the implementation — zero source files needed changing** (all mtimes predate this session).

Verification coverage added:
- **smoke2** — validation guards (pagination bounds, unknown body field, `terminal_code`/precision patterns, 404s, 403s), malformed/duplicate tower, `ERR_DRIVER_STATEMENT_REQUIRED` + waiver, `ERR_NO_PRESERVED_EVIDENCE`, OCC on the review case, abstain-with-scores rejection, weighted score 2.47 under the 4-criterion renormalisation, SoD on decide and appeal, discipline ladder (tier insufficient → driver/crash mismatch → ±24h suspension buffer → CRITICAL staffing override), and the **full appeal unwind** (points 8.0 → 0.0, actions ISSUED → VOIDED with `retraining_status` reset, driver back to ACTIVE, terminal counts and `preventable_crash_count` restored, second decide → CLOSED_FINAL + `appeals_exhausted`).
- **smoke3** — LATE_FILED filing, COMPROMISED posture via `PURGED_BEFORE_HOLD`, ballot supersession (5 rows, 1 superseded, 3 active + 1 abstain), `WEIGHTED_CRITERIA` basis disagreeing with the majority, risk 80/1.60/counsel-required, provisional reserve 227,200,000, and the PRD's exact worked settlement example: offer 13,392,857 → alae 1,607,143 → total 15,000,000 allocated 10,000,000 SIR + 5,000,000 PRIMARY; **rescission restoring every field to the cent** (allocations emptied, `sir_eroded`/`insured_paid` back to 0, subrogation back to DRAFT with null ceiling, exposure conserved at 227,200,000), then offer 13,392,858 → `ERR_COVERAGE_EXHAUSTED` (422) with no drift; `ERR_RESERVE_INSUFFICIENT`, `ERR_OPEN_DEMANDS_REMAIN`, SETUP→CLOSED no-liability closure, list `meta` (`limit`/`offset`/`total_count`/`has_more`), and crash-analytics under both bases with `by_route_class`/`by_tenure_band`.
- **smoke4** — `ERR_UNAUTHENTICATED` (401) for missing/blank/unknown role, retraining issuance → completion → reinstatement → CONTINUE, suspension elapse boundary (`ERR_SUSPENSION_NOT_ELAPSED` at exactly `suspension_end_at`, success one second later) with terminal posture STRAINED → OK, `ERR_APPEAL_WINDOW_CLOSED`, `ERR_RETENTION_DEADLINE_PASSED`, `ERR_NO_THIRD_PARTY_AT_FAULT`, SCENE_PHOTO exempt from the duplication test, subrogation DENIED path + closure, and point decay across the 365/730-day bands (4.0 → 2.0 → 0.0).
- **Role matrix probe** — all 56 PRD endpoints × 8 roles compared against the PRD's authorized lists: exactly one intentional divergence (`POST /crashes/{id}/driver-statements`, where band-3 driver ownership correctly rejects a Driver whose `X-User-ID` is not a driver row).

Fresh-boot check: an empty server returns `total_count: 0` for terminals and claims with the clock at `2026-08-01T00:00:00.000Z` — no seeding, in-memory only.

## File inventory

`workspace/implementation/`

| file | bytes | lines |
|---|---|---|
| `start.sh` (exec) | 399 | 10 |
| `requirements.txt` | 13 | 1 |
| `app.py` | 2156 | 66 |
| `store.py` | 1737 | 74 |
| `errors.py` | 3082 | 86 |
| `envelope.py` | 2052 | 84 |
| `auth.py` | 1905 | 58 |
| `shape.py` | 9218 | 251 |
| `calc.py` | 18566 | 535 |
| `serializers.py` | 10689 | 284 |
| `common.py` | 3066 | 105 |
| `routes/__init__.py` | 0 | 0 |
| `routes/core.py` | 9526 | 268 |
| `routes/crashes.py` | 10687 | 275 |
| `routes/review.py` | 11290 | 275 |
| `routes/discipline.py` | 6906 | 164 |
| `routes/claims.py` | 8817 | 230 |
| `routes/demands.py` | 12731 | 312 |
| `routes/subrogation.py` | 4095 | 106 |

Total 3,184 lines across 19 files (`__pycache__` removed). Scratch confined to `/tmp/task_2923_impl/`; `test_suite/`/`test_helpers/` were never read.

## Step 5: Generate unit tests — 2026-09-05T22:07:29.235340859Z

(Launched concurrently with Step 6 in one orchestrator message; Step 5 returned second.)

Step 5 is complete. The full test infrastructure and test suite are generated at the task root.

## Final inventory

`test_helpers/` — 9 files, 2,692 lines
`__init__.py` 40, `api_client.py` 335, `api_errors.py` 163, `assertions.py` 384, `constants.py` 421, `factories.py` 453, `fixtures.py` 504, `test_users.py` 109, `types.py` 283

`test_suite/` — `conftest.py` (8) + 18 test modules, 14,978 lines, **194 tests**
`test_01` 495 / `test_02` 353 / `test_03` 476 / `test_04` 504 / `test_05` 375 / `test_06` 440 / `test_07` 579 / `test_08` 490 / `test_09` 767 / `test_10` 1385 / `test_11` 1724 / `test_12` 2158 / `test_13` 2381 / `test_14` 1049 / `test_15` 312 / `test_16` 857 / `test_17` 332 / `test_18` 301

## Work finished this session

- `test_17_optimistic_concurrency.py` (332 lines, 3 tests) — the single non-stub `complexity_layers` instance. Ballot OCC (`ERR_REVIEW_CASE_VERSION_STALE` 412 leaves `version`, `next_vote_sequence` and the vote ledger unmoved, retry at the fresh version succeeds), reserve OCC (`ERR_CLAIM_VERSION_STALE` 412 leaves `revised_reserve_cents`, `outstanding_reserve_cents`, `reserve_status`, `version` untouched), and the cross-endpoint case where demand creation advances `Claim.version` and thereby staleness a revision prepared before it.
- `test_18_derived_field_immediacy.py` (301 lines, 4 tests) — the single `consistency_model` instance. Terminal headcount and driver bands current in their own write responses; the intake response already carrying frozen recordability `[DISABLING_TOW]`, `report_due_at` = occurred + 72 h, `PENDING_FILING` / `REPORTED` / `PARTIAL`; the preserve request flipping posture `PARTIAL → COMPLETE`; and the claim create response carrying score 5, `counsel_required` false and 500,000 in all four money fields, with each followed by a read that must repeat the write.

## Design-index coverage (verified mechanically)

- **66 / 66 non-stub instances covered** (queue A 18 + queue B 48); zero uncovered.
- Zero `excluded_because:` stubs translated; zero tags pointing at non-existent instances; every test carries exactly one `Design:` line; every queue A instance has ≥2 tests.
- `python3 -m pyflakes` clean across all 28 files (only the deliberate `# noqa: F401` re-exports in `test_helpers/__init__.py` are reported, which flake8 honours); `compileall` clean; `__pycache__` removed.
- No occurrence of "scaffold" or a `§` reference anywhere in either output directory.
- Nothing written under `workspace/`; no server started, no pytest run, no `pkill`.

## Two corrections worth relaying

1. The design's `consistency_model` assertion says `litigation_risk_score == 10`, but its own parenthetical ("REPORTED 5 plus COMPLETE posture 0 plus nothing else") and PRD 277 both give **5**. The test asserts 5.
2. Carried forward from earlier files, the PRD overrides the design on: `ERR_APPEAL_EVIDENCE_INVALID` / `ERR_SEPARATION_NOT_SUPPORTED` / `ERR_NO_THIRD_PARTY_AT_FAULT` / `ERR_RESCISSION_WINDOW_CLOSED` / `ERR_APPEAL_WINDOW_CLOSED` = 409; `ERR_COVERAGE_EXHAUSTED` / `ERR_OPEN_DEMANDS_REMAIN` = 422; `POST /review-cases/{id}/votes` = 201; pagination keys sit directly on `meta`, not `meta.pagination`.

## Step 7: Run tests and iterate — 2026-09-05T22:48:18.616053397Z

Clean sweep. All 8 rounds green.

## Summary

**Iterations run: 2**
- Iteration 1 — baseline 8-round sweep: 185/194 in all 8 rounds, 9 failures, perfectly deterministic (zero flakiness, so no reaping or CPU-contention artifact to discount). An independent local per-test pass reproduced exactly the same 9.
- Iteration 2 — after the 8 fixes below: 194/194 in all 8 rounds.

**Tests deleted: none.** Every one of the 9 failures traced to an assertion or fixture that the PRD verbatim covers and uniquely determines, so no test met the PRD-silence or non-unique-derivability criteria. No assertion was weakened: no `error_id` downgraded to a bare status, no boundary loosened, no `skip`/`xfail`, no relaxation to `validate_error_is_one_of`.

**Fixes to `test_helpers/` (1)**
- `test_helpers/factories.py` — `_payload()`: the `DROP` sentinel was only honoured for keys arriving via `**overrides`, so `cdl_number=factories.DROP` (a *declared named parameter*, landing in `base`) leaked the sentinel object into the JSON body instead of omitting the field. Now both maps are scrubbed.

**Fixes to `test_suite/` (7)**
- `test_03_non_linear_case_and_claim_state_machines.py` — second-appeal test expected `ERR_APPEALS_EXHAUSTED`, but the case is `CLOSED_FINAL` and PRD §3.4's state guard (ladder band 8, *State legality*) runs ahead of band 9 (*Appeal exhaustion*); corrected to `ERR_REVIEW_CASE_STATE_INVALID` + 409 and re-cited the governing sentence.
- `test_04_transitive_cascades.py` — `crash["version"] == context["crash"]["version"] + 1` compared against the *intake* snapshot (v1); opening deliberation already bumped the crash to v2, so the PRD's "+1" is measured from the version standing immediately before the determination. Now reads the crash just before deciding.
- `test_10_entity_records_and_listings.py` — declaration-order test read `error_id` off the raw envelope; `error_id` lives under `data`. Switched to the already-unwrapping `assert_error_envelope`.
- `test_11_state_machine_transitions.py` — same wrong unwrap on the duplicate-create test; now captures `validate_error(...)`'s unwrapped return.
- `test_13_validation_rules_and_ladders.py` — `_deliberating_case_and_draft_recovery()` returned the stale intake crash (`REPORTED`) despite its own docstring promising "a crash still under review"; it now re-reads the crash after `build_case_in_deliberation`.
- `test_13_validation_rules_and_ladders.py` — a test-internal premise line asserted `FOSTORIA_TOTAL_A_CENTS < FOSTORIA_OUTSTANDING_AFTER_B_CENTS` (972,000 < 852,000), arithmetically false. Every FOSTORIA constant was verified against the implementation and the true relation is `>`, which is precisely the case PRD §"Two money guards" names: "A file that is both uncovered and underreserved reports the coverage failure, never the reserve failure." Flipped the operator and re-cited that sentence — this strengthens the precedence claim rather than dropping it. (Editing `FOSTORIA_DEMAND_A_CENTS` instead would have broken two passing sibling tests.)
- `test_15_error_catalogue_triggers.py` — local `_crash_payload()` passed a hardcoded `location_text` *and* `**overrides`, a duplicate-keyword `TypeError` whenever a caller overrode it. Overrides now merge over the defaults.

**Fixes to `implementation/`: none.** All 9 failures were test-artifact defects; the implementation was PRD-faithful in every case. Verified `implementation/` still holds state in memory only — no sqlite, pickle, shelve, JSON dump or `/tmp` cache, and nothing seeded at boot.

**Final per-round counts (8-round parallel sweep, `--isolation per-test-server`, `--timeout 120`, `--test-timeout 30`, no `-k`):**

| round | passed | total |
|---|---|---|
| 1 | 194 | 194 |
| 2 | 194 | 194 |
| 3 | 194 | 194 |
| 4 | 194 | 194 |
| 5 | 194 | 194 |
| 6 | 194 | 194 |
| 7 | 194 | 194 |
| 8 | 194 | 194 |

0 failed, 0 errors, 0 skipped in every round; no round log contains `Terminated` or `ServerStartError`. Evidence left in place at `workspace/implementation/results.{1..8}.json` with per-round logs at `workspace/round.{1..8}.log`. `worklog.md` was not touched.

Orchestrator verification: independently parsed all 8 `results.*.json` after the sentinel appeared — every round reports `passed 194 / total 194`. Baseline (185/194 × 8) was also independently observed before the fix round, confirming the sweep genuinely ran twice.

Orchestrator decision on Step 8: NOT skipped. The skip condition requires zero deletions AND zero `test_suite/` fixes AND zero `test_helpers/` fixes AND zero `implementation/` fixes; Step 7 made 8 test-artifact fixes across 2 iterations. Because there were 0 `implementation/` fixes, a byte-identical `PRD_FINALIZED.md` is a legitimate outcome here — the Step 7 diff may contain no genuine PRD silence. Step 9 will still run the full scan regardless.

## Step 8: Finalize PRD — 2026-09-05T22:59:10.254274675Z

`PRD_FINALIZED.md` produced. It is **byte-identical to `PRD.md`** — all eight `<step_7_diff>` items are pure test-artifact defects; none exposes a PRD silence or a PRD/impl mismatch.

## Line counts
- `PRD.md`: 490 lines
- `PRD_FINALIZED.md`: 490 lines
- Delta: **0 lines, 0.00%** (md5 `cab6ce68d0fac83c19201e9ce5cff0be` on both)

## Changes
None. No PRD section was inserted or revised.

## Per-item adjudication (subject / impl paths enumerated / verdict)

**1. `factories.py` `_payload()` DROP sentinel (`cdl_number=DROP`)** — Subject: which driver-hire inputs are required. Paths: `routes/core.py:181` (`f("cdl_number","string",required=True)`), `:200`; `shape.py` required-field handling. Verdict: PRD §3.1 lists `cdl_number` among the fields the hiring request "carries" with no "optional" marker (contrast the explicitly-optional `adjuster_note`, `conditions_note`, `comment`, `statement_waiver_reason`), and §2.8 band 4 makes a missing required input `ERR_INVALID_REQUEST`. Determined. No edit.

**2. `test_03` second appeal: `ERR_REVIEW_CASE_STATE_INVALID` not `ERR_APPEALS_EXHAUSTED`** — Subject: appeal guard ordering and the reachability of `ERR_APPEALS_EXHAUSTED`. Paths: `routes/review.py:205-244` (full guard chain: shape 216-221 → case lookup 222 → evidence-item body ref 225 → state `DECIDED` 226 → exhaustion 230 → SoD 233 → appeal window 236 → appeal-evidence 240), plus the `CLOSED_FINAL` producer at `review.py:187-198` and every `appeals_exhausted` site (`crashes.py:68`, `review.py:197,230`). Verdict: PRD §3.4 already enumerates "appealing a case in `DRAFT`, in `DELIBERATION` or in `CLOSED_FINAL` is `ERR_REVIEW_CASE_STATE_INVALID`" and states the guards "run in the ladder's order" (band 8 before band 9). Impl matches band-for-band. `ERR_APPEALS_EXHAUSTED` is in fact unreachable in the impl (a case with `appeal_round>=1` always sits in `CLOSED_FINAL`), which is consistent with — not contradicted by — the PRD text. Determined. No edit.

**3. `test_04` crash `version` measured against the intake snapshot** — Subject: which operations bump `Crash.version`. Paths: every `touch(crash)` in the impl — `routes/review.py:56` (case creation), `:198` (determination), `:257` (appeal), `routes/crashes.py:105` (regulatory filing). Confirmed `open_deliberation` (`review.py:78-93`) touches only the case. Verdict: PRD §3.4 already says opening a case moves the crash `REPORTED → UNDER_REVIEW` and "its `version` increases by 1", and that opening deliberation "bumps the case's `version`" only; §2.4/§2.10 give the +1-per-mutation rule. Determined. No edit.

**4. `test_10` `error_id` read off the raw envelope** — Subject: error envelope shape. Paths: `envelope.py`, `errors.py:fail`. Verdict: PRD §2.2 places `error_id` inside `data`. Determined. No edit.

**5. `test_11` same wrong unwrap on duplicate-create** — Subject: same as (4), plus duplicate-review-case precedence. Paths: `routes/review.py:29-34` (`ERR_REVIEW_CASE_EXISTS` checked before the crash-state guard). Verdict: PRD §3.4 and §2.8's closing paragraph both pin the referential-over-state precedence; §2.2 pins the envelope. Determined. No edit.

**6. `test_13` `_deliberating_case_and_draft_recovery()` returned the stale `REPORTED` crash** — Subject: crash state after a review case opens. Paths: `routes/review.py:55-56`. Verdict: PRD §3.4 "the crash moves `REPORTED → UNDER_REVIEW`". Determined. No edit.

**7. `test_13` arithmetically false premise line (coverage vs. reserve guard)** — Subject: settle-time guard ordering. Paths: `routes/demands.py:186-206` — demand state → claim `CLOSED` → `ERR_POLICY_TOWER_MALFORMED` → `calc.allocate` leftover → `ERR_COVERAGE_EXHAUSTED` → `ERR_RESERVE_INSUFFICIENT`; plus `calc.allocate`/`calc.tower_well_formed`. Verdict: PRD §3.8 "Two money guards then run, in this order… A file that is both uncovered and underreserved reports the coverage failure, never the reserve failure", corroborated by §2.8 band 16. Impl matches exactly. Determined. No edit.

**8. `test_15` `_crash_payload()` duplicate-keyword `TypeError` on `location_text`** — Subject: `location_text` at intake. Paths: `routes/crashes.py:22` (`required=True`), `:54`. Verdict: a Python duplicate-keyword defect in a test-local helper; PRD §3.2 already treats `location_text` as required free text. No PRD implication. No edit.

## Note
Per the pipeline's own guidance, a byte-identical `PRD_FINALIZED.md` is the correct outcome when Step 7 applied zero `implementation/` fixes and zero test deletions, as here. Step 9 must still produce a non-identical `PRD_COMPLETED.md`.

Orchestrator verification: confirmed both files are 114,025 bytes with identical content. Step 9 will run as three sequential module-partitioned passes over one shared `PRD_COMPLETED.md` (pass 1 performs the copy; passes 2 and 3 must not re-copy), so that a single subagent's output budget cannot silently swallow the scan.

## Step 9: Complete PRD — 2026-09-05T23:21:04.517439275Z

Run as three sequential module-partitioned passes over one shared `workspace/PRD_COMPLETED.md`. Pass 1 performed the single `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes 2 and 3 edited it in place with targeted anchored Edits only (no `cp`, no whole-file `Write`), so no pass could overwrite an earlier pass's work. Final result: **490 lines / 134,200 chars** vs the 490-line / 114,025-char source — **+20,175 chars across 50 revised line-pairs**, all in-paragraph, no new sections. Totals across the three passes: **43 ambiguity-pins, 11 mismatch-revisions (54 changes)**.

### Pass 1 — plumbing + `routes/core.py` (13 ambiguity-pins, 3 mismatch-revisions)

Scope: `app.py`, `envelope.py`, `errors.py`, `auth.py`, `shape.py`, `store.py`, `common.py`, `serializers.py`, `routes/core.py`. Result after pass: 490 lines / 122,290 chars (+8,265).

- §2.1 — revise — ambiguity — whitespace-only headers count as empty; role match is exact/case-sensitive; `X-User-ID` inspected before `X-User-Role` — auth.py:42-49
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from A–Z/0–9 — envelope.py:12,16
- §2.2 — revise — ambiguity — `api_request_timestamp` is read from the logical clock, not wall time, so it is identical on every response until the clock moves — envelope.py:52
- §2.3 — revise — ambiguity — non-integer/empty/decimal `limit`/`offset` are 400 (whitespace tolerated); enum-filter violations and non-`true`/`false` bool filters are 400; undeclared query params are ignored; identifier filters are never existence-checked — shape.py:205-251
- §2.3 — insert — ambiguity — equal-`created_at` ties broken by insertion order — store.py:58-60
- §2.4 — insert — ambiguity — server renders instants only in canonical 3-digit `Z` form, but accepts `T`/`t`, `Z`/`z`, numeric `±HH:MM` offsets (converted to UTC) and 1–9 fractional digits; dates strictly `YYYY-MM-DD` — envelope.py:19-26, shape.py:14-79
- §2.4 — insert — ambiguity — audit fields are the trailing keys in fixed order `created_at`, `updated_at`, `version`; `id` first; never alphabetised; derived fields occupy fixed slots — app.py:26, serializers.py:14-19
- §2.4 — insert — ambiguity — on the four append-only types `created_at` is the final key — serializers.py:103,162,209,247
- §2.5 — insert — ambiguity — clock set is unconditional (may wind backwards, no upper bound) and its `data` is the single key `current_utc`; no row's `version` moves — routes/core.py:22-27
- §2.8 band 4 — insert — ambiguity — absent/blank body = `{}`, non-object body is a shape violation; explicit `null` == absent (a required field so given is reported *missing*); all strings must be non-blank after trim but are stored untrimmed; booleans never accepted for numeric fields and vice versa; unknown-field check precedes missing-required precedes per-value type — shape.py:82-193
- §2.9 — insert — ambiguity — trailing slash insignificant; unknown path → `ERR_INVALID_REQUEST` at 404, undeclared method → `ERR_INVALID_REQUEST` at 405 (both outside the 400 tabulated in §5), and routing outranks authentication — app.py:25,37-52
- §3.1 — revise — ambiguity — `region_code` is two ASCII letters of either case stored verbatim (so its filter is case-sensitive); `annual_miles_millions` echoed in the client's numeric form; duplicate check runs after shape; fresh terminal reports rate `0.0` / `STANDARD` — routes/core.py:36,47-56, serializers.py:36-37
- §3.1 — insert — ambiguity — `hire_date` is unconstrained against the clock (future date bands `UNDER_12_MONTHS`); employee-code duplicate check runs after `terminal_id` resolves — routes/core.py:190-195, calc.py:217-227
- §3.1 — insert — ambiguity — tenure age anchors `hire_date` at midnight UTC and counts whole days, part-days discarded — calc.py:221-223
- §3.1 — insert — ambiguity — explicit key order for the serialised terminal and driver objects — serializers.py:27-40,45-59
- §3.5 — insert — ambiguity — `CONTINUE` still bumps `version`; `decision_note` is an absolute overwrite (omitted ⇒ null, discarding an earlier note); the decision may be repeated on a non-terminated driver — routes/core.py:263-267
- §3.9 — revise — **mismatch** — `crash_count` reflects the `route_class`/`tenure_band` narrowing (PRD said "every notified crash in the window"); breakdown arrays are emitted in fixed enumeration order with empty values omitted and no per-entry `risk_tier`; subset rates use the terminal's full denominator; query params validated before the path `{id}` resolves; `limit`/`offset` not accepted — routes/core.py:100-171

No role-authorization mismatches: `TERMINAL_READ`, `SAFETY_READ` and every explicit role list in `routes/core.py` match the §4 endpoint table exactly, and `errors.py:ERROR_STATUS` matches the §5 catalogue row-for-row.

### Pass 2 — `routes/crashes.py`, `routes/review.py`, `routes/discipline.py` (13 ambiguity-pins, 4 mismatch-revisions)

Result after pass: 490 lines / 127,330 chars (+5,040).

- §3.2 — insert — ambiguity — `driver_id` is resolved before `terminal_id`, so a notification with two unknown ids reports `ERR_DRIVER_NOT_FOUND` — routes/crashes.py:39-40
- §3.2 — insert — ambiguity — full serialised `Crash` key order (frozen recordability trio with the filing fields; re-derived `evidence_posture` last domain key) — serializers.py:63-90
- §3.3 — insert — ambiguity — a driver statement on an unresolvable crash is `ERR_CRASH_NOT_FOUND` (after body-shape validation), not `ERR_UNAUTHORIZED`; the ownership test only applies to an existing crash — routes/crashes.py:119-128
- §3.3 — revise — **mismatch** — "in practice a crash carries either zero or one" implied a constraint; impl enforces no uniqueness, so a second statement on the same crash is accepted — routes/crashes.py:112-140
- §3.3 — insert — ambiguity — serialised `DriverStatement` key order — serializers.py:93-103
- §3.3 — revise — **mismatch** — evidence duplication test compares only against items still in `REQUESTED`/`PRESERVED`; `PURGED_BEFORE_HOLD` and `RELEASED` items reserve nothing (PRD said "not-yet-purged", which left `RELEASED` unclear) — routes/crashes.py:182
- §3.3 — insert — ambiguity — the `evidence_hash` supplied at preservation overwrites any hash recorded at request time — routes/crashes.py:250
- §3.3 — insert — ambiguity — serialised `EvidenceItem` key order — serializers.py:106-121
- §3.4 — insert — ambiguity — the `REPORTED` crash-state rule for opening a case is real, checked after the duplicate test and before the driver-statement prerequisite, and reports `ERR_CRASH_STATE_INVALID` — routes/review.py:29-38
- §3.4 — insert — ambiguity — ballot casting answers HTTP 201 (a ballot row was created) even though the body is the review case; plus serialised `CommitteeVote` key order — routes/review.py:146, serializers.py:148-162
- §3.4 — revise — **mismatch** — the cited `appeal_evidence_item_id` is a band-7 body reference resolved ahead of the state, exhaustion, segregation and window guards (PRD said "Finally … must resolve"); only the belongs-to-crash/`PRESERVED` test is genuinely last — routes/review.py:222-244
- §3.4 — insert — ambiguity — appeal compensation leaves a `RETRAINING_REQUIRED` driver in that status even though the retraining action is voided — routes/review.py:267-274
- §3.4 — insert — ambiguity — serialised `ReviewCase` key order (tally fields between `committee_score` and `next_vote_sequence`) — serializers.py:124-145
- §3.5 — revise — **mismatch** — discipline guard order corrected: `ERR_DRIVER_STATE_INVALID` (terminated driver) outranks the suspension-window test, which in turn outranks `ERR_DRIVER_CRASH_MISMATCH` and `ERR_CRASH_NOT_PREVENTABLE`; PRD prose had listed the pairing/preventability tests first — routes/discipline.py:62-85
- §3.5 — insert — ambiguity — an equal or inverted suspension pair is `ERR_INVALID_REQUEST` in the conditional-shape band, before body references resolve — routes/discipline.py:59-61
- §3.5 — insert — ambiguity — `override_reason` is accepted on any action type under any posture and `override_flag` merely mirrors its presence — routes/discipline.py:91,109
- §3.5 — insert — ambiguity — only an `ACTIVE` driver's status moves on issuance; retraining/suspension on a driver already `RETRAINING_REQUIRED` or `SUSPENDED_PENDING_ACTION` leaves status and both headcounts alone — routes/discipline.py:113-116
- §3.5 — insert — ambiguity — on retraining completion, when the driver is not returned to `ACTIVE` no driver field changes and his `version` does not move — routes/discipline.py:159-163
- §3.5 — insert — ambiguity — serialised `DisciplinaryAction` key order — serializers.py:250-267

### Pass 3 — `routes/claims.py`, `routes/demands.py`, `routes/subrogation.py` (17 ambiguity-pins, 4 mismatch-revisions)

Result after pass: 490 lines / 134,200 chars (+6,870). All 21 changes sit inside §3.6–§3.9.

- §3.6 — insert — ambiguity — `claimant_notice_date` carries no bound at all (not compared to the clock or to `occurred_at`), unlike `demand_received_at` — routes/claims.py:80
- §3.6 — insert — ambiguity — `revision_note` is shape-validated but persisted nowhere and in no response — routes/claims.py:157
- §3.6 — insert — ambiguity — counsel assignment is repeatable while `counsel_required` holds, and is an absolute overwrite that re-stamps `counsel_assigned_at` and bumps `version` — routes/claims.py:194
- §3.6 — insert — ambiguity — every claim write (revision, counsel, closure) answers 200 with the updated claim — routes/claims.py:176,200,230
- §3.6 — insert — ambiguity — `counsel_required` list filter matches the re-derived value; full claim key order pinned (30 keys, `layer_allocations` before the derived totals) — routes/claims.py:141, serializers.py:165
- §3.7 — insert — ambiguity — a year with no layers is malformed; the write-time test includes the new layer and a refused layer is not persisted, so towers build upward index by index; duplicate index outranks the structural test — calc.py:450, routes/claims.py:36
- §3.7 — insert — ambiguity — policy-layer key order, `created_at`-terminal with no version — serializers.py:199
- §3.7 — revise — **mismatch** — PRD said the claim reacts "on both branches"; impl has a third: a demand on a `SETTLEMENT_COMPLETE` claim leaves the handling status there (only `SETUP → NEGOTIATION` is declared) while still bumping `version` — routes/demands.py:53
- §3.7 — insert — ambiguity — demand key order (incl. derived `round_count` slot, internal per-demand allocation record excluded) and negotiation-round key order — serializers.py:212,234
- §3.7 — insert — ambiguity — offers return the new round at 201, counters return the standing round at 200 (not the demand) — routes/demands.py:130,164
- §3.8 — insert — ambiguity — `layer_allocations` is kept ascending by `layer_index` regardless of settlement arrival order — routes/demands.py:233
- §3.8 — insert — ambiguity — settlement's response is the updated demand; claim/subrogation effects need re-reads — routes/demands.py:251
- §3.8 — revise — **mismatch** — completion branch also self-loops on `SETTLEMENT_COMPLETE` when the claim was already there — routes/demands.py:240
- §3.8 — insert — ambiguity — `rescission_reason` is required but stored nowhere; only `rescission_count` witnesses it — routes/demands.py:257
- §3.8 — revise — **mismatch**/ambiguity — a zeroed allocation entry is removed from the array outright, and the `SETTLEMENT_COMPLETE → NEGOTIATION` move is conditional (a claim already in `NEGOTIATION` is left as is) — routes/demands.py:295
- §3.8 — insert — ambiguity — rescission's response is the updated demand — routes/demands.py:312
- §3.9 — insert — ambiguity — a subrogation demand may be opened on a `SETTLEMENT_COMPLETE` or `CLOSED` claim and then stays `DRAFT` forever; opening one does not write the parent claim or move its `version` — routes/subrogation.py:25
- §3.9 — insert — ambiguity — a zero/negative `recovered_amount_cents` reports `ERR_RECOVERY_EXCEEDS_BASE`, not `ERR_INVALID_REQUEST`, and only after the state guard — routes/subrogation.py:92
- §3.9 — insert — ambiguity — `RECOVERED` advances the claim's `version`; `DENIED`/`WRITTEN_OFF` write nothing on the claim; response is the subrogation demand — routes/subrogation.py:102
- §3.9 — insert — ambiguity — subrogation read surface and key order — serializers.py:270
- §3.9 — revise — **mismatch** — closure guards run already-closed first, then open demands, then open subrogation (PRD's narrative had put the already-closed guard last) — routes/claims.py:208

§5 cross-check by pass 3: every error id its partition raises matches `errors.py` exactly (including `ERR_CLAIM_VERSION_STALE` 412, `ERR_COVERAGE_EXHAUSTED` 422, `ERR_RESERVE_INSUFFICIENT` 422). No §5 edits were needed by any pass.

### Orchestrator final verification

- `PRD.md` and `PRD_FINALIZED.md` md5 `cab6ce68d0fac83c19201e9ce5cff0be` (legitimately identical — Step 7 made zero `implementation/` fixes); `PRD_COMPLETED.md` md5 `9dc0a41fd5eca56c6258b1b58c91bc90`, i.e. NOT identical to its source, so the Step 9 scan demonstrably ran.
- `PRD_COMPLETED.md` structure intact: 490 lines, all five `## ` headings, §5 still carries all 63 `ERR_` rows, file ends at `| \`ERR_RESERVE_INSUFFICIENT\` | 422 |`.
- Final 8-round sweep evidence re-parsed after Step 9: `workspace/implementation/results.{1..8}.json` all report `194 / 194`.
- `__pycache__` directories removed from the task tree. Test artifacts sit at the task root (`test_helpers/`, `test_suite/`); nothing stray was written under `workspace/` and `worklog.md` exists only at the task root.

Pipeline complete through Step 9.
