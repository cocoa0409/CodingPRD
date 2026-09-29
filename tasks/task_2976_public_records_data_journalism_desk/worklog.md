# Worklog — task_2976_public_records_data_journalism_desk

## Step 1: Create task directory — 2026-09-06T00:16:11.364Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2976_public_records_data_journalism_desk` and `.../workspace` (pre-assigned path from the orchestration prompt; no index auto-allocation performed, since up to 32 pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-06T01:53:00.000Z

All three scaffold files for task 2976 are complete, lint-clean, and parse cleanly.

## Deliverables

| File | Lines | Bytes | `yaml.safe_load` |
|---|---|---|---|
| `SCAFFOLD.yaml` | 3471 | 191,266 | parse OK |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2067 | 151,979 | parse OK |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3923 | 285,627 | parse OK |

`SCAFFOLD.yaml` top-level keys are `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — neither `scaffold_difficulty_design` nor `scaffold_corner_design` appears in it. The other two files each have exactly one top-level key. `tail -30` on all three ends on a complete list item (RBAC `shared_operations` entry / final `assert:` line respectively); nothing is truncated.

## Lint

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared: 63   §1.1 entities declared: 14
  §1.8 instances scanned: 20    §1.9 instances scanned: 43
  Calls scanned (§1.8+§1.9): 1092
```

Independent self-checks also pass: instance names are unique across the union of both design files (0 duplicates), every instance has exactly one of `test_recipe` / `excluded_because`, and all 18 `excluded_because.difficulty_instance` citations resolve to real §1.8 instance names.

## Domain surface (§1.0–§1.7)

`api_prefix: /records-desk`, `difficulty_level: expert_plus`, archetypes compliance_audit + multi_party_negotiation, topology `graph`, SM shape `cyclic`, `role_model: segregation_of_duties`, `consistency_model: immediate`, layers `cascading_side_effects, dual_variant_calculation, optimistic_concurrency, scheduled_actions, derived_field_reconciliation`.

**14 entities** (Desk, Agency, RecordsRequest, Appeal, Dataset, FieldDefinition, Investigation, AnalysisRun, Finding, ExpertReviewer, ReviewAssignment, SubjectResponseRequest, SecureEnclave, EnclaveSession), **9 state machines**, **2 OCC rules**, **11 calculations**, **38 ordered validations** (priority ladder 10→270), **63 endpoints**, **57 errors**, **6 roles**.

## §1.8 difficulty design

20 instances = all nine Difficulty Rules × 2+, e.g. dual-variant deadline (strict vs tolled) and disclosure risk (AGGREGATE_MAX vs COMPOSITE_WEIGHTED); an 8-step pinned-order fee-waiver cap; round-each-share-then-residual cost allocation; a bounded 3-round clarification cycle; a five-hop appeal-denial litigation cascade; a three-hop quarantine invalidation; three priority-conflict pairs (100>270, 150>200, 140>170); exact-millisecond appeal ripeness, the 72-hour notice boundary, empty-allocable-set and zero-share edges, half-open enclave spans with the sanitization buffer, and closed-window reviewer capacity at the touching endpoint.

## §1.9 corner design

43 full recipes + 18 `excluded_because` stubs across all nine allowed sections: entities 14, state_machines 11 (+6 stubs), calculations 6 (+6), validations 5, endpoints 2 (+2), errors 1, rbac 2, cross-cutting complexity layers 1 (+4), consistency model 1. Coverage highlights: every entity's creation/retrieval/listing/404/required/defaults/computed/system/type/immutability/parent claims plus the three graph features (self-referential supersede, the reviewer×finding junction, the Investigation↔Dataset cycle); a single error-envelope instance driving 401/403/404/400/409/412/402/422 with eight pairwise-distinct codes; identity-bound SoD on peer-review and expert verdict; wrong-role 403s against unresolvable UUIDs proving priority 30 precedes 40 while both shared operations still succeed under both roles; both OCC rules in one fixture with distinct stale-version codes; and an `immediate`-consistency instance where readiness and the lock-findings→NOTICE_ELIGIBLE cascade are visible in the causing request. All 57 catalogue errors are now referenced by at least one design instance.

**Orchestrator note (post-subagent):** the subagent flagged that `SCAFFOLD.yaml` line 2 carried the literal difficulty directive `Generate task harder than expert level!` inside the verbatim `scenario:` block — the known leak path scenario → PRD.md. The orchestrator stripped that line (and the following blank line) from `SCAFFOLD.yaml` before Step 3; the file now starts the scenario block at `2976. Public Records & Data Journalism Desk ...` and re-parses clean with `yaml.safe_load` (3469 lines after the strip). The directive remains withheld from the doc, test, and implementation generators.

