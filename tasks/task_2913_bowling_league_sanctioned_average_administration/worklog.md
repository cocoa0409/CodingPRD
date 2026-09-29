# Worklog — task_2913_bowling_league_sanctioned_average_administration

## Step 1: Create task directory — 2026-09-05T15:52:15.373Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2913_bowling_league_sanctioned_average_administration/` and its `workspace/` subdirectory. Index 2913 was pre-assigned by the orchestrating prompt; no scan of `./tasks/` was performed and no index was allocated locally (concurrent pipelines on this host would collide).

## Step 2: Generate scaffold — 2026-09-05T18:48:59.370157859Z

Subagent summary (verbatim):

All three scaffold artifacts for task 2913 are complete, parse cleanly, and pass the lint. Final state:

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2913_bowling_league_sanctioned_average_administration/`)

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3077 | 161,918 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 3336 | 225,419 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 9074 | 637,178 |

`worklog.md` and `workspace/` untouched. All three `yaml.safe_load` OK. `SCAFFOLD.yaml` top-level keys are exactly `[scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles]` — neither design key leaked in; each design file has exactly one top-level key.

## SCAFFOLD.yaml surface (§1.0–§1.7)
13 entities / 11 state machines (Membership carries two parallel axes: sanction UNSANCTIONED→PENDING_REMITTANCE→SANCTIONED/back, and fiscal UNPAID→INVOICED→REMITTED/REFUNDED→INVOICED) / 3 OCC rules / 11 calculations / 47 validations in one strict priority ladder / 56 endpoints / 58 error ids / 5 roles. `complexity_profile`: primary `compliance_audit`, secondary `ledger_reconciliation`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`, topology flat, state_machine_shape cyclic, role_model segregation_of_duties, consistency immediate, difficulty_level `expert_plus`.

## §1.8 — 9 rule_ids / 20 instances (≥2 each)
`dual_variant_calc` (2), `combinatorial_formula` (3), `non_linear_state_machine` (2), `transitive_cascade` (2), `priority_pair_validation_conflict` (2), `boundary_precision_check` (3), `cross_entity_state_dependency` (2), `resource_temporal_overlap` (2), `compensating_invariant` (2).

## §1.9 — all nine guide sections / 73 instances (52 active, 21 `excluded_because` stubs)
entities 10/10 · state_machines 20/14 · calculations 12/6 · validations 13/11 · endpoints 6/4 · errors 3/1 · rbac 3/3 · cross-cutting complexity layers 4/2 · consistency model 2/1.

## Lint verdict (verbatim, complete block)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2913_bowling_league_sanctioned_average_administration/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2913_bowling_league_sanctioned_average_administration/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2913_bowling_league_sanctioned_average_administration/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    56
  §1.1 entities declared:     13
  §1.8 instances scanned:     20
  §1.9 instances scanned:     52
  Calls scanned (§1.8+§1.9):  2338

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Coverage audits (all green)
- Uncovered error ids: `[]` — all 58 are triggered by at least one instance.
- Endpoints never called: `[]` — all 56 exercised.
- Unbound placeholders: 0 across both design files (every `${var}` is either a setup-declared id or a prior `captures` key in the same instance).
- Instance names: 93 total, 93 unique — no collisions across the union of §1.8 and §1.9; every `excluded_because.difficulty_instance` resolves to a real §1.8 instance.
- Grounds refs: all resolve to declared §1.1–§1.6 elements. One last fix this pass — `corner_two_conditional_action_endpoints_reject_the_wrong_companion_field` cited a nonexistent `state_machines.LanePair.CERTIFIED_to_CERTIFIED`; replaced with the two real transitions the recipe actually drives (`EXPIRED_to_CERTIFIED` for RECERTIFY, `CERTIFIED_to_REVOKED` for REVOKE).

## Notes for the orchestrator
- The §1.9 pass doubled as the mandated §1.5/§1.4 audit and produced **15 SCAFFOLD.yaml corrections** across the earlier passes (reachability of priority 25, dues clarification on priority 15, conditional-input + pagination bounds on priority 9, ERR_INVALID_REQUEST condition extension, and eleven earlier ones). No scaffold change was needed in this final pass — the two remaining gaps (an unreachable `ERR_SEGREGATION_OF_DUTIES` and an unreachable 8% reserve tier) were closed inside the test recipes via fixture patches rather than by weakening a rule, which is the desired outcome.
- Per the known "difficulty directive leaks via scaffold" hazard: I was told to use the scenario verbatim, so `scenario:` still begins with the line `Generate task harder than expert level!`. That line should be stripped before Step 3 so it cannot reach PRD.md.

Orchestrator note: acted on the subagent's final warning — stripped the two lines (`Generate task harder than expert level!` + following blank) from `SCAFFOLD.yaml`'s `scenario:` block. `grep -ril "harder than expert"` over the task dir now returns nothing; `SCAFFOLD.yaml` still parses and its 13 top-level keys are unchanged (now 3075 lines / 161,875 bytes). The difficulty directive therefore cannot reach the doc generator in Step 4.

## Step 3: Copy shared files — 2026-09-05T18:49:26.554291618Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T19:04:53.298306266Z

Subagent summary (verbatim):

PRD generation is complete.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2913_bowling_league_sanctioned_average_administration/workspace/PRD.md` — **478 lines / 102,783 bytes**

## Section list
- `# Bowling League & Sanctioned Average Administration API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Officers, Bowlers and Role-Based Access Control · 2.2 API Response Structure (+ the two `####` subheads) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and the Logical Clock · 2.5 Optimistic Concurrency on the League, the Match and the Prize Fund · 2.6 The Order in Which a Request Is Refused · 2.7 Conditionally Required Inputs and Bylaw Coherence · 2.8 Precision, Rounding and the Conventions That Differ Between Them · 2.9 Cascades, Derived Fields and Compensating Actions · 2.10 Segregation of Duties
- `## 3. Business Logic & Workflows` — 3.1 The Organizational Meeting · 3.2 Teams, Enrolment and the Prior-Season Record · 3.3 Sanctioning: Remitting Fees Upward and the Four-Hop Cascade Back Down · 3.4 Certified Lanes and the Legal Lineup · 3.5 Match Night: Opening, Scoring, Forfeiting and Certifying · 3.6 Averages, Handicaps and the Two Bases the Bylaws Can Choose · 3.7 Weekly Dues, Prize-Fund Accumulation and the Distribution Waterfall · 3.8 Honor Scores: Claiming, Verifying and Certifying an Award · 3.9 Protests, the Hearing Cycle and Escalation to the Association
- `## 4. Endpoint Definitions` — 56-row, exactly-4-column table (verified: every row splits to 4 fields)
- `## 5. Error Code Catalogue` — 58-row, exactly-2-column table