## Step 3: Copy shared files — 2026-09-06T01:55:26.432Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `tasks/task_2976_public_records_data_journalism_desk/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-06T02:10:00.000Z

PRD generation for task 2976 is complete.

**Output:** `workspace/PRD.md`
**Size:** 511 lines / 107,329 characters (built via one `Write` plus 10 incremental `cat >>` appends, growth confirmed after each)
**End boundary:** ends at the completed §5 table — 57 of 57 error rows present, last row is the 57th scaffold error. Verbatim last line:

`| \`ERR_FIELD_LIMIT_EXCEEDED\` | 422 |`

**Structure:** §1 Introduction → §2 Global Specifications (2.1 RBAC, 2.2 verbatim response envelope, 2.3 Pagination, 2.4 Identity/versioning, 2.5 Nested paths, 2.6 Logical clock & statutory day arithmetic, 2.7 Fee-budget ledger, 2.8 OCC, 2.9 Security posture, 2.10 Money/rounding, 2.11 Rejection precedence with all 38 rungs numbered in ascending priority) → §3 Business Logic (3.1–3.9) → §4 Endpoint table (4 columns) → §5 Error table (2 columns). No audit footer.

**Coverage (found / expected), machine-verified:**
- Endpoint (method, path) pairs in §4: **63 / 63**, zero missing, zero extra (exact string diff against `SCAFFOLD.yaml`)
- Error IDs: **57 / 57** in §5 with all HTTP statuses matching the scaffold exactly; also **57 / 57** mentioned narratively in §1–§4
- Entities: **14 / 14** named
- Entity field names (backticked, word-boundary matched): **146 / 146**
- Endpoint input identifiers: **102 / 102** (plus `limit`/`offset`, specified in §2.3)
- Calculations: **11 / 11** (statutory_deadline, fee_waiver_and_net_fee, desk_fee_budget_ledger, desk_security_posture, dataset_retention_expiry, analysis_cost_allocation, investigation_analysis_readiness, reviewer_capacity_window, enclave_occupancy_span, disclosure_risk_score, subject_notice_sufficiency)
- Validations: **38 / 38** rungs, in scaffold priority order, each paired with its error ID
- State machines: 9 machines / 54 transitions; every state string present
- Enum values and known-issue/reason/suppression code sets: all present

**Hard Contract reports:** Field coverage PASS (146/146 entity fields, 102/102 request-body inputs, 4/4 query params). Rule coverage PASS (38/38 validations, 2/2 OCC rejections, 54/54 transitions, 11/11 calculations, 41/41 side-effects, 146/146 field contents, 14/14 sibling-branch symmetry groups). Path purity PASS (997 backtick tokens scanned in §3, 0 paths / 0 bare methods / 0 method+path tokens).

Two notes from the subagent: (1) it initially drafted a `POST /records-desk/appeals/{id}/withdrawal` row in §4; the scaffold has no such endpoint (appeal withdrawal exists only as a cascade hop off records-request withdrawal), so the row was removed and §4 now matches the scaffold exactly. (2) The forbidden design files were never opened, grepped, or referenced; all worked examples come from `SCAFFOLD.yaml`'s own `calculations[].*_example` and state-machine cascade text.

**Orchestrator truncation check (mandated):** independently ran `wc -l -c` (511 / 107,329 — matches) and `tail -25`. The file ends on `| \`ERR_FIELD_LIMIT_EXCEEDED\` | 422 |`, the final row of the complete 57-row §5 error table, i.e. a real section boundary, not mid-sentence. Also grepped PRD.md for `harder than expert`, `expert level`, `scaffold`, `SCAFFOLD_DIFFICULTY`, `test_recipe` — zero hits, so the Step 2 difficulty directive did not leak into the PRD. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-06T03:20:00.000Z

Step 5 is complete. Both deliverables are at the task root, not under `workspace/`.

## Deliverables

`test_helpers/` (9 files, 3,285 lines): `__init__.py` 14, `api_client.py` 562, `api_errors.py` 162, `assertions.py` 352, `constants.py` 339, `factories.py` 569, `fixtures.py` 826, `test_users.py` 141, `types.py` 320.