## Coverage (machine-verified against SCAFFOLD.yaml)
- **Entities/fields:** 13 entities, 133 field names + 68 POST input names + 26 GET query params = **144 required names, 0 missing**.
- **Endpoints:** 56 scaffold endpoints ↔ 56 table rows; set difference in both directions is empty (no missing, no extras). `api_prefix` is `""`, so all paths are root-mounted.
- **Errors:** all **58** scaffold error codes present with their statuses; 0 missing.
- **State machines:** **45 distinct states**, 0 missing; all **55 transitions** present with source and target co-located in a single sentence/bullet (includes Membership's two independent axes, the cyclic `UNDER_REVIEW → REMANDED → UNDER_REVIEW`, the FeeRemittance re-filing loop, the AwardApplication evidence loop, and Match's three-way branch).
- **Calculations:** all **11** rendered as prose (entering/bowler average, bowler handicap, both `team_handicap_per_game` variants, match points, remittance pricing, both prize-fund bases, the 7 pinned waterfall steps, honor-score thresholds, and both conservation invariants). No pseudocode; every symbolic expression is natural language.
- **Validations:** all **47** rendered as an explicit numbered priority list in §2.6 with error ID, HTTP status and `applies_to` scope.
- **OCC:** all **3** concurrency rules with their occ field names, write endpoints and 412 error IDs, plus an explicit statement that no other endpoint accepts a version field.
- **Side effects:** the 31 endpoints carrying `side_effects` have theirs narrated in §3 (both four-hop cascades, forfeit preallocation, disbursement/reversal compensation).

## Hard Contracts
- **Contract 1 (Field-Name Coverage): PASS** — 144/144 required names appear verbatim in backticks.
- **Contract 2 (Rule Coverage): PASS** — priority ordering rendered explicitly (not by text order), OCC, cross-entity side effects, applies_to scopes, sibling-branch symmetry (ACCEPT/REJECT, CERTIFY/DENY, the four protest rulings), and the tail categories (all transitions, all calculations, all validation conditions, all endpoint side_effects) all confirmed.
- **Contract 3 (§3 Path Purity): PASS** — 300 distinct backtick tokens inside §3; **0 violations** (none start with `/`, none is a bare HTTP method, none is a method+path pair). All paths and methods are confined to §2.5, §2.6 and §4.

## Truncation verification
`wc -l` = 478. `grep -n '^#'` returns all 27 planned headings in order. `tail` shows the file ending cleanly on the final error row `` | `ERR_DUES_AMOUNT_MISMATCH` | 422 | `` — a complete table row at a real section boundary, no audit footer, no mid-sentence cut. §2.2 was appended byte-for-byte from the skill's fixed source file. A fuzzy-language scan now returns zero hits (one "and so on" in the waterfall's ranking step was rewritten as an explicit quantified statement).

Nothing outside `workspace/PRD.md` was touched — `worklog.md`, both SCAFFOLD design files and `workspace/INSTRUCTION.md` retain their original timestamps. The two withheld design files were never opened or grepped; all worked examples in the PRD come from SCAFFOLD.yaml itself. Scratch work is confined to `/tmp/task_2913_prd/`.

Orchestrator verification (independent, per the known doc-generator truncation hazard): `wc -l` = 478 / 102,809 bytes; `grep -n '^#'` shows all 27 headings in order; `tail -12` ends on the complete final error-catalogue row `| ERR_DUES_AMOUNT_MISMATCH | 422 |` — a real section boundary, not a mid-sentence cut. No regeneration needed. Also re-confirmed the difficulty directive did not leak: `grep -ril "harder than expert"` over `workspace/` returns nothing.

## Step 6: Generate implementation — 2026-09-05T19:44:31.696650091Z

Subagent summary (verbatim):

Implementation complete. Everything is under `/home/ubuntu/github/CodingPRD/tasks/task_2913_bowling_league_sanctioned_average_administration/workspace/implementation/` — nothing was written anywhere else in the task dir, and `worklog.md`, `PRD.md`, `INSTRUCTION.md` and the `SCAFFOLD*.yaml` files were read-only throughout (the two corner/difficulty design files were never opened).

**Modules (19 files, 3220 lines)**

| file | lines | role |
|---|---|---|
| `errors.py` | 82 | `ApiError` + full 58-entry `ERROR_STATUS`/`DEFAULT_MESSAGES` |
| `clock.py` | 72 | logical clock (default `2026-08-01T00:00:00Z`), ISO-8601 with 3 fractional digits, instant parsing, whole-day elapsed |
| `store.py` | 76 | 13 in-memory dicts, id/created_at/updated_at/version stamping, `apply_changes` (bumps only genuinely mutated rows) |
| `envelope.py` | 76 | `meta`/`response_type`/`data`, list pagination meta, `limit`/`offset` validation |
| `auth.py` | 103 | `X-User-ID`/`X-User-Role`, 5 roles, checks 1→3, not-found families, officer/owner binding |
| `shape.py` | 173 | check 9: required/enum/int/instant/percentage/list/conditional-forbidden |
| `calc.py` | 176 | all 11 calculations + every named constant |
| `derive.py` | 285 | averages, handicaps, counters, cascades, high-water week |
| `serialize.py` | 182 | explicit per-entity field lists, read-time `certification_status` |
| `routes_core.py` | 430 | members, leagues, bylaws (17 fields + coherence), schedule, close-season, teams, memberships, lane pairs, clock |
| `routes_remit.py` | 190 | remittance draft/submit/national-decision (4-hop cascade) |
| `routes_match.py` | 416 | lineups (full ordered gauntlet), open, scores/points, certify, forfeit |
| `routes_money.py` | 187 | dues, plan drafting/approval/disbursement, award reversal |
| `routes_award.py` | 194 | honor-score filing, league verification, evidence loop, association decision |
| `routes_protest.py` | 252 | filing, hearings, rulings, VOID_MATCH 4-hop decert + asymmetric FORFEIT_AWARD |
| `routes_read.py` | 268 | 13 single reads + 12 listings with declared filters/orderings |
| `app.py` | 49 | blueprint registration, `ApiError`/`HTTPException` handlers, `0.0.0.0:$PORT` |
| `start.sh` / `requirements.txt` | 8 / 1 | guarded `pip install`, `exec python3 app.py` |

**Verification**

- `python3 -m py_compile` passes on all 17 modules (`ALL_COMPILE_OK`), no `__pycache__` left behind.
- **Endpoint count: 56 implemented = 56 in the PRD table** (31 POST, 13 GET singles, 12 GET lists), enumerated from `app.url_map`.
- **Cold boot: 0.641 s** from `bash start.sh` to first served request on a random high port; server log is Werkzeug access lines only.
- **Storage purely in-memory, zero seeded entities**: `store.Store` holds 13 dicts, all empty at import (asserted programmatically); a grep for `sqlite|open(|json.dump|pickle|/tmp` in the implementation returns only two docstrings. A restarted server reports `total_count 0` on `/leagues`.
- **Hand-constructed requests** (all correct): 401 `ERR_UNAUTHENTICATED` envelope on a missing header and on a blank `X-User-ID`; 403 `ERR_FORBIDDEN_ROLE` for an undeclared role; 403 `ERR_UNKNOWN_ACTOR` for an entity-backed role with a non-member id; 201 member/league creation; 403 `ERR_NOT_LEAGUE_SECRETARY` when a non-secretary charters; 200 bylaw adoption (version 1→2, `FORMING→BYLAWS_ADOPTED`); prize fund auto-created at chartering discoverable via `GET /prize-funds`; 400 `ERR_INVALID_REQUEST` on `limit=0`; clock default `2026-08-01T00:00:00.000Z` then advanced.
- **A full 40-call end-to-end run passed with 0 failures**: charter → bylaws → 2 teams → 4 memberships → lane pair → schedule → remittance (12400 = 4x2600 + 4x500, no penalty) → ACCEPT 4-hop (league `SANCTIONED`, 2 confirmed teams, 4 sanctioned members, DRAFT→SCHEDULED) → lineups → open → scores (points 4.0/0.0) → certify (membership `certified_games 3`, `certified_pins 600`, avg 200, handicap 18 = floor(0.90x(220-200))) → 4 dues payments (fund collected 4000) → duplicate-week 409 and wrong-amount-after-paid still 409 (money checks last) → close-season → plan draft (basis 4000, reserve 200 = 5 %, admin 114 = 3 % half-up, net 3686) → approve → disburse → awards `[(1, 2212), (2, 1474)]` summing exactly to net → `PRIZES_DISBURSED` → reversal restores fund to `PLAN_APPROVED`, league to `SEASON_CLOSED`, `disbursed_at` null, and the money invariant holds (1474 + 2526 = 4000) → honor-score refusals (`ERR_AWARD_THRESHOLD_NOT_MET`, and 400 for a game number on a series type) → protest filing, ruling-before-review 409, escalate-at-round-1 409, UPHOLD + VOID_MATCH → **certified-pin invariant restored exactly** (membership back to games 0 / pins 0 / avg null / handicap 0, byte-for-byte its pre-certification values).
- Smoke servers were killed by PID/port only (`lsof -ti :<port>`); no broad pkill was used, and `prd-bench-local-run` was never invoked. Scratch files live in `/tmp/task_2913_impl/`.

**Interpretation decisions worth knowing** (each traced to PRD prose, recorded because a test could probe them): duplicate email/team name/lane-pair number → `ERR_INVALID_REQUEST` (no dedicated code exists); an unknown `series_entry_id` at score entry → `ERR_SCORE_SET_INVALID` and an unknown/foreign `forfeiting_team_id` → `ERR_REFERENCE_MISMATCH` (neither endpoint is in check 5's list); a cited slot that is not a certified average-bearing slot → `ERR_REFERENCE_MISMATCH`; an unsanctioned protest filer → `ERR_BOWLER_NOT_SANCTIONED` (the spec assigns no code); `match_id` is accepted but not required on a `RULES_INTERPRETATION` protest, since §2.7 declares its conditional-pair list exhaustive; refused verifications leave the application untouched (flags are re-evaluated for the decision, not persisted on failure); the association may not impose `FORFEIT_AWARD` (→ `ERR_REMEDY_NOT_APPLICABLE`).

## Step 5: Generate unit tests — 2026-09-05T19:54:31.10596322Z

(Launched concurrently with Step 6 in a single assistant message per the skill; it finished after Step 6, hence the out-of-order heading. Append-only worklog, so entries appear in completion order.)

Subagent summary (verbatim):

Step 5/6 test generation for task_2913 is complete and audited.

## Deliverables

**`test_helpers/`** (Stage 1, 9 files at the task root): `types.py` (25 domain enums + 13 entity TypedDicts), `constants.py` (fee/average/waterfall constants, `BASE_BYLAWS` = the 17 CONFIG-B values), `api_errors.py` (58-id `ApiErrorId` enum + status map, registered at import), `api_client.py` (60 typed endpoint methods; the single ISO-8601 canonicalisation point), `test_users.py` (role builders + 5 malformed-identity builders), `factories.py`, `assertions.py`, `fixtures.py` (6 layered builders + 8 pytest fixtures), `__init__.py`.

**`test_suite/`**: `conftest.py` + 12 test modules, **250 tests collected** (`pytest --collect-only -q`, 0 collection errors, 0.56s):

| file | tests | file | tests |
|---|---|---|---|
| test_01 dual_variant/formula | 21 | test_07 corner state machines B | 14 |
| test_02 state machines/cascades | 18 | test_08 corner calculations | 17 |
| test_03 priority/boundaries | 14 | test_09 corner validations A | 22 |
| test_04 dependency/overlap/compensation | 20 | test_10 corner validations B | 24 |
| test_05 corner entities | 23 | test_11 corner endpoints+errors | 23 |
| test_06 corner state machines A | 17 | test_12 corner rbac/cross-cutting | 37 |

## Design-index coverage

**All 72 live instances translated, zero skipped** — queue A 20/20, queue B 52/52. No instance failed the PRD-first two-condition filter outright. Independent confirmation of the denominators: the scaffold's own worklog records "20 instances" and "73 instances (52 active, 21 `excluded_because` stubs)", matching my grep-built index exactly.

**Tag audit (AST-based, over all 12 files):** 250 test functions, 250 `Design:` lines — exactly one per test, every tag byte-matching a real `name:` in the source yaml, **zero** untagged/dual-tagged/unknown tags, **zero** tags pointing at any of the 21 stubs, **zero** tags appearing in more than one file, and zero test-function name collisions across the suite. No `mark.skip`/`xfail`/`pytest.skip` anywhere. None of the 21 stub instance names appears in any test file.

## Constraint verification

- `ls -d` confirms `test_helpers` and `test_suite` at the **task root**; `workspace/test_helpers` and `workspace/test_suite` **confirmed absent**.
- Nothing under `workspace/implementation/` was read or written by me or any worker; no server started, no `prd-bench-local-run`.
- `python3 -m py_compile` clean on all 21 files. All 7 requested fixtures resolve from `conftest.py`/`fixtures.py`.
- Fixture fidelity: zero money-as-string literals, zero date-only literals, zero whitespace-only header values. Single-unwrap holds — the only `["data"]` accesses are two raw-envelope shape assertions in test_11 on `response.json()` plus three helper docstrings.
- `test_helpers/` mtimes all predate 19:20 (frozen through Stage 2); `SCAFFOLD*.yaml`, `PRD.md`, `INSTRUCTION.md` untouched. `worklog.md` grew 11195->17210 at 19:44 — that was the **orchestrator's own Step 6 implementation entry**, not any of my workers; Steps 1-4 are intact and nothing was truncated. No Step 5 heading was added by me.
- `__pycache__`/`.pytest_cache` cleaned; scratch confined to `/tmp/task_2913_tests/`.

## Divergences resolved PRD-over-yaml (worth relaying to Step 7)

Recurring across five workers: the yaml repeatedly asserts `current_average is null` before any certification, but §3.6's BLENDED formula with a non-null `entering_average` and non-zero prior games derives a value — every worker asserted the derived value instead. Others: `LINEUPS_SUBMITTED` replaced by the §3.4 `SCHEDULED -> SCHEDULED` self-loop; `RECERTIFY` tests advance the clock to `EXPIRED` first since only `EXPIRED -> CERTIFIED` is pinned; an illegal `weekly_dues_cents: 12500` re-expressed at the legal 10000 max while still hitting the 100000-cent reserve threshold exactly; full prize-money restoration tested with a single-place plan because the fund leaves DISBURSED on the first reversal; `approve-plan`'s HTTP status not pinned, so it runs through the lenient setup helper.

## Step 7: Run tests and iterate — 2026-09-05T20:18:24.192187352Z

Subagent summary (verbatim):

All 8 rounds green at 250/250. Here is the summary for the worklog.

---

**Iterations run:** 2 (baseline sweep, one fix batch, verification sweep).

**Tests deleted:** none. No test failed the STEP 1 coverage or unique-derivability checks — the two failures were both traceable to a PRD sentence that uniquely determines the outcome, and the artifact was the side that had mistranslated it.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:**
- `test_suite/test_12_corner_rbac_and_crosscutting.py`, `test_the_owning_bowler_and_the_owning_captain_are_obeyed` (line ~758): expected match `status` changed from `LINEUPS_SUBMITTED` to `SCHEDULED`. The test submits only **one** side's lineup (`team_ids[0]`, the away side) on week two's `SCHEDULED` match, whose opposing side has no slots; PRD §3.4 states verbatim "A submission on a `SCHEDULED` match where the other side has no slots yet leaves the match at `SCHEDULED` — the self-loop `SCHEDULED → SCHEDULED`." The implementation was already PRD-faithful; the assertion had borrowed the two-sided outcome.
- `test_suite/test_12_corner_rbac_and_crosscutting.py`, `test_a_lineup_freezes_handicaps_that_only_the_certify_call_created` (line ~1639): identical mistranslation, identical fix. The test's real subject — that the freeze picks up the post-certification handicaps 36+18=54 rather than the entering 36+22=58, and that week one's frozen 36/22 and `home_team_handicap_per_game` 58 stay untouched — is unchanged and still asserted; only the status literal moved to the PRD's self-loop value.

**Fixes applied to `implementation/`:** none. No implementation defect was found; the baseline sweep's 248/250 was fully accounted for by the two assertion literals above, deterministic in all 8 rounds with no load-flakiness anywhere in the run.

**Final sweep evidence:**
- results.1.json — 250/250
- results.2.json — 250/250
- results.3.json — 250/250
- results.4.json — 250/250
- results.5.json — 250/250
- results.6.json — 250/250
- results.7.json — 250/250
- results.8.json — 250/250

(0 failed, 0 errors, 0 skipped in every round.) `worklog.md`, `PRD.md`, `INSTRUCTION.md`, the `SCAFFOLD*.yaml` files and `sweep.sh` were not touched; `git status` shows the task tree as the only change, storage in `implementation/` remains in-memory dicts with no SQLite, no on-disk JSON and no `/tmp` cache, and no stray test directories were left under `workspace/`.

Orchestrator verification (independent, per the known "Step 7 claims a clean sweep with no artifacts" hazard): all eight `results.$i.json` exist under `workspace/implementation/` (each ~77 KB, all written 20:15) and parse to `passed 250 / failed 0 / total 250 / errors 0 / skipped 0`. The green claim is confirmed from the per-round artifacts, not from `sweep.log`.

Orchestrator decision on Step 8: NOT skipped. Step 7 made 0 `implementation/` fixes but 2 `test_suite/` fixes, so the skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes) is not met. Both fixes are assertion mistranslations of a PRD sentence the subagent quotes as already verbatim in §3.4, so Step 8 may well find nothing to patch — but the scan is run rather than assumed.