`test_suite/` (13 files, 10,859 lines): `conftest.py` 29, then `test_01_desk_and_agency_registry.py` 961 / 24 tests, `test_02_records_request_drafting_and_submission.py` 1701 / 42, `test_03_statutory_deadlines_and_tolling.py` 862 / 19, `test_04_fee_determination_and_waiver.py` 493 / 11, `test_05_appeals_and_litigation_cascade.py` 764 / 16, `test_06_budget_ledger_conservation.py` 387 / 7, `test_07_dataset_lifecycle.py` 1270 / 27, `test_08_analysis_runs_and_cost_allocation.py` 775 / 20, `test_09_findings_and_expert_review.py` 1226 / 23, `test_10_secure_enclave_occupancy.py` 611 / 12, `test_11_disclosure_risk_variants.py` 727 / 15, `test_12_publication_gate_ladder.py` 1053 / 21.

**Total: 237 tests.**

## Coverage

- Queue A (§1.8 difficulty): **20/20 instances translated, 0 skipped** — 76 tests, 3-7 per instance.
- Queue B (§1.9 corner): **43/43 non-stub instances translated, 0 skipped** — 161 tests, 3-5 per instance. The 18 stub instances point at difficulty instances already covered, so no placeholders were needed.
- No instance was skipped. A handful of individual *assertions* were dropped as not uniquely derivable (see below).

## Verification (all run by the subagent over the final files)

- `python3 -m py_compile test_helpers/*.py test_suite/*.py` → **COMPILE_OK**.
- `pytest --collect-only` → **237 tests collected, 0 errors**, matching the AST count exactly.
- Design tags: every one of the 237 docstrings carries **exactly one** `Design:` line, it is the **last** line of the docstring, and every tag byte-matches an instance name from the two design indices. **63/63 tags covered, 0 unknown, 0 duplicate assignments**.
- No `pytest.mark.skip` / `xfail` / `pytest.skip(` / bare `pass`, no mention of "scaffold", no `subprocess` / `Popen` / `os.system` / `pkill` / file writes anywhere in the suite. No server was ever started, probed, or killed.
- Zero inline `ERR_*` string literals — all error ids come from `api_errors`. Every uppercase enum literal exists in the PRD or the helpers, with one deliberate exception (`"WEEKDAYS"`, an invalid-`deadline_basis` rejection probe).
- Static symbol check: every `C.*` / `F.*` / `X.*` / `api.*` attribute referenced exists, and every call **binds against the real signature** (0 arity/keyword mismatches).
- `__pycache__`, `.pytest_cache` removed; `.scratch/step5` removed (`.scratch/step2` left intact); `worklog.md` untouched; nothing read or written under `workspace/` except `PRD.md`.

## Design-literal corrections applied (PRD wins)

Invalid `expertise_code`s (`CORRECTIONS`, `PAYROLL`, `TRANSIT`) → valid enum members; `blocking_reason_code == null` → `"NONE"`; unresolvable-id probes use `00000000-0000-4000-8000-000000000000`; `SecureEnclave.booked_session_count` asserts replaced with observable consequences since PRD §4 declares no enclave GET; all dataset slugs minted uniquely; a fresh dataset's `record_count` asserted as `0`, not null (PRD §3.6).

## One thing worth escalating to Step 8/9

The PRD contradicts itself on cleaning-lock gate ordering: §2.11 numbers documentation (rung 34) before format (rung 35) and calls itself "the complete ladder, in evaluation order", while §3.6 says the two gates are "evaluated in that order" with format first. The both-gates-violated precedence assertion was therefore dropped (the two single-gate refusals and the success path are still covered). Also dropped as unpinned by the PRD: `waiver_pct` on non-waiver branches, and `labor_cost_cents` / `total_cost_cents` at run-creation time.

## Step 6: Generate implementation — 2026-09-06T03:20:00.000Z

Implementation is complete and verified.

## Deliverable
`workspace/implementation/` — Python 3 + Flask 3.0.3, 27 source files, **3252 lines** total.

| Module | Lines | | Module | Lines |
|---|---|---|---|---|
| `app.py` | 80 | | `routes/records_requests.py` | 290 |
| `clock.py` | 102 | | `routes/datasets.py` | 248 |
| `db.py` | 235 | | `routes/investigations.py` | 187 |
| `errors.py` | 89 | | `routes/reviewers.py` | 181 |
| `middleware.py` | 49 | | `routes/analysis_runs.py` | 153 |
| `response.py` | 62 | | `routes/enclaves.py` | 145 |
| `validation.py` | 244 | | `routes/appeals.py` | 130 |
| `services/calculations.py` | 177 | | `routes/subjects.py` | 118 |
| `services/cascades.py` | 149 | | `routes/desks.py` | 111 |
| `services/publication.py` | 119 | | `routes/findings.py` | 103 |
| `services/daycalc.py` | 89 | | `routes/clock_routes.py` | 21 |
| `services/ledger.py` | 74 | | `routes/__init__.py` | 0 |
| `services/investigation.py` | 46 | | `services/__init__.py` | 0 |
| `services/money.py` | 38 | | `start.sh` / `requirements.txt` | 11 / 1 |