## Step 8: Finalize PRD — 2026-09-05T20:20:19.962379046Z

Subagent summary (verbatim):

## Result: PRD_FINALIZED.md is byte-identical to PRD.md — no edit was warranted

Created `/home/ubuntu/github/CodingPRD/tasks/task_2913_bowling_league_sanctioned_average_administration/workspace/PRD_FINALIZED.md` via `cp`. No edits applied.

**Line counts:** PRD.md 478 lines / PRD_FINALIZED.md 478 lines — 0.0% delta. Identical md5 (`3bafccd0a89b51d0095c5a83869b4833`), `diff` clean.

**Change bullets:** none.

### Why no edit

Both Step 7 items are the *same* subject and the *same* mistranslation, and the PRD already determines it verbatim.

`/home/ubuntu/.../workspace/PRD.md` §3.4, line 245:
> "A submission on a `SCHEDULED` match where the other side has no slots yet leaves the match at `SCHEDULED` — the self-loop `SCHEDULED → SCHEDULED`. A submission on a `SCHEDULED` match where the opposing side already has slots for this match completes both sides and advances `SCHEDULED → LINEUPS_SUBMITTED` … All three cases carry the same slot preconditions and the same side effects, and all three increment the match's `version` by 1."

The implementation is a literal transcription of that sentence at `/home/ubuntu/.../workspace/implementation/routes_match.py:195-197`:

```python
if match["status"] in ("DRAFT", "SCHEDULED") and opposing_slots:
    match["status"] = "LINEUPS_SUBMITTED"
touch(match)
```

`opposing_slots` is computed at line 149 as `derive.side_slots(match["id"], opponent_id)`, i.e. exactly "the other side has no slots yet". Both fixed tests submit one side only onto a `SCHEDULED` week-two match whose opposing side is empty, so `opposing_slots` is falsy and the status is left untouched — the PRD self-loop. `touch()` (`implementation/store.py:54-59`) bumps `version` by 1 unconditionally, matching the "all three increment" clause. The tests' `LINEUPS_SUBMITTED` literal had borrowed the two-sided branch; the artifact, not the PRD, was wrong.

### Pre-edit search log

Even though no edit was committed, the mandatory search was run for the one candidate subject:

**(a) Subject:** the match status outcome of a lineup submission, and its side-effect set (frozen side handicap, version bump).