## Required verification results
- **Endpoints: 63/63.** Machine-diffed the Flask `url_map` against the PRD §4 table (method + normalized path): zero missing, zero extra, **PERFECT MATCH**.
- **Error codes: 57/57.** Machine-diffed `errors.ERROR_STATUS` against the PRD §5 catalogue: same 57 ids, and **every HTTP status matches**.
- **`py_compile`: PASS** on all 25 `.py` files. `ls -la` confirms both `__init__.py` files are intentionally 0 bytes and no other file is short.
- **Cold-boot smoke check: PASS.** Four separate cold boots on random high ports (25442, 26888, 25952, 27341) via `start.sh`; each served requests and was killed by its exact recorded PID (`KILLED_CLEAN` every time, no broad `pkill`). Zero tracebacks in any server log. No non-source file exists in the impl dir, confirming no on-disk state.

## Behavioural verification beyond the minimum
Validated against the scaffold's own worked examples (the runner has no `-k` selector):
- **Fee waiver, all 5 cases live over HTTP:** A (cap binds, net 5250), B (small-balance full waive, net 0), C (no waiver, 15250), D (0.95 ceiling, net 16000), E1/E2/E3 half-up precision (8688 / 5213 / 1738). **All PASS.**
- **Cost allocation, examples 1–4:** negative residual `[11571, 11572, 11607]`, zero-record edge `[11500, 0]`, QUARANTINED filtering `[17375, 17375]`, empty set → `ERR_NO_ALLOCABLE_INPUTS` 422 with nothing written. **All PASS.**
- **Disclosure risk divergence example:** AGGREGATE_MAX 80 vs COMPOSITE_WEIGHTED 69, `any_source` false, and all three variant selections correct. **PASS.**
- **Enclave half-open buffered exclusion** (4 boundary cases incl. the 11:29/11:30 pair and the CLOSED-session release) and **reviewer closed-interval aggregate capacity** (the 09-05 endpoint touch vs 09-05T00:00:00.001Z). **All PASS.**
- **RBAC: 63 endpoints × 6 roles = 378 probes, zero mismatches** against the PRD roles column, plus correct `ERR_UNAUTHENTICATED` for missing headers, empty `X-User-ID`, and an unrecognised role.
- **Full end-to-end path to publication: 0 failures** — desk → agency → request → submit → fee-determination (ledger conserved) → agency-decision → dataset → delivery (`retention_expires_at` 2029-08-19T23:59:59.000Z) → 2 field definitions → `documentation_status` COMPLETE → cleaning-lock → analysis-run (labor 22750 / total 34750) → peer-review → cost-allocation → finding → document-match → reviewer → assignment → verdict → readiness READY → lock-findings (subject flips to NOTICE_ELIGIBLE) → notice attempts → publication PUBLISHED with risk 30 / COMPOSITE_WEIGHTED. Negative gates fired at the correct rung and status: SoD 403, verdict ownership 403, `ERR_SUBJECT_NOTICE_PENDING` 409, `ERR_INSUFFICIENT_NOTICE` 422, `ERR_INSUFFICIENT_ATTEMPTS` 422.

## Adjudications worth flagging to Step 7
1. **`search_hours` / `labor_hours` are `type: number`** in SCAFFOLD.yaml, so a JSON *string* `"3.5"` is correctly rejected with `ERR_INVALID_REQUEST`. If iteration 1 shows a mass fixture failure naming these fields, it is the known factories-send-money-as-strings test bug, not an impl bug.
2. **Cleaning-lock gate order: documentation (250) before format (260)**, per §2.11 and the priority table — contradicts §3.6's prose ("format AGREED then documentation COMPLETE, in that order"); the table wins. (Independently flagged by Step 5 — same contradiction, and both agents resolved it the same way.)
3. **Session-closure `documents_returned_count` mismatch is a rung-5 schema violation** (`ERR_INVALID_REQUEST`), so it precedes `ERR_INVALID_SESSION_STATE`.
4. **`matched_page` has no declared range anywhere**, so it is type-checked only (no invented bound).
5. **`POST /review-assignments` has no finding-state gate** and **repeat `cost-allocation` on an ALLOCATED run is permitted** (recomputes) — both because their declared error lists omit the corresponding codes.
6. The publication notice/attempt gates are applied literally to every non-DRAFT subject record (only `UNREACHABLE` is exempt from the 72-hour check), so a `RESPONDED` record still needs 72 elapsed hours.