**(b) Impl paths enumerated** (`grep -n "LINEUPS_SUBMITTED\|SCHEDULED"` across all of `implementation/*.py`, then read in full):
- `routes_match.py:103` — legality gate `("DRAFT","SCHEDULED","LINEUPS_SUBMITTED")` -> matches PRD's "legal while the match sits at `DRAFT`, `SCHEDULED` or `LINEUPS_SUBMITTED`".
- `routes_match.py:195-197` — the transition itself (the Step 7 site) plus the `LINEUPS_SUBMITTED → LINEUPS_SUBMITTED` self-loop, which falls out of the same condition being false.
- `routes_match.py:191-194` — the parallel side-effect that writes `home_`/`away_team_handicap_per_game`, unconditional on status; consistent with PRD's "same side effects" in all three cases and with the second test's surviving `away_team_handicap_per_game=54` assertion.
- `routes_match.py:209` — `open_match` requires exactly `LINEUPS_SUBMITTED`; a self-looped `SCHEDULED` match is correctly not yet openable, matching PRD's "at which point the match becomes openable".
- `routes_match.py:402` — `forfeit` accepts `("SCHEDULED","LINEUPS_SUBMITTED","OPEN")`; PRD §3.6 (line 263) already enumerates all three, so the self-loop leaving a match at `SCHEDULED` does not strand the forfeit surface.
- `routes_remit.py:173` — the only other writer of `"SCHEDULED"` (the sanction cascade hop 4, `DRAFT → SCHEDULED`); already pinned by PRD line 233.
- `store.py:54-59` — `touch()`, the version bump shared by all three cases.

**(c) Wording adjustment:** n/a — no wording was proposed, because every enumerated path is already correctly described by the existing §3.4 prose. Inserting a restatement of the self-loop would have been a redundant edit with no Step-7-traceable silence behind it.

### One out-of-scope observation for Step 9

While enumerating, I noted a genuine PRD silence adjacent to (but not at) the Step 7 site: PRD §3.4 permits submission from `DRAFT` but never states the `DRAFT` outcome, whereas `routes_match.py:195` folds `DRAFT` into the same branch as `SCHEDULED` (`DRAFT` + opposing slots -> `LINEUPS_SUBMITTED`; `DRAFT` alone -> stays `DRAFT`). No Step 7 fix touched that path, so under the HARD SCOPE rule I deliberately left it alone rather than manufacture a traceable-looking edit. It is a legitimate Step 9 candidate.

Orchestrator note: a byte-identical `PRD_FINALIZED.md` is the correct Step 8 outcome here — Step 7 applied 0 `implementation/` fixes, and its 2 `test_suite/` fixes were assertion literals contradicting prose already verbatim in §3.4, so there was no PRD silence at the Step 7 sites to pin. Verified: `md5sum` matches PRD.md and `diff` is clean. Step 9 (which must NOT be identical) will run as three sequential module-partitioned passes over one shared PRD_COMPLETED.md, and the `DRAFT`-outcome silence flagged above is being handed to the pass that owns `routes_match.py`.

## Step 9: Complete PRD — 2026-09-05T20:58:42.113128234Z

Run as three sequential module-partitioned passes over one shared `PRD_COMPLETED.md` (pass 1 did the `cp`; passes 2 and 3 inherited and edited in place via targeted Edit calls only). Partition: pass 1 = app/errors/clock/store/envelope/auth/shape/serialize/routes_read (infrastructure + whole read surface); pass 2 = calc/derive/routes_core/routes_remit; pass 3 = routes_match/routes_money/routes_award/routes_protest. Each pass handed forward the out-of-scope silences it spotted, and the final pass explicitly disposed of all 8 inherited hand-off notes.

### Pass 1 summary (verbatim)

All 15 edit sites verified. PRD_FINALIZED.md 478 lines / 102,809 chars -> PRD_COMPLETED.md 478 lines / 108,395 chars. Char delta +5,586; line count unchanged (every edit in-paragraph, no new paragraphs or sections). Changed lines: 15, 23, 46, 47, 49, 76, 78, 86, 90, 112, 116, 160, 182, 352, 354.

**Counts**: ambiguity-pins 15, mismatch-revisions 0. The error catalogue was verified programmatically — all 58 ids and all 58 HTTP statuses in §5 match `errors.py::ERROR_STATUS` exactly, and every field in every `serialize.py` projection is already named in the PRD prose, so no catalogue or field-name mismatch existed.

**Changes**
- §2.1 — revise — ambiguity — a whitespace-only header counts as empty (401), and both header values are trimmed before role/identifier comparison — auth.py:20-25
- §2.1 — revise — ambiguity — reads carry no ownership binding either, `/members/{id}` added to the all-five-roles read list, and the financial restriction stated to cover listings as well as single reads — routes_read.py:47-50,71-74,95-98,162-169,213-220
- §2.2 — revise — ambiguity — `api_request_id` is `req_` plus exactly twenty upper-case-alphanumeric characters — envelope.py:11-19
- §2.2 — revise — ambiguity — `api_request_timestamp` comes from the logical clock, not real time, so it does not advance between requests — envelope.py:18
- §2.2 — revise — ambiguity — a resource object carries exactly the entity's narrated fields plus §2.4 identity fields and no others, unset fields present as null, same projection for single/write/list responses — serialize.py:108-119
- §2.3 — revise — ambiguity — a non-integer `limit`/`offset` is malformed too, and `meta` echoes the effective (defaulted) values — envelope.py:50-70
- §2.3 — revise — ambiguity — insertion order is the tie-break on equal `created_at`; the lineup-slot listing orders by `team_id` as a string; both departing orderings fall back to insertion order — store.py:74-76, routes_read.py:203-204,237-238
- §2.4 — revise — ambiguity — `updated_at` is stamped equal to `created_at` at insert — store.py:42-51
- §2.4 — revise — ambiguity — non-string/blank instants rejected; a non-`Z` explicit offset is accepted and normalised to UTC; rendered instants always UTC with three fractional digits, truncated not rounded — clock.py:28-56
- §2.6 check 5 — revise — ambiguity — an absent, `null` or non-string identifier is not looked up at check 5 and falls to check 9 (400 if required, accepted if optional); a present-but-blank string yields the entity's 404 — auth.py:61-70 (confirmed `body_ref` precedes `req_id` at every call site)
- §2.6 check 9 — revise — ambiguity — booleans and strings are not integers; percentages carry <=2 decimals and may arrive as a number or a decimal string; array max lengths; string length measured as supplied while blankness is tested after trimming; absent/empty body read as `{}`, non-JSON or non-object body refused — shape.py:17-28,47-54,57-67,145-168
- §2.7 — revise — ambiguity — a field carrying JSON `null` counts as absent in *both* directions of every conditional pair — shape.py:31-32,171-173
- §2.9 — revise — ambiguity — a cascade row whose recomputation yields the values it already held is not a mutation and moves neither `updated_at` nor `version` — store.py:62-71, derive.py:274-285
- §4 preamble — revise — ambiguity — trailing slash accepted; undeclared method on a declared path -> `ERR_INVALID_REQUEST` at 400, undeclared path -> `ERR_INVALID_REQUEST` at 404; routing resolves before the §2.6 header checks — app.py:23,40-44
- §4 filter paragraph — revise — ambiguity — undeclared query params ignored; filters are case-sensitive exact equality; `season_year`/`week_number`/`certified` refuse untypeable values (400) while a well-formed non-matching value yields an empty page; `total_count` is post-filter; `certification_status` filtered against the read-time derivation — routes_read.py:16-42,178-180