Constraint compliance: never read, listed, grepped or wrote `test_suite/`, `test_helpers/`, or the two design YAMLs; no `worklog.md` touch; scratch confined to `.scratch/step6/`, removed at the end.

**Orchestrator verification:** `test_helpers/` (9 files) and `test_suite/` (13 files) are at the task root, not under `workspace/`; no stray copies exist under `workspace/`. `workspace/implementation/` contains `start.sh`, `requirements.txt`, 9 top-level modules plus `routes/` and `services/`, and no on-disk state files. Steps 5 and 6 were launched in a single assistant message so the impl generator was physically unable to read `test_suite/`.

## Step 7: Run tests and iterate — 2026-09-06T03:35:00.000Z

The sweep came back fully green on the first iteration — no diagnosis or fixes were needed.

## Summary

**Iterations run:** 1 (single 8-round sweep; zero failures, so no fix/rerun cycle was required).

**Tests deleted:** none. No test failed in any round, so no test reached STEP 1 of the diagnostic protocol.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:** none.

**Fixes applied to `implementation/`:** none.

**Final sweep evidence** (`workspace/implementation/results.$i.json`, all written 03:27 after the `SWEEP_DONE` sentinel appeared):

| round | passed / total | failed | errors | skipped | duration |
|---|---|---|---|---|---|
| 1 | 237 / 237 | 0 | 0 | 0 | 422.9 s |
| 2 | 237 / 237 | 0 | 0 | 0 | 424.8 s |
| 3 | 237 / 237 | 0 | 0 | 0 | 423.0 s |
| 4 | 237 / 237 | 0 | 0 | 0 | 424.8 s |
| 5 | 237 / 237 | 0 | 0 | 0 | 424.8 s |
| 6 | 237 / 237 | 0 | 0 | 0 | 423.0 s |
| 7 | 237 / 237 | 0 | 0 | 0 | 423.0 s |
| 8 | 237 / 237 | 0 | 0 | 0 | 424.8 s |

**Integrity checks performed** (because a clean first sweep is the shape a false-negative parser produces):
- Parsed on the `"status"` key per test, not `"outcome"`. Cross-check holds: union of non-`passed` tests = 0 = `total - passed` for every round.
- Per-test status histogram is `{'passed': 237}` in all 8 rounds — no statuses hidden behind an unexpected label.
- `skipped == 0` in all rounds, and `grep` over `test_suite/` finds no `pytest.mark.skip`/`xfail` markers. The single `skip` textual hit is the test *name* `test_a_cleaning_dataset_is_skipped_entirely_rather_than_zeroed`, a cost-allocation filtering assertion, not a marker.
- Collected count matches the source of truth: 237 `def test_` functions across the 13 files equals the 237 reported `total`, so nothing failed at collection and silently dropped out.
- Results are genuinely from this run: `sweep.sh` does `rm -f results.*.json` before launching, and all 8 files are timestamped after the launch.
- The sweep ran under `setsid` as mandated, polling for `SWEEP_DONE` rather than treating the launcher's early return as completion. No round showed the `Terminated`/simultaneous-death signature of SIGTERM reaping, and there were no timeout- or connection-class failures despite the contended host.