**Hand-off notes (pass-2/pass-3 silences not edited by pass 1)**
- `routes_remit.py:142-147` (pass 2) — `national_member_number` minting sorts pending members by `(created_at, _seq)`; §3.1 pins ascending `created_at` but not the insertion-order tie-break.
- `routes_remit.py:160-170` (pass 2) and `routes_money.py:156-162,177-186` (pass 3) — the league row and the prize-fund row can each take **two** `version` increments in one request (a counter recompute via `apply_changes` plus an unconditional status `touch`). Deliberately avoided any "version moves exactly once per request" wording in §2.9.
- `routes_match.py:238-262,406-410` (pass 3) — points are Python floats rounded to one decimal, so they serialize as `4.0`/`3.5`/`0.0` rather than integers; §2.8 pins "one decimal place" but not the JSON rendering.
- `routes_match.py:277,399` and `routes_protest.py:202,242` (pass 2/3) — at score entry, forfeit declaration and protest ruling, body identifiers are shape-checked (`req_id`/`opt_id`, 400 on blank or non-string) *before* resolution, i.e. these endpoints sit outside §2.6 check 5's declared scope.

### Pass 2 summary (verbatim)

Pass 2 complete. All edits were targeted in-paragraph `Edit` calls against the shared file; no new sections, no `cp`, no rewrite.

**Size**: before 478 lines / 108,395 chars -> after 478 lines / 115,292 chars (line count unchanged).

**Counts**: ambiguity-pins 22, mismatch-revisions 5.

Mismatches (PRD asserted something impl does not do):
- §3.1 — revise — mismatch — schedule adoption: a team or lane pair owned by another league yields `ERR_CROSS_LEAGUE_REFERENCE` (check 10), not `ERR_TEAM_COUNT_MISMATCH`; the latter now covers only distinct-team-count and same-side-twice — `routes_core.py:222-226,244-249`
- §3.3 hop 2 — revise — mismatch — every roster team named by a listed membership recomputes `sanctioned_roster_count` *and* `team_handicap_per_game` whether or not its status moves; confirmation is a separate consequence — `routes_remit.py:154-162`, `derive.py:140-151`
- §3.6 — revise — mismatch — roster `team_handicap_per_game` recompute list corrected from "when a team is confirmed" to "on hop 2 of the sanction cascade for every touched team" — `derive.py:140-151`
- §3.6 — revise — mismatch — the "three moments" list for averages was incomplete; enrolment and every remittance transition (submit/accept/reject) also re-derive `current_average` and `average_status` — `derive.py:274-285`, `routes_remit.py:103-107,134-138,179-183`
- §3.1 — revise — mismatch — a bylaw amendment's reach stops at memberships and teams: a team can move `PROVISIONAL -> CONFIRMED` on a lowered `legal_lineup_minimum` while the league's `confirmed_team_count`, `sanctioned_member_count` and `certified_week_high_water` are left un-recomputed — `routes_core.py:180`, `derive.py:249-254`

Ambiguities pinned:
- §3.1 — insert — email uniqueness compared on the value as supplied (case-sensitive), no length ceiling, duplicate -> `ERR_INVALID_REQUEST` — `routes_core.py:36-43`
- §3.1 — revise — `national_member_number` sequence is service-wide, starts at `NM-000001`, allocated by member `created_at` with insertion order as tie-break, not in `membership_ids` order *(pass-1 hand-off note 1)* — `routes_remit.py:139-147`, `store.py:30-32`
- §3.1 — insert — `center_name` required and not blank, no upper length bound — `routes_core.py:65`
- §3.1 — insert — chartering mismatch on `secretary_member_id` -> `ERR_NOT_LEAGUE_SECRETARY`; treasurer and secretary may be the same member — `routes_core.py:59-62`
- §3.1 — insert — fresh league has `bylaws_adopted_at` null; the auto-created fund has every monetary figure 0 and all three stamps null — `routes_core.py:80,89-104`
- §3.1 — insert — `expected_league_version` must be a non-negative integer, refused 400 before the 412 comparison; percentages/weights render back as JSON numbers (`"0.90"` -> `0.9`) — `routes_core.py:168`, `shape.py:145-155`, `serialize.py:108-115`
- §3.1 — insert — `total_weeks` non-negative, unbounded, need not agree with the highest `week_number` — `routes_core.py:218`
- §3.1 — insert — schedule response is the created-match array in supplied order, `response_type` `array`, HTTP 201 — `routes_core.py:271`
- §3.1 — insert — an unsettled match on close-season -> `ERR_LEAGUE_STATE_INVALID`; a league with no matches closes vacuously — `routes_core.py:281-287`
- §3.2 — insert — team-name collision within the league -> `ERR_INVALID_REQUEST` — `routes_core.py:301-303`
- §3.2 — insert — `team_id` is optional for `REGULAR` too, and the named team's own `status` is not consulted — `routes_core.py:330,337-340`
- §3.2 — insert — `current_average` is derived at enrolment (equals `entering_average` when non-null, else null) and the row's `version` is still 1 — `routes_core.py:356,366-370`
- §3.3 — insert — a repeated identifier in `membership_ids` -> `ERR_INVALID_REQUEST`, not `ERR_DUPLICATE_MEMBERSHIP` — `routes_remit.py:37-38`
- §3.3 — insert — draft's four null stamps; drafting consults no league `status` at all — `routes_remit.py:55-67`
- §3.3 — insert — a submission instant before `bylaws_adopted_at` counts as zero elapsed days — `clock.py:65-72`
- §3.3 — insert — a refused amount-mismatch submission still persists the corrected `declared_amount_cents`, leaving `computed_amount_cents`, `penalty_cents`, `status`, `updated_at`, `version` and every membership untouched — `routes_remit.py:92-95`
- §3.3 — insert — the national decision consults no league `status` either — `routes_remit.py:111-125`
- §3.3 hop 1 — insert — a member written twice (number + counter) advances `version` by 2; already-numbered member by 1 — `routes_remit.py:139-153`
- §3.3 hop 3 — insert — counter recompute and the `SANCTIONED` status move are two writes, so the league's `version` jumps by 2 on the sanctioning request, 1 on a counters-only one, 0 on neither *(pass-1 hand-off note 2, pinned at the §3.3 site rather than globally)* — `routes_remit.py:164-168`
- §3.4 — insert — `pair_number` collision -> `ERR_INVALID_REQUEST`; a `certified_through` already behind the clock registers fine and reads `EXPIRED` at once — `routes_core.py:383-395`
- §3.4 — insert — the certification action has no league-status gate; `CERTIFIED -> CERTIFIED` recertify is legal; a second `REVOKE` restamps `revoked_at` and bumps `version` rather than being refused; `REVOKE` leaves `certified_through`/`last_certified_at` alone — `routes_core.py:399-420`
- §4 — insert — the logical-clock setter answers 200 with an empty `data` object — `routes_core.py:424-430`

**Pass 1's edits survived** — spot-checked four, all present: the whitespace-only-header clause in §2.1, the "recomputation that changes nothing... moves neither `updated_at` nor `version`" sentence in §2.9, the twenty-character `api_request_id` clause in §2.2, and the trailing-slash sentence in §4.

**Hand-off notes for pass 3 (spotted, deliberately not edited)**
1. `routes_money.py:127` — a prize award's `weight` is the league's exact `Decimal` and `serialize.py` renders `Decimal` as a JSON float, so `"0.50"` reads back as `0.5`. Pinned that read-back rule for the *league* resource only (§3.1); §3.7's approval paragraph still silent for the award.
2. `routes_money.py:71-73` — `place_count != len(prize_place_weights)` is refused with `ERR_INVALID_REQUEST`; §3.7 states the requirement without naming a code. Also `league["prize_place_weights"] or []`, so drafting against an un-bylawed league sees an empty weight list.
3. `routes_match.py:58-61` — `calc.absentee_handicap` never consults `sanction_status`, so an `ABSENTEE` slot naming an unsanctioned membership freezes a non-zero `handicap_per_game_applied` even though that membership's own `handicap_per_game` is 0 — and §3.4's `ERR_BOWLER_NOT_SANCTIONED` gate names only `REGULAR`/`SUBSTITUTE`/`PREBOWL`. §3.6's absentee paragraph is silent.
4. `routes_match.py:262,407-410` — points are floats (`round(x, 1)`, `float(4)`), so `home_points`/`away_points` render as `4.0`/`0.0`; §3.5 is silent on the JSON form.
5. `derive.py:244-246` via `cascade_certification_change` — certification/void/forfeit refresh `dues_paid_cents` and `dues_arrears_weeks` on **every** membership of the league (bumping their `version` where the figure moves). §3.5's four-hop list mentions only the league's high-water at hop 4.
6. Nothing was written implying a 404-first ordering at `routes_match.py:277` or `routes_protest.py:202,242`; the only §2.6 cross-references are to check 10 (schedule adoption) and check 9 (uniqueness collisions and shape failures).
7. `calc.waterfall` and `calc.place_amounts` match §3.7's seven pinned steps exactly (tier boundary "at or above 100000", floor for reserve, half-up for admin, floor per place, ascending-wrap remainder). No §3.7 edit needed from pass 2.

### Pass 3 summary (verbatim)

Pass 3 of 3 complete. All work landed via targeted `Edit` calls only; `PRD_COMPLETED.md` was never copied, rewritten, or clobbered.

**Size**

| | lines | chars |
|---|---|---|
| Step 9 source (`PRD_FINALIZED.md` = `PRD.md`) | 478 | 102,809 |
| `PRD_COMPLETED.md` before pass 3 | 478 | 115,292 |
| `PRD_COMPLETED.md` after pass 3 | 478 | 126,570 |

Pass-3 delta: **+11,278 chars, 0 lines**. Cumulative Step 9 delta vs `PRD.md`: **+23,761 chars, 0 lines**. `cmp` against both `PRD.md` and `PRD_FINALIZED.md`: **DIFFERENT** (not byte-identical).

**Counts** — Pass 3: 28 changed passages via 30 Edit calls (one corrective re-edit of the §3.7 reversal version claim, plus two same-paragraph follow-ups in §3.5/§3.8) — 22 ambiguity pins, 6 mismatch revisions. Cumulative Step 9: 42 (passes 1-2) + 28 = **70 edits (59 ambiguity pins, 11 mismatch revisions)**.