**Note on the known PRD self-contradiction:** the cleaning-lock gate ordering (§2.11 rungs 34/35 putting documentation before format, versus §3.6's prose putting format before documentation) never came into play — no test turns on which gate fires when both are violated, so the implementation's choice to follow the §2.11 table stands unchallenged and no change was made there.

**Orchestrator independent verification (mandated — a claimed-clean sweep with no artifacts is a known failure mode):** re-listed and re-parsed the artifacts myself. All 8 `results.$i.json` exist (79,116–79,131 bytes, mtime 03:27) alongside `workspace/SWEEP_DONE`. Independent parse: every round reports `passed=237 total=237`, carries exactly 237 per-test records, and its status histogram is `{'passed': 237}` — no hidden label. Source-of-truth cross-check: 237 `def test_` functions across `test_suite/*.py`, matching `total`. `grep` for `mark.skip|mark.xfail|pytest.skip(` across both `test_suite/` and `test_helpers/`: 0 hits. The green sweep is real.

## Step 8: Finalize PRD — SKIPPED — 2026-09-06T03:36:00.000Z

Skipped per the skill's explicit skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. With an empty `<step_7_diff>` there is no fix site to patch, so no subagent was spawned and no `PRD_FINALIZED.md` is produced. Step 9 therefore starts from `workspace/PRD.md`, per the skill's input rule ("Start from `workspace/PRD_FINALIZED.md` if Step 8 produced it; otherwise from `workspace/PRD.md`").

Note this does NOT mean the PRD is complete: Step 7's silence only proves the 237-test suite never asserted a behavior the PRD failed to pin. Every PRD silence the impl resolved at generation time without producing a test failure is still open, which is exactly what Step 9's full impl scan exists to close. Step 9 is run as three sequential, impl-module-partitioned passes over one shared `PRD_COMPLETED.md` plus a fourth reconciliation pass, because a single pass over a 27-module / 63-endpoint implementation reliably under-scans (and a byte-identical `PRD_COMPLETED.md` would mean the scan never ran).

## Step 9: Complete PRD — 2026-09-06T04:10:00.000Z

Run as four sequential passes over one shared `workspace/PRD_COMPLETED.md`: three impl-module-partitioned scan passes plus a reconciliation pass. Pass 1 did the `cp PRD.md PRD_COMPLETED.md`; passes 2–4 were explicitly forbidden from re-copying (a re-cp would silently destroy prior passes). Each pass was given the prior passes' out-of-partition observations verbatim as a handoff list, with instructions to verify each item against source rather than trusting the sibling agent's summary.

### Growth trace (proves each pass actually ran)

| stage | lines | chars |
|---|---|---|
| `PRD.md` baseline | 511 | 107,329 |
| after pass 1 (infra + requests + appeals + ledger) | 512 | 112,069 |
| after pass 2 (datasets + runs + enclaves + cascades) | 512 | 117,032 |
| after pass 3 (findings + reviewers + subjects + publication) | 512 | 128,182 |
| after pass 4 (reconciliation) | 512 | **130,328** |

Total **+23,999 chars / +22.4%** over `PRD.md`, 109 diff lines, all as in-paragraph inserts/revisions (+1 line total, one new §2.2 bullet; zero new sections — heading count 28 before and after).

### Pass 1 — 13 ambiguity-pins, 4 mismatch-revisions
Modules: `app.py`, `middleware.py`, `response.py`, `errors.py`, `db.py`, `clock.py`, `validation.py`, `routes/{clock_routes,desks,records_requests,appeals}.py`, `services/{daycalc,ledger,money}.py`.
Pins: `api_request_id` shape (`req_` + 20 chars of `A–Z0–9`); unknown path → `ERR_INVALID_REQUEST` at **404** and disallowed method at **405** (not §5's 400), firing ahead of rung 1 with no auth headers, trailing-slash variants resolving to the declared path; `offset` unbounded / `?limit=` empty treated as omitted / whitespace and `+` accepted / undeclared query params ignored; `created_at` ties broken by insertion sequence; `id` is a random **v4** UUID in canonical lowercase form; instant-parsing leniency and the fact that rendered timestamps **truncate** rather than round to 3 digits, clock endpoint's `data` has the single key `current_utc`; rung-5 free-text fields are required strings with no min/max and no non-blank rule (verified at all 12 `field_text` callsites); fresh `DRAFT` request carries all 15 later-workflow fields present-and-null; a live supersede target on a *different desk* also yields `ERR_SUPERSEDE_TARGET_NOT_ACTIVE`; superseded target `version` +1 and desk `version` +1 exactly once with `open_request_count` netting unchanged; `search_hours`/`billed_page_count` schema is any finite number ≥ 0 with no enforced scale or upper bound; `waiver_pct` stays **null** (not 0) when no waiver was requested; appeal created with `decision_rationale` present-and-null.
Mismatches fixed: §2.7's Release-trigger list was missing the supersede-driven withdrawal; §3.4's conserved-identity worked example was **unreachable** (it settled 4500 on a *denied* appeal then withdrew the request, but a denied appeal drives the request to terminal `LITIGATION_AUTHORIZED`, which `WITHDRAWABLE_STATUSES` excludes — its arithmetic 495500/0/4500 is exactly the *granted* path, so it was rewritten to grant with the denied variant noted as `ERR_INVALID_REQUEST_STATE`); §3.6's cleaning-lock ordering sentence was backwards; §4's source-exposure row wrongly claimed the lockdown cascade fires only on `CRITICAL` (it fires at every severity; severity is audit metadata).
Verified-correct-without-edit: the §3.2 tolling worked example, all four §3.3 fee cases, §5's 57 rows vs `errors.ERROR_STATUS` in membership/status/order, §4's role column vs `authenticate()` for all 21 in-partition endpoints, and §4's budget-adjustment wording vs the impl's `available + delta < 0` guard.

### Pass 2 — ~16 ambiguity-pins, 6 mismatch-revisions
Modules: `routes/{datasets,analysis_runs,enclaves}.py`, `services/cascades.py`, dataset/run-side `services/calculations.py`.
Pins: explicit `null` `investigation_id` == omitted; the desk-linkage check (rung 31) precedes rung-36 slug uniqueness; `delivered_format`/`quarantine_reason_code`/`retention_expires_at` present-and-null on creation; `record_count` integer ≥ 0 unbounded; suppression returns the `FieldDefinition` (not the dataset) and does not version the dataset, and re-suppressing overwrites `suppression_method`; quarantine hop two leaves a run that is neither `APPROVED` nor `ALLOCATED` untouched including `version`, and a downgrade preserves `review_cycle_count`/`peer_review_note`/`reviewed_by_user_id`; requalification is **not** a cascade (only the dataset versions; `allocated_cost_cents` stays 0 and `retention_expires_at` is not re-stamped); peer review consults no investigation state; cost allocation has no gate on the run's own `cost_allocation_status`; explicit `null` `sanitization_buffer_minutes` == omitted (30); session bounds are never compared to the logical clock (past bookings legal) and the gating posture is the desk resolved dataset → records request → desk; `documents_returned_count` equality is a rung-5 check ahead of the state gate; both cancellation cascades walk sessions system-wide by `created_at` then insertion sequence.
Mismatches fixed: "each affected run's version" → the runs hop two actually rewrote, plus the investigation is versioned by **every** quarantine even when nothing changed; "a later run leaves the investigation in `ANALYSIS`" → in whatever status it occupies (`FINDINGS_LOCKED`/`CLEARED` are not reverted), and `labor_cost_cents`/`total_cost_cents` are stamped at creation; every dataset in the allocable set is rewritten and versioned even when its share is unchanged; the readiness recompute list was missing finding assertion; §4's cleaning-lock row reordered to documentation-then-format; §4's quarantine row "its analysis run" → every analysis run of that investigation.
Verified-already-correct: `compute_cost_allocation`'s residual applied before any write, `allocable` ordered by `(created_at, name)`, and all three worked cases re-checked arithmetically.

### Pass 3 — 19 ambiguity-pins, 4 mismatch-revisions
Modules: `routes/{investigations,findings,reviewers,subjects}.py`, `services/{publication,investigation}.py`, risk/capacity/notice `services/calculations.py`.
Pins: finding assertion stores three fields present-and-null and has **no** investigation-status gate (unlike run creation), so assertion/document-match/verdict can drop a `FINDINGS_LOCKED` investigation to `NOT_READY` while leaving it locked; `matched_page` is a plain integer with no range (zero and negatives accepted); reviewer registration's element-level non-empty rule, left-to-right agency resolution, and verbatim unsorted un-deduplicated storage; assignment creation gates neither the finding's `verification_status` nor investigation status — `DOC_MATCHED` bites only at verdict; capacity is a window-overlap count over `ASSIGNED` rows only, so `active_assignment_count` may legitimately exceed `max_concurrent_assignments`; revocation hop one leaves `source_document_ref` in place, hop two releases both `ASSIGNED` and `COMPLETED` assignments but decrements/versions the reviewer only for `ASSIGNED` ones, hop three reverts only `FINDINGS_LOCKED`; lock-findings validates no body and checks status before readiness (rung 10 before 33); subject creation has no status gate and lock-findings is the only promoter out of `DRAFT`; `contact_detail` is 1–300 chars with no non-blank rule; the notice clock starts on `NOTICE_ELIGIBLE`, not the attempt counter; an attempt from `NO_RESPONSE` is a pure self-loop that can never reach `UNREACHABLE`; legal clearance checks status before lockdown (rung 10 before 13); the lapse pre-step runs only after the status check, versions each lapsed record, and its writes stand even when a later gate refuses; **the publication ladder never reads `analysis_readiness`**; the dataset-linkage check is rung 31, the last rung, despite being named early in the prose; `UNREACHABLE` is the only notice-gate exemption (`RESPONDED`/`NO_RESPONSE` are held to the full 72 h and two-attempt minimum); `COMPOSITE_WEIGHTED` scores 0 on an empty unsuppressed set.
Mismatches fixed: verdicts "diverge symmetrically" → not quite (only `CONFIRMED` stores `sme_verdict_rationale`); §4's `/review-assignments` row wrongly implied a document-matched gate; §4's revocation row "cancelling any open expert review" → releasing every `ASSIGNED`-or-`COMPLETED` assignment; the rehearsal paragraph (empty `?release_dataset_id=` == absent, unchecked stamped fallback, `notice_window_hours` floor semantics incl. negatives under a rewound clock, and three consequences of rehearsing the *gate ladder only* — notably that the preview omits the rung-10 status check, so the pre-existing claim that `NONE` means publication would succeed was a genuine mismatch, and `ERR_RELEASE_DATASET_REQUIRED` can never surface as a blocking code).

### Pass 4 — reconciliation: 4 open cross-pass items closed, 1 real contradiction fixed
- **Rung 31 completed**: added the third clause (dataset-create investigation must sit on the same desk as the named records request, `datasets.py:55-57`, between rung-6 resolution and rung-36 slug uniqueness).
- **Rung 5 explicit-`null` rule generalised** after sweeping every optional field in the system (10 sites, no `payload.get()` bypasses): all accept null, with the per-type outcome stated (string/enum/reference → null, integer → the declared default, array → `[]`). Caveat scoped rather than over-claimed: `field_int` returns `None` not the default, but both optional-int callsites re-apply the default immediately, so the local pins are correct; and an explicitly-null `denial_reason_code` on a `DENIED` disposition is still refused — by the cross-field rule, not the null rule. All six local pins retained.
- **Body-less POSTs**: programmatically swept all 63 handlers for `v.body()`; exactly three POSTs never touch the body (`records-requests/{id}/submit`, `analysis-runs/{id}/cost-allocation`, `investigations/{id}/lock-findings`). Stated once at rung 5 by name, noting a body sent anyway is ignored entirely even if not well-formed JSON.
- **Quarantine on a `CLEARED` investigation**: §3.6 hop three now states only `FINDINGS_LOCKED` reverts, so a `CLEARED` investigation's readiness drops while its status stands and the §3.9 ladder does not block the release — cross-referenced to the parallel §3.8 revocation pin.
- **Contradiction found and fixed — §2.4 ¶4 vs §3.7.** Pass 1 left §2.4 asserting flatly that "a row that a cascade inspects but does not change is left untouched, including its `version`", while pass 2 inserted into §3.7 that every readiness recompute versions the investigation whether or not the value changed, and that every allocable dataset is versioned even when its share is identical. Adjudicated from source: **pass 2 is right, §2.4 was wrong** — `db.touch()` is unconditional and the discriminator is whether the operation calls it, not whether a value changed. Fixed by softening §2.4 in place (kept the sentence, gave it the two examples that genuinely *are* skipped — `cascades.py:111` `if changed:` and `:139` `if was_assigned:` — then added the discriminator). Pass 2's pins untouched.
- **Spot-checks on the three most sweeping prior-pass claims:** pass 2's "every readiness recompute versions the investigation" **upheld** (all 8 `recompute_readiness` callsites individually verified, each followed by an unconditional `db.touch`); pass 1's §2.4 universal **softened** (true for runs and reviewers in the cascades, false for the investigation on a recompute and for allocable datasets on re-allocation); pass 3's "revocation hop three reverts only `FINDINGS_LOCKED`" **upheld**, and the identical guard in the quarantine cascade is what made item D writable as a strict parallel.

### Orchestrator final verification (independent)
- `wc -l -c`: `PRD.md` 511 / 107,329; `PRD_COMPLETED.md` 512 / 130,328 — grew, never shrank.
- `cmp -s PRD.md PRD_COMPLETED.md` → **differs**. The byte-identical failure mode (scan never ran) did not occur; `diff` shows 109 changed lines.
- Heading count `grep -c '^#'`: 28 in both — no section added or lost.
- `tail -3` ends at `| \`ERR_FIELD_LIMIT_EXCEEDED\` | 422 |`, the final row of the complete §5 error table — the same real section boundary as `PRD.md`, so no pass truncated the document.
- Per-pass survivor greps in the final file: pass 1's `api_request_id` ×4; pass 2's `documentation before format` ×1 and `recomputing readiness` ×2; pass 3's `never reads` ×2 (the `analysis_readiness` clause); rung 31's `ERR_DATASET_NOT_LINKED` ×6. All four passes' work is present in the final artifact.
- Leak re-check on the final deliverable: `grep -in "harder than expert|scaffold"` → 0 hits. The Step 2 difficulty directive never reached any PRD variant.

**PIPELINE COMPLETE.** `workspace/PRD_COMPLETED.md` written; all 9 steps done (Step 8 legitimately skipped per its stated skip condition).