**Changes**
- §2.6 check 25 — revise — mismatch — "League verification only" narrowed; the flag re-evaluation/refusal also fires on the association decision and never on the `RETURN_FOR_EVIDENCE` branch — routes_award.py:135, routes_award.py:187
- §3.4 — insert — ambiguity — the `DRAFT` lineup outcome (stays `DRAFT` with no opposing slots, `DRAFT -> LINEUPS_SUBMITTED` with them) — routes_match.py:195
- §3.4 — revise — mismatch — dropped the false claim that every membership-naming slot must be `SANCTIONED` and either on the submitting team or `roster_role` `SUBSTITUTE`; only `REGULAR`/`SUBSTITUTE`/`PREBOWL` slots are sanction-tested and `roster_role` is read by no gate — routes_match.py:110-114
- §3.4 — insert — ambiguity — position handling: non-integer/absent `position` is a shape failure, wrong slot count and any non-permutation of 1..`lineup_positions` are `ERR_ILLEGAL_LINEUP` — routes_match.py:34, routes_match.py:135-138
- §3.4 — insert — ambiguity — created-slot defaults (null game fields, `games_recorded` 0, `scratch_series` 0, `certified` false) and the exact `counts_toward_average` rule — routes_match.py:173-190
- §3.5 — revise — mismatch — the pin range fails differently at its two ends: negative -> `ERR_INVALID_REQUEST`, above 300 -> `ERR_SCORE_SET_INVALID` — routes_match.py:281, routes_match.py:300
- §3.5 — insert — ambiguity — score entry requires the league `IN_SEASON`, and an unknown `series_entry_id` yields `ERR_SCORE_SET_INVALID` (not a check-5 surface, so never `ERR_SERIES_ENTRY_NOT_FOUND`) — routes_match.py:277, routes_match.py:285, routes_match.py:294
- §3.5 — insert — ambiguity — points render as one-decimal JSON numbers (`4.0`, `0.0`, `2.5`), never integers — routes_match.py:262, routes_match.py:407
- §3.5 — insert — ambiguity — cascade hop 3's affected-team set = bowlers' roster teams plus the match's own two sides — routes_match.py:349-358
- §3.5 — insert — ambiguity — hop 4 refreshes all three league counters and then **every** membership's dues figures, not only the participating ones — derive.py:234-246
- §3.5 — insert — ambiguity — forfeit declaration has no league-status gate of its own; an unknown `forfeiting_team_id` is `ERR_REFERENCE_MISMATCH`; and it runs cascade hops 2-4 over the replaced memberships and both sides — routes_match.py:392-403, routes_match.py:414-415
- §3.5 — insert — ambiguity — a team's `total_points` is likewise a one-decimal JSON number, created at `0.0` — routes_core.py:251-268
- §3.6 — insert — ambiguity — the `ABSENTEE` freeze consults only the league bylaws, the two averages and `member_class`; `sanction_status` is never examined, so an unsanctioned bowler may hold an `ABSENTEE` slot — routes_match.py:59-63
- §3.7 — insert — ambiguity — `week_number` above the league's `total_weeks` is a shape failure (`ERR_INVALID_REQUEST`), not a state or bylaw refusal — routes_money.py:29-30
- §3.7 — insert — ambiguity — `place_count` must equal `len(prize_place_weights)` and that test runs in the shape pass, ahead of the version comparison; a null weights array counts as length 0 — routes_money.py:71-73
- §3.7 — insert — ambiguity — each award's `weight` is copied from the league's exact decimal and read back as a JSON number — routes_money.py:127
- §3.7 — insert — ambiguity — disbursement writes the fund row twice, so its `version` advances by 2 where the money recompute moves a figure and by 1 where it moves none — routes_money.py:159-160
- §3.7 — insert — ambiguity — reversal: one code `ERR_PRIZE_FUND_STATE_INVALID` for both halves, response body is the award, fund `version` +2/+1 on the same hedge, league drops back on the first reversal — routes_money.py:175-186
- §3.8 — insert — ambiguity — a match with null `certified_at` gives no honor-score window at all, so filing is refused with `ERR_FILING_WINDOW_CLOSED` — routes_award.py:85-87
- §3.8 — revise — mismatch — removed the non-existent "match is `CERTIFIED`" verification requirement and pinned the real order (flags -> segregation -> threshold); a slot still certified after a protest-driven forfeit stays verifiable — routes_award.py:132-142
- §3.8 — insert — ambiguity — association `CERTIFY` reads the stored flags rather than re-deriving them, refuses with `ERR_AWARD_EVIDENCE_INCOMPLETE`, and stores `association_ruling_note` only when supplied — routes_award.py:184-192
- §3.9 — insert — ambiguity — no protest surface consults the league's `status`, so filing, hearings, rulings and association rulings all work at any league state — routes_protest.py:24-73, routes_protest.py:191-252
- §3.9 — insert — ambiguity — a `RULES_INTERPRETATION` protest may still carry a `match_id` (optional, resolved when present); a match with null `certified_at` gives no protest window and `deadline_at` is stored null — routes_protest.py:43-58
- §3.9 — revise — mismatch — `ruling_note` is required on every one of the four decisions, not "an optional `ruling_note`" — routes_protest.py:201
- §3.9 — insert — ambiguity — `forfeiting_team_id` is not resolved at the ruling surface (never `ERR_TEAM_NOT_FOUND`), and an ineligible `ESCALATE` is `ERR_PROTEST_STATE_INVALID` refused before the segregation test — routes_protest.py:202, routes_protest.py:205-208
- §3.9 — revise — mismatch — `forfeiting_team_id` need only name one of the match's two sides; which side is never examined, so the forfeit may fall on the filer's own team. Also pinned: a `VOID_MATCH`/`FORFEIT_AWARD` on a protest citing no match is `ERR_REMEDY_NOT_APPLICABLE` — routes_protest.py:179-187
- §3.9 — insert — ambiguity — `void_reason` is written as `"<protest_id>:<remedy>"` — routes_protest.py:124
- §3.9 — insert — ambiguity — `FORFEIT_AWARD` keeps the match's `certified_at`, creates its replacement `FORFEIT` rows with `certified` **true**, and refreshes the same affected-team set plus league counters and every membership's dues — routes_protest.py:136-170

**Hand-off notes — disposition**
1. **Award `weight` Decimal->JSON float** — pinned, §3.7 approval paragraph.
2. **`place_count != len(prize_place_weights)` + `or []`** — pinned, §3.7 drafting paragraph (shape-pass precedence and the null/empty case).
3. **`calc.absentee_handicap` ignores `sanction_status`** — pinned twice: §3.4 sanction-gate sentence and §3.6 ABSENTEE sentence.
4. **Points render as `4.0`/`0.0`** — pinned, §3.5 points paragraph, plus `total_points` in the team-figures paragraph.
5. **`cascade_certification_change` refreshes dues league-wide** — pinned at §3.5 hop 4 and referenced from §3.5 forfeit and both §3.9 remedies.
6. **Shape-checked identifiers outside check 5** — pinned at three sites: §3.5 score entry (`series_entry_id`), §3.5 forfeit (`forfeiting_team_id`), §3.9 ruling (`forfeiting_team_id`).
7. **Two `version` increments** — the prize-fund half is pinned at both §3.7 disbursement and §3.7 reversal, each hedged for the no-op recompute. The **match** half was deliberately *not* written: no request writes the match row twice (every match mutation is direct field assignment plus a single `touch`, and `derive.freeze_side_handicap` has no callers), so pinning it would have introduced a new mismatch.
8. **`DRAFT` lineup-submission outcome** — pinned, §3.4 state-outcome paragraph.

**Survival spot-check**
- Pass 1 — §2.1 whitespace-only header / blank-as-401 sentence: present at L15. `api_request_id` "exactly twenty characters" bullet: present at L46.
- Pass 2 — §3.2 "`"0.90"` and `0.9` both read back as `0.9`" sentence: present at L200. §3.3 hop 3 "the league's `version` advances by 2" sentence: present at L232.
- `workspace/sweep.sh` and all 8 `implementation/results.*.json` still in place; no servers started, no broad kills, scratch confined to `/tmp/task_2913_step9p3/`.

---

## Pipeline complete — orchestrator closing verification (2026-09-05)

- `workspace/PRD_COMPLETED.md` exists: 478 lines / 126,570 chars. `cmp` vs `PRD.md` differs at byte 3011 (line 15), so the Step 9 scan demonstrably landed — it is NOT byte-identical, which is the required Step 9 invariant.
- `workspace/PRD_FINALIZED.md` IS byte-identical to `PRD.md` (md5 `3bafccd0a89b51d0095c5a83869b4833`) — legitimate for Step 8, which had 0 `implementation/` fixes to align to.
- Test evidence: all eight `workspace/implementation/results.$i.json` present and independently parsed by the orchestrator to `passed 250 / failed 0 / total 250 / errors 0 / skipped 0`.
- No stray `workspace/test_helpers` or `workspace/test_suite` directories; `test_helpers/` and `test_suite/` sit at the task root as required.
- Exactly one `worklog.md` in the task tree (no cwd-drift strays under `workspace/`).
- Difficulty-directive containment: `grep -ril "harder than expert"` over the whole task dir matches only `worklog.md` itself, which is the orchestrator's own record of stripping the line in Step 2. Neither `PRD.md`, `PRD_FINALIZED.md`, `PRD_COMPLETED.md`, `SCAFFOLD.yaml` nor any generated artifact contains it.
