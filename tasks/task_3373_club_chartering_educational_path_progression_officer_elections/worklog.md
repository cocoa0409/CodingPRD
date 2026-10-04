# Worklog — task_3373_club_chartering_educational_path_progression_officer_elections

## Step 1: Create Task Directory — 2026-10-01T00:00:00.000Z

Task directory `./tasks/task_3373_club_chartering_educational_path_progression_officer_elections/` was pre-allocated by the caller (already present with an empty `workspace/` inside). No index computation and no directory creation performed; the pre-allocated path was used verbatim.

## Step 2: Generate Scaffold — 2026-10-01T00:00:00.000Z

All three artifacts are written and verified.

### Files written

| File | Lines | Size |
|---|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_3373_club_chartering_educational_path_progression_officer_elections/SCAFFOLD.yaml` | 1941 | 102 KB |
| `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1664 | 113 KB |
| `.../SCAFFOLD_CORNER_DESIGN.yaml` | 1497 | 100 KB |

File split honored: `scaffold_difficulty_design` / `scaffold_corner_design` appear only as the single top-level key of their own files, never inside `SCAFFOLD.yaml`. (The pre-existing `worklog.md` + empty `workspace/` from the caller's Step 1 were left untouched.)

### Counts

- **Entities 11** (flat topology, 19 declared FKs, one self-referential `Club.sponsor_club_id`), **state machines 13 / 49 transitions**, **calculations 9 / 6 variants**, **validations 19** (priorities 1–19), **endpoints 47** (22 GET / 25 POST), **errors 30**, **concurrency rules 3**, **roles 4** (2 opaque-backed identities, 2 `entity_backed`).
- **§1.8: 24 instances across all 9 Difficulty Rules** (2–3 each: dual_variant_calc 2, combinatorial_formula 3 covering modes a/b/c, non_linear_state_machine 2, transitive_cascade 3 with depths 5/4/4 from three different triggers, priority_pair_validation_conflict 3 across three different error-category pairs, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2 with different interval geometry, compensating_invariant 3 on three different conserved quantities).
- **§1.9: 39 instances across all 9 guide sections**, 35 active + 4 `excluded_because` stubs citing §1.8 instance names.

### Verification

`python3 scaffold_lint.py <task-dir>` → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (479 calls scanned, 0 violations). Extra self-audits, all passing: grounds-ref resolvability (0 dangling), placeholder closure (0 unbound `${var}`), error-code coverage (every error mentioned ≥2×), forbidden OCC vocabulary (0 hits), enum producers, structural completeness (every transition has preconditions + side effects; every field has type/source/description; every role has `identity:`).

### Design adjudications

- **Archetype** `graph_constraint` + `posture_driven_gating`, layers: optimistic_concurrency, cascading_side_effects, derived_field_reconciliation, rate_threshold_triggers. Flat entity topology and self-referential FK were chosen deliberately (§0.3 flags both as 0% in existing examples).
- **Posture is cycle-scoped**: `good_standing` is re-derived only by `close-cycle` (and at charter grant) while `good_standing_score` is live — this makes the posture gate testable from a cheap fresh club and creates the §1.8 live-vs-frozen variant divergence.
- **Integer-weighted score** (30/25/20/15/10 with floor division per component) so the 80/60/40 thresholds are exactly reachable; all asserted literals were computed by executing the formulas (e.g. quote 10062 vs the wrong sum-then-round 10061; proration boundary 10063 at +90 days vs 6032 at +91 days; score 36 → REVOKED vs 40 → SUSPENDED; DCP 7 → score 80).
- **Suspension/revocation scoped to chartered clubs** so ORGANIZING-club fixtures don't cascade into REVOKED mid-chain.
- **Added `POST /toastmasters/memberships/bulk`** (best-effort, per-row results) so the 20-member charter threshold and 20-member score fixtures stay executable instead of needing 40 sequential calls; also added `cycle_opened_at`/`cycle_closed_at` inputs to the create/close-cycle endpoints so no rule depends on wall-clock time (no logical-clock endpoint needed).
- **OCC rules pass §1.2.1's serial-observability filter** by construction: each guards a create whose second instance is independently legitimate (another meeting at a different time, another completion with a different project_code, another role slot), so the stale version is the only thing that can reject it.

**One risk to flag:** 47 endpoints exceeds the §0.4 "Expert: 20–32" guideline (the skill calls that table a guideline, and its own examples run 28–64 — clinical-trial ships 37 with 15 entities). This is above the ~40 mark that my notes record as degrading impl-gen, so if Step 6 returns a rambling report, the cheapest trims are the four redundant single-resource GETs (`/role-assignments/{id}`, `/officer-terms/{id}`, `/area-visits/{id}`, `/contest-entries/{id}` — each currently needed only for filtered-list segment derivation).

### Orchestrator audit of the flagged risk (not part of the subagent report)

Cross-referenced all 47 declared endpoints against every `call:` in both design indices. The four suggested-trim GETs are indeed unreferenced by any §1.8/§1.9 instance, as are the listing GETs and `POST /area-visits*` (16 endpoints total never called). Decision: **keep SCAFFOLD.yaml intact.** Trimming to ≤40 would require removing 7 endpoints and would shrink the breadth the caller explicitly asked to maximize, for a soft guideline whose known failure mode (a rambling Step 6 report) is directly detectable and recoverable. Mitigation moved to Step 6: force incremental one-file-per-message writes and verify artifacts on disk myself. All three files verified present with correct top-level key structure.

## Step 3: Copy Shared Files — 2026-10-01T00:00:00.000Z

Copied `./INSTRUCTION.md` → `./tasks/task_3373_club_chartering_educational_path_progression_officer_elections/workspace/INSTRUCTION.md` (1424 bytes). Bash-only step, no subagent.

## Step 4: Generate PRD — 2026-10-01T00:00:00.000Z

PRD generated and all three hard contracts verified PASS. I did not open `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or any sibling task.

### Output

`/home/ubuntu/github/CodingPRD/tasks/task_3373_club_chartering_educational_path_progression_officer_elections/workspace/PRD.md` — 372 lines, ~73 KB.

**Structure** (domain-derived, no template reuse):
- §1 Introduction (3 paragraphs)
- §2 Global Specifications — 2.1 RBAC · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Common Resource Properties and Record Identity · 2.5 The Semiannual Dues Cycle Clock · 2.6 Charter Standing and Posture Reconciliation · 2.7 Recognition Points and the Composite Good-Standing Score · 2.8 Optimistic Concurrency Control · 2.9 Monetary Precision and Rounding · 2.10 Validation Precedence and Referential Integrity · 2.11 Cascade Discipline Across Aggregates
- §3 Business Logic — 9 subsections (petitioning/chartering, dues cycle & close, enrollment & payment, path progression, completions/evaluation/review, meetings & rotation, officer elections, contests, governance visits & coaching queue)
- §4 Endpoint Definitions — 47 rows × 4 columns
- §5 Error Code Catalogue — 30 rows × 2 columns

### Coverage adjudications

1. **Scaffold header says "46 endpoints"; the table actually holds 47** (22 GET + 25 POST). I emitted all 47 and verified each scaffold path appears in §4.
2. **OCC fields beyond `concurrency_rules`.** The skill's default is that only `concurrency_rules` endpoints take a version field, but the scaffold also declares `expected_membership_version` on education-path creation and `expected_education_path_version` on advance-level (validation priority 5 covers the former). All four are documented in §2.8.
3. **`ERR_CLUB_NOT_CHARTERED` / `ERR_CLUB_REVOKED` status conflict.** Validation priority 16 groups them under `http_status: 409`, but `errors[]` gives 422 for both. I followed `errors[]` in §5 and stated no status in prose (statuses live only in §5), so no contradiction is visible.
4. **Late fee, two scaffold statements kept separate.** The `ISSUED → OVERDUE` transition records a flat 500-cent late fee added to the next quote; the `dues_quote` calculation has a 5%-of-lines late line when overdue. I stated both faithfully (500 in §3.3 with the transition, the 5% rate in §3.2 with the formula) rather than silently reconciling them.
5. **Rounding worked example included** (`club_dues_cents` 2999 → 10062 pinned vs 10061 sum-then-round). This comes from the scaffold's own formula text, not from a withheld index, and it pins the per-line-then-sum order.
6. **First pass missed `dcp_recognition_points` entirely** — a coverage script caught that the formula and its tier values (`PRESIDENT_DISTINGUISHED`/`SELECT_DISTINGUISHED`/`DISTINGUISHED`) were absent. Added in full to §2.7.

### Hard Contract Reports

```
Field coverage check:
- entities[].fields: 96 required, 96 present, 0 missing
- endpoints[].request_body/input: 67 required, 67 present, 0 missing
- endpoints[].query_params: 0 required (filters are declared in the same input list), 0 missing
- path_params: paths use {id} only; all 47 paths emitted in §4
- roles: 4 required, 4 present; states: 41 required, 41 present; enum values: 84 required, 84 present; errors: 30 required, 30 present
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 19 checked, 19 expressed in prose (full precedence ladder in §2.10), 0 missing
- concurrency_rules[] OCC rejections: 3 checked (+1 scaffold-declared extra), 4 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION all named), 0 missing
- state_machines[].transitions: 49 checked, 49 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed (incl. pinned evaluation/rounding orders and all constants), 0 missing
- validations[] conditions: 19 checked, 19 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 47 checked, 47 expressed, 0 missing
- entities[].fields[] structured content: 96 checked, 96 reconstructible from prose, 0 missing
- sibling-branch symmetry: 14 groups checked (4 charter gates, 5 level requirements, 4 review/return branches, 3 role-resolution branches, 5 posture transitions, 4 contest-entry transitions, etc.), 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 712
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks run: §2.2 is byte-identical to `section-2.2-response-structure.md` (verified by diff); no fuzzy/approximating words anywhere; no forbidden concurrency framing ("simultaneously", "first-writer-wins", "race") in the OCC prose; no audit-report footer leaked into `PRD.md`.

### Orchestrator audit (not part of the subagent report)

Verified on disk: 372 lines / 73067 bytes; §4 holds 49 table rows (47 endpoints + header + separator), §5 holds 32 rows (30 errors + header + separator) — both match the scaffold counts. Two adjudications are flagged as **latent Step 7 risks** to re-check at the fix loop: (3) the `ERR_CLUB_NOT_CHARTERED`/`ERR_CLUB_REVOKED` 409-vs-422 status split between `validations[]` and `errors[]`, and (4) the flat-500-cent late fee versus the 5%-of-lines late line in `dues_quote`. Both are scaffold-internal tensions the PRD faithfully reproduced rather than invented; if a design-index test asserts one side, the fix loop must adjudicate against PRD prose rather than guess.

## Step 5: Generate Unit Tests — 2026-10-01T00:00:00.000Z

Done. The full test infrastructure is generated, collects cleanly (79 tests), and passes a mechanical audit against both design indices and the PRD.

### Files written

`test_helpers/` (9 files, 2026 lines)
| File | Lines | Contents |
|---|---|---|
| `constants.py` | 97 | Dues-quote lines, score bands, requirement table, buffer/window/slot constants, fixture clock anchors |
| `types.py` | 391 | 11 entity TypedDicts (all carry `id/created_at/updated_at/version`), 22 status enums, `UserRole` |
| `api_errors.py` | 75 | 30 error ids + HTTP map, registered via `set_error_http_status_map` |
| `api_client.py` | 225 | One method per endpoint (47) |
| `test_users.py` | 41 | Shared opaque WHQ constant + per-instance `make_*_headers(entity_id)` builders for all three entity-backed roles |
| `factories.py` | 185 | One payload factory per entity, input fields only |
| `assertions.py` | 270 | Per-entity shape assertions, score/posture invariant, paid-roster invariant, instant comparison helpers |
| `fixtures.py` | 739 | Tiers 0–4: reads/version readers, creation, state progression, hierarchies, lifecycle shortcuts, threshold targeting |
| `__init__.py` | 35 | Barrel export |

`test_suite/` (9 files, 1990 lines): `conftest.py` + 8 concern-grouped files (chartering, dues quotes, membership cascades, education, meetings/roles, officers/coaching, contests, authorization/OCC).

### Tests emitted
- **Queue A (difficulty): 44 tests** — 22 of 24 instances covered with exactly 2 tests each.
- **Queue B (corner): 35 tests** — every non-stub instance covered once; the 4 `excluded_because:` stubs were verified to resolve and were not translated.
- **Total 79.** Audit confirms every docstring ends with exactly one resolving `Design:` tag, and every quoted ≥8-word citation greps PRD.md verbatim after whitespace normalization (16 citations were rewritten to the true sentence boundary).

### Instances skipped (2, both queue A)
- `Difficulty/dual_variant_calc/club_score_live_variant_diverges_from_cycle_close_variant` — the asserted literals (close = 60, live = 2) depend on whether rows created at wall-clock time fall inside the supplied `cycle_closed_at`/`cycle_opened_at` window. PRD pins neither the server's clock model nor the row-creation timestamps, so a faithful PRD-only implementer can land on a different value. No coverage/derivability.
- `Difficulty/cross_entity_state_dependency/role_assignment_requires_meeting_still_scheduled` — PRD §2.10's status-check list names dues renewal, refund, close, evaluation, review, release, election, training and visit completion; role-assignment *creation* is not among them and §3.6 states no SCHEDULED requirement for it. `ERR_INVALID_STATE` on that path is not uniquely derivable. (The sibling corner instance `release_of_released_assignment_returns_invalid_state` **is** derivable — release requires `ASSIGNED` — and was emitted.)

### Helper-layer decisions
- **Fixture fidelity**: every helper builds state through declared endpoints only; nothing assumes seeded data. Setup calls use `get_success_data` so a broken precondition reads "Setup step failed: ERR_X" rather than a confusing assertion failure.
- **Shared identity**: all `ClubOfficer`/`Member`/`DistrictDirector` calls use `make_*_headers(<real entity id>)`. No test uses a shared role constant for an ownership-gated call. Fixtures re-read parent versions (`club_version`, `path_version`, `meeting_version`) before every OCC-gated write, because the setup chains mutate parents repeatedly.
- **Create status**: creates assert 201 explicitly, both in the fixture layer (8 sites) and in tests.
- **Two literal re-derivations** (design index contradicted the PRD formula, so the PRD value was used, per "re-derive contradicting literals"):
  - `dcp_points_nested_minmax_over_four_inputs`: the fixture *must* contain a HELD meeting (elections require it), so `meetings_held_this_cycle` is 1, giving score **82** (30+25+15+2+10), not the design's 80. Points (7) and tier (SELECT_DISTINGUISHED) match the design.
  - `return_review_reverts_level_and_recomputes_club_score`: 12 → 17 confirmed correct, but only if the club has exactly one dues-paid member; the education fixture was changed so the evaluator is an **unpaid** member (evaluation has no membership-status gate), keeping `paid_member_count == 1`. That assertion is now pinned explicitly in the test.
- Where a design literal was ambiguous rather than wrong, the untestable bullet was dropped instead of weakened: `club_create_applies_defaults_and_system_fields` omits `version == 1` (PRD says "starts at its creation value" without naming it), and `organizing_meeting_required_before_charter` asserts the named error but not the sub-ordering against the roster error.

### Orchestrator audit (not part of the subagent report)

Independently ran `python3 -m pytest test_suite --collect-only -q` → **79 tests collected in 0.39s**, no import/collection errors, confirming the `test_helpers` package graph is intact (not merely that each file compiles). File line counts on disk match the report exactly (2026 + 1990 = 4016 total).

**Latent Step 7 risks carried forward:** the `dcp_points_nested_minmax_over_four_inputs` re-derivation (82 vs the design index's 80) is the highest-risk item in this task — the score formula's `meetings_held_this_cycle` component is only reachable with a HELD meeting, and Step 6's implementer reads the SCAFFOLD's own worked example, which may still say 80. If that test fails at Step 7, the adjudication must come from the PRD formula, not from either worked example.

## Step 6: Generate Implementation — 2026-10-01T00:00:00.000Z

The implementation is complete and verified. All 47 declared endpoints have handlers, `start.sh` boots cleanly with a wiped store, and four smoke suites (covering CRUD, all 13 state machines, the pinned calculations, cascade discipline, validation precedence and error paths) pass with zero failures.

### Files written (`workspace/implementation/`)

| File | Lines |
|---|---|
| `app.py` | 72 |
| `auth.py` | 135 |
| `calc.py` | 286 |
| `db.py` | 229 |
| `errors.py` | 95 |
| `recompute.py` | 555 |
| `response.py` | 61 |
| `routes_clubs.py` | 244 |
| `routes_contests.py` | 333 |
| `routes_education.py` | 377 |
| `routes_meetings.py` | 345 |
| `routes_members.py` | 293 |
| `routes_officers.py` | 206 |
| `routes_visits.py` | 119 |
| `serializers.py` | 176 |
| `start.sh` | 11 (executable) |
| `requirements.txt` | 1 |
| **Total** | **3538** |

**47 endpoint handlers** — 22 GET + 25 POST, matching the scaffold §1.5 table exactly.

### Verification performed
- All 47 routes registered (checked against the URL map); no seeding (grep-verified); no `float` in any money path (all `Decimal` + `ROUND_HALF_UP`); hidden bookkeeping keys (`_judges`, `_paid_history`) never serialized.
- Pinned rounding confirmed: `club_dues_cents=2999` + first-time member → **10062** (per-line), not 10061.
- Booted the real `bash start.sh` on `$PORT`, exercised it over HTTP, confirmed **state is wiped across a restart** (clubs/memberships both 0 after re-launch).

### PRD ambiguities adjudicated
1. **`good_standing_score` at club creation** — PRD §3.1 and the scaffold both say 0, but §2.7's formula yields 2 (the `cycle_open_standing == GOOD` admin point). Resolution: creation *initializes* the counters to 0 without running the formula; every later mutation recomputes normally. Satisfies both texts.
2. **Version-bump count** — §2.4 makes recomputation a mutation, while some scaffold side-effect lists only name the explicit bump. Rule applied: **each mutated resource gets exactly one bump per request**, so recompute-and-explicit-bump never double-counts (e.g. meeting create bumps the club once; close bumps meeting + each resolved assignment + club once).
3. **Cycle-close counters** — §2.7 says the closing cycle's points are "frozen … until the next close", so the club is *not* recomputed against the newly opened cycle at the end of a close.
4. **Post-close cascades** — the scaffold's Club transitions omit some Membership side effects; I applied the Membership state machine's own ACTIVE→LAPSED effects (dues→`OVERDUE`, paths suspended, entries DQ'd, terms vacated) to the suspension and revocation cascades. This is what makes `ERR_CLUB_NOT_CHARTERED` reachable on renewal.
5. **Terminal-state errors** — PRD §2.10 enumerates exactly which operations carry the priority-6 state check; advancing a `COMPLETED` path and completing a `COMPLETED` contest are *not* among them, so they fall through to priority 11 (`ERR_LEVEL_REQUIREMENTS_NOT_MET`) and the empty-candidate rule (`ERR_NO_JUDGED_ENTRIES`) respectively.
6. **Reinstatement is unreachable** — its gates (score ≥ 60 while suspended, renewals refused at a suspended club) cannot be satisfied simultaneously; implemented literally, refusing with `ERR_CHARTER_MINIMUM_NOT_MET`.
7. **Coaching queue is structurally empty** — close-cycle flags every non-`GOOD` club, and the queue only admits `coaching_status == NONE`; implemented literally, so `ERR_NO_COACHING_CANDIDATES` is the reachable outcome.
8. **`contest_participation_count`** — counted per the field description (entries this club entered into CLUB-level contests, status not filtered); note the club is *not* recomputed on entry creation (the scaffold only lists `Contest.entry_count` there), only on contest completion.
9. **`new_member_count_this_cycle`** — "first paid cycle" isn't a stored field, so it is derived as `dues_paid_through_cycle - consecutive_cycles_paid + 1`.
10. **Payload structure precedes auth** — PRD §2.10 states `ERR_INVALID_REQUEST` fires "before any business rule is consulted" and that auth is the first check "once the payload is well formed".
11. **Evaluation requires an evaluator** — a `LEADERSHIP`/`EVALUATION` completion logged without `evaluator_member_id` can never be evaluated (the evaluator must be set and equal the acting member, and self-evaluation is refused). Implemented literally.

### Orchestrator audit (not part of the subagent report)

Verified on disk: all 17 files present, line counts byte-matching the report (3538 total); `start.sh` is executable (`-rwxrwxr-x`) and correctly `exec`s the app; `app.py` reads `$PORT`, binds `0.0.0.0`, runs foreground. Route registration counted from source: **22 `@bp.get` + 25 `@bp.post` = 47**, exactly the scaffold's declared endpoint count. No-seeding grep returned only docstring prose, no live seeding code.

Independent boot smoke test on a self-allocated free port (killed only my own PID): `/health` → 200; unauthenticated `GET /toastmasters/clubs` → 401 `ERR_UNAUTHENTICATED`; malformed club create → 400 `ERR_INVALID_REQUEST` naming the exact missing field. Server boots clean from a fresh process.

**Latent Step 7 risks carried forward — adjudications 6 and 7 are the most dangerous.** Both assert that a PRD-described capability is *structurally unreachable* ("reinstatement is unreachable", "coaching queue is structurally empty"). That is the classic signature of an implementation that has silently dropped a PRD-required path rather than of a PRD that genuinely describes dead functionality. Adjudication 7 directly contradicts an existing test (`test_coaching_queue_ranks_the_weaker_club_first`, `test_06_officers_and_coaching.py`), so at least one of the two is wrong and the fix loop must adjudicate it against PRD §3.9 prose. Adjudication 1 (`good_standing_score` 0-at-creation vs formula-2) is a genuine PRD tension the implementer resolved by fiat and is the second-most-likely Step 7 flashpoint.

## Step 7: Run Tests and Iterate — 2026-10-01T00:00:00.000Z

All 8 parallel rounds are green (78/78, zero failures, zero skips) and the sweep is valid — no source file was touched after the last write (newest source mtime 13:08:37 UTC vs. results written 13:11:57 UTC).

### Summary

**Iterations run:** 2 (initial 8-round sweep → 6 stable failures; fix round → 8/8 rounds × 78/78 passed).

**Tests deleted (1)**
- `test_coaching_queue_ranks_the_weaker_club_first` — `test_suite/test_06_officers_and_coaching.py`. Not PRD-silence but direct contradiction: §3.9 states "The queue's candidate set is the clubs whose `good_standing` is `PROBATION` or `NOT_IN_GOOD_STANDING` and whose `coaching_status` is still `NONE` — a club already flagged … has left the queue", yet the test asserts a 2-club queue whose members have `coaching_status == "FLAGGED"`. The two assertions are mutually unsatisfiable: §3.2 step five flags every club whose newly derived posture is `PROBATION`/`NOT_IN_GOOD_STANDING` while `coaching_status` is `NONE`, and §2.6 permits posture to be re-derived only at close or charter (forced `GOOD`) — so no club can ever be a candidate. The implementation's "structurally empty" reading is correct; scaffold instance `Corner/endpoints/club_coaching_queue_ranks_struggling_clubs_first` drove the bad test. The sibling empty-queue test is kept and passes.

**Fixes applied to `test_suite/` (no `test_helpers/` changes were needed)**
- `test_01_club_chartering.py::test_revoked_club_refuses_dues_renewal` — close stamped at `2027-01-01T00:00:00Z` instead of `FIRST_CYCLE_CLOSE_AT` (`2026-10-01T00:00Z`, which precedes the wall-clock `created_at` of the fixture rows, so §2.7's close variant "counts only rows created at or before `cycle_closed_at`" scored 2 not 36); the "invoice untouched" assertion now compares against the pre-request `dues_status`, because §2.11 ("A club that is suspended or revoked lapses its memberships") legitimately moves it to `OVERDUE`.
- `test_04_education_and_completions.py::test_return_review_recomputes_the_club_good_standing_score` — posture assertion `NOT_IN_GOOD_STANDING` → `GOOD`; §2.6: "Outside those two situations a club keeps whatever posture it was last assigned, even while its score changes underneath it." (§2.6 quote added to the docstring.)
- `test_07_contests.py::test_entry_is_refused_once_the_contest_has_started` — `entry_count` 1 → 2; the fixture builds two live entries (leftover from the design recipe's one-entry setup) and §3.8's recomputed count is 2 before and after the refused entry.

**Fixes applied to `workspace/implementation/recompute.py`**
- `cycle_window(..., cycle_scoped=False)` now used by `paid_member_count`, `total_member_count`, `new_member_count`, `officer_trained_count`. §2.6 defines these roster counters with no creation window and §2.7 says the live variant "counts every current row"; the shared `cycle_opened_at` floor was zeroing the paid roster once the cycle index advanced (reinstatement test: `paid_member_count` stayed 0 after a successful renewal). Activity counters (`meetings_held_this_cycle`, `approved_level_completions_this_cycle`, `contest_participation_count`, DCP education points) keep the cycle window.
- `disqualify_entry` now recomputes its contest's `entry_count`/`judged_entry_count`. §3.8: "A `DISQUALIFIED` entry stops counting toward the contest's `entry_count` and `judged_entry_count`, both of which are recomputed" — the cascade paths (§2.11 lapse, posture fall) disqualified entries without recounting the contest.

**Hazard adjudications (all settled from PRD prose, not from either side's assertion)**
1. Coaching queue — PRD §3.9 excludes flagged clubs; test deleted (above).
2. Reinstatement — reachable: a `CHARTERED` club's cycle close lapses unpaid memberships while the club stays `CHARTERED`, leaving an `OVERDUE` invoice that §3.3's reinstatement route accepts. The test was right; the implementation's roster-counter bug was the cause.
3. `dcp_points_nested_minmax_over_four_inputs` / score 82 — correct as generated (30+25+15+2+10 with one HELD meeting); passed in all 8 rounds, no change.
4. `ERR_CLUB_NOT_CHARTERED`/`ERR_CLUB_REVOKED` status — no test asserts the status directly; `test_helpers/api_errors.py` maps both to 422 per PRD §5 and the implementation returns 422 (verified live).
5. Creates return 201 — unaffected, all create assertions green.

### Orchestrator audit (not part of the subagent report)

Verified the sweep evidence survives on disk: `results.1.json` … `results.8.json` all present, each reporting `passed=78 total=78 failed=0 skipped=0`. Test count 79 → 78 reflects exactly the one documented deletion. Source-mtime check confirms no `implementation/` write after the sweep (newest source 13:07:36 vs results 13:11), so the green result is not invalidated by a post-sweep edit.

**Flag for Step 8 — test-side edits dominate this round** (1 deletion + 3 `test_suite/` fixes vs only 2 `implementation/` fixes). A green sweep proves tests match code, not PRD vs code. The three `test_suite/` fixes are each a site where PRD prose was *ambiguous enough that the test-generator read it wrong*, which is precisely the class of silence Step 8 exists to close — so all three belong in the `<step_7_diff>` focus list, not just the two `recompute.py` fixes.

**Sibling paths left unasserted** (name them for Step 8 even though no test covers them): the same `cycle_window(cycle_scoped=...)` distinction governs every roster-vs-activity counter in `recompute.py` — `officer_trained_count` was fixed, but any sibling counter sharing that helper must be described consistently; and `disqualify_entry`'s recount now runs from the cascade paths, so the §3.8 prose about `entry_count`/`judged_entry_count` must not be narrowed to the direct-DQ path only.

## Step 8: Finalize PRD — 2026-10-01T00:00:00.000Z

`PRD_FINALIZED.md` is written. Five in-place edits, all traced to `<step_7_diff>` items; line count unchanged (372 → 372), +1,348 bytes (+1.85%).

### Summary

**Line counts:** `PRD.md` 372 lines / 73,067 B → `PRD_FINALIZED.md` 372 lines / 74,425 B (+1.85% bytes, 0% line delta).

**Changes (one bullet per edit)**

- **§2.4 (Optimistic Concurrency Control / record identity)** — *insert* — added "A resource's `version` is bumped at most once by any single request: when one request both recomputes a resource's derived fields and writes to that same resource, those two count as one modification, not two." (step_7 flag (b)) — `implementation/recompute.py:336-339` (`touch_club` = recompute + one bump), `implementation/routes_members.py:257-258`, `implementation/routes_clubs.py:224-225`, `implementation/routes_meetings.py:199-201`.
- **§2.6 (Charter Standing and Posture Reconciliation)** — *insert* — pinned that `paid_member_count`, `total_member_count`, `new_member_count_this_cycle`, `officer_trained_count` carry no creation window (a row created before `cycle_opened_at` still counts; only §2.7's `cycle_closed_at` cap excludes), while `meetings_held_this_cycle`, `approved_level_completions_this_cycle`, `contest_participation_count` are the ones anchored to the cycle window. (step_7 implementation fix 1) — `implementation/recompute.py:67-91, 95-186`.
- **§2.11 (Cascade Discipline)** — *revise* — "A club that is suspended or revoked lapses its memberships and vacates its officers; every membership it lapses this way has its `dues_status` set to `OVERDUE`, whatever that field held before." (step_7 `test_01` fix: the "invoice untouched" assertion had to be re-based because the revocation cascade moves a `PAID` invoice to `OVERDUE`) — `implementation/recompute.py:430-457, 509-519`.
- **§3.1 (Petitioning and Chartering)** — *revise* — replaced the incorrect justification ("every weighted component contributes nothing") with the actual creation behavior: `good_standing_score` 0, `dcp_recognition_points` 0, `dcp_tier` `NONE`, written as zero rather than run through the §2.7 formulas. (step_7 flag (a); §2.7's formula would otherwise yield 2/1) — `implementation/routes_clubs.py:121-157`.
- **§3.2 (Cycle Close)** — *insert* — "The counters step two recomputed are the ones the club reports when the close returns; the close does not recompute the club a second time against the cycle it has just opened." (step_7 flag (c)) — `implementation/recompute.py:486-556` (recompute at step 2 only, explicit comment at 553-555), `implementation/routes_clubs.py:241-244`.

**Per-edit pre-edit search log**

1. **§2.4 version bump** — (a) subject: version-bump counting when a recompute and an explicit write coincide. (b) Enumerated every `db.touch` callsite (grep across all of `implementation/*.py`: `recompute.py:339,352,360,368,404,412,421,452,532,541`; `routes_clubs.py:222,225,243`; `routes_contests.py:131,137,167,182,268,330,332`; `routes_education.py:116,170,261,292,353,376`; `routes_meetings.py:133,168,170,193,201,315,343,344`; `routes_members.py:258,292`; `routes_officers.py:169,205`; `routes_visits.py:81,112,116,118`) and checked each request for a double-touch of one object — `close_cycle` (lapse vs. step-4 membership; `vacate_terms_for_membership` vs. `complete_terms_below_index`; idempotent `disqualify_entry`), `charter_club`, `renew`, `refund`, `close_meeting`, `review_completion`, `record_ballot`, `complete_contest` (club dedup via `touched_clubs`), `complete_visit`. (c) No wording adjustment; "at most once" is one-directional and does not claim that every recomputed resource is bumped (which is false for `recompute_membership` in review, `recompute_contest` in `disqualify_entry`), so it stays consistent with those paths too.
2. **§2.6 roster vs. activity window** — (a) subject: which club counters are filtered by creation time. (b) Read `cycle_window` and all nine callers (`paid_member_count`, `total_member_count`, `new_member_count`, `officer_trained_count`, `meetings_held_count`, `approved_level_completions_count`, `contest_participation_count`, `dcp_education_points`, `recompute_membership`), plus downstream consumers (`calc.py:126-185` score/DCP formulas, `calc.py:277-286` queue ranking, `routes_clubs.py:180,194` charter gate, `close_cycle`'s `cutoff=closed_at` at `recompute.py:486`). (c) Scoped the activity half with "among them" so the sentence cannot be read as an exhaustive claim over all counters in the system — the membership-level `speeches_delivered_this_cycle` / `roles_completed_this_cycle` also use the cycle window but are not in this paragraph's subject.
3. **§2.11 club-lapse invoice** — (a) subject: invoice state of memberships lapsed by club suspension/revocation. (b) Enumerated all `lapse_membership` callsites (`recompute.py:483` sweep — no force; `:513` revocation — all memberships, forced; `:519` suspension — `ACTIVE` memberships only, forced) and confirmed no other code path writes `charter_status` to `SUSPENDED`/`REVOKED` (`routes_clubs.py:160-226` only sets `CHARTERED`). (c) Wrote the claim over "every membership it lapses this way" rather than "every membership of the club", so it does not mis-describe a suspended club's `PENDING` memberships (not lapsed) or an already-`LAPSED` membership at a revoked club (not re-lapsed, though its invoice is also forced `OVERDUE` — left under-determined deliberately).
4. **§3.1 creation counters** — (a) subject: derived counters on a newly created club. (b) Enumerated club-creation paths (`routes_clubs.py:90-157`, the only writer of `db.CLUBS`; `db.py:86-97` `create` stamps only `id/created_at/updated_at/version`; no seeding at boot) and confirmed no `recompute_club` call on the creation path. (c) Scoped the sentence to "a newly created club" so it cannot be read as a claim about charter/close/`touch_club` paths, which do run the formulas.
5. **§3.2 no post-close recompute** — (a) subject: the club's reported counters after a close returns. (b) Traced `close_cycle` end-to-end (`recompute.py:471-556`: step-2 `recompute_club(..., cutoff=closed_at)` at 486; step 4 index/open/close writes at 522-525; step 5 at 535-551; no later recompute) and the route (`routes_clubs.py:241-244`, only `db.touch`). (c) No adjustment; the sentence is scoped to the close operation and matches the frozen values the sweep/tests observe (e.g. `paid_member_count` 20 and score 82 after a close).

**Items checked and deliberately NOT edited** (PRD already determines the behavior; the Step 7 change was a test-side or impl-side realignment): coaching-queue deletion (§3.9's `coaching_status == NONE` candidate set and `ERR_NO_COACHING_CANDIDATES` already match `routes_clubs.py:22-51`); `test_01`'s close-timestamp fixture bug (§2.7's `cycle_closed_at` cap already matches `cycle_window`); `test_04`'s posture assertion (§2.6 already pins posture re-derivation to close/charter only); `test_07`'s `entry_count` 2 (§3.8 already defines `entry_count` as non-`DISQUALIFIED` entries); the `disqualify_entry` recount (§3.8 already states a `DISQUALIFIED` entry stops counting toward both counters, which covers the cascade paths — the inserted §3.2/§2.6 wording does not narrow it); `ERR_CLUB_NOT_CHARTERED`/`ERR_CLUB_REVOKED` 422 and creates-return-201 (§5 and §4 already match `errors.py:19-50` and the 201 returns); the DCP 82/7 fixtures (§2.7's formulas already yield them).

**Out-of-scope divergences noticed but left alone** (not traceable to a `<step_7_diff>` item, per the HARD SCOPE rule): `judged_entry_count` counts `ADVANCED`/`ELIMINATED` entries after a contest completes (`recompute.py:290-295`) while §3.8 only says it is "recomputed"; `contest_participation_count` counts `DISQUALIFIED` entries; several recomputes (e.g. `recompute_membership` in `review_completion`, `recompute_contest` inside `disqualify_entry`) mutate a resource without bumping its `version`, which §2.4/§2.11's blanket wording would require.

### Orchestrator audit (not part of the subagent report)

Verified on disk: `PRD_FINALIZED.md` 372 lines / 74,425 bytes vs `PRD.md` 372 lines / 73,067 bytes — +1,358 bytes, line count unchanged, consistent with five in-place insert/revise edits and no new sections. Spot-checked the diff: all five edits land where reported and are additive/scoped rather than wholesale rewrites. `find implementation -newermt 13:11:57` (the sweep timestamp) returned **nothing**, so the Step 7 sweep remains valid through Step 8 — Step 8 touched only the PRD.

**Three out-of-scope divergences the subagent correctly refused to patch are now the Step 9 work list** — they are genuine PRD-vs-impl mismatches that no Step 7 test ever surfaced (exactly the gap Step 9 exists to close): (i) `judged_entry_count` semantics after contest completion, (ii) `contest_participation_count` including `DISQUALIFIED` entries, and (iii) recomputes that mutate a resource without bumping `version`, which the newly inserted §2.4 sentence does not license (it bounds bumps from above, it does not permit their absence). Item (iii) is the highest-risk of the three because Step 8 *just* wrote prose adjacent to it.

## Step 9: Complete PRD — 2026-10-01T00:00:00.000Z

`PRD_COMPLETED.md` is written. All 22 edits are single-line in-paragraph replacements — no new sections, no table changes, and the file is still 372 lines.

### Summary

**Source:** `PRD_FINALIZED.md` (372 lines / 74,425 chars) → `PRD_COMPLETED.md` (372 lines / 78,672 chars), **+4,247 chars**.
**Counts:** 26 logical changes across 22 hunks — **15 ambiguity-pins**, **11 mismatch-revisions**. All 78 tests in `implementation/results.*.json` are green, so none of these were test-surfaced.

### Changes

- §2.3 — revise — ambiguity — coaching-queue emptiness is decided *before* its `limit` is validated, so an empty queue answers `ERR_NO_COACHING_CANDIDATES` whatever `limit` says — `routes_clubs.py:34-46`
- §2.4 — revise — **mismatch** — replaced "any recomputation is a mutation that bumps" with the actual rule: a by-product counter refresh on a non-addressed resource (member, path, membership, contest) writes in place without a bump; the club is the one resource always bumped — `recompute.py:364-377`, `routes_education.py:351,374`, `routes_meetings.py:196`, `routes_officers.py:168,201`, `routes_contests.py:331` *(known item iii)*
- §2.6 — revise — **mismatch** — "recomputed on every membership, officer, education, meeting and cycle mutation" replaced with the nine occasions that actually refresh the club — `routes_clubs.py:224,242`; `routes_members.py:160,197,257,291`; `routes_education.py:169,352,375`; `routes_meetings.py:133,200`; `routes_officers.py:204`; `routes_contests.py:179`
- §2.6 — insert — ambiguity — `new_member_count_this_cycle`'s "first paid cycle" is derived as `dues_paid_through_cycle − consecutive_cycles_paid + 1`, skipping negative/consecutive<1 rows — `recompute.py:118-134`
- §2.6 — insert — ambiguity — `contest_participation_count` counts an entry whatever its status, so `DISQUALIFIED` entries still count — `recompute.py:177-186` *(known item ii)*
- §2.7 — revise — **mismatch** — live recognition points are recomputed on the §2.6 occasions only; a fresh club-level contest entry is reflected at the next recompute, not in that response — `routes_contests.py:267-268`
- §2.10 — insert — ambiguity — where an ownership clause reads a field of the path resource, the load precedes it, so a missing resource yields `ERR_NOT_FOUND` before `ERR_UNAUTHORIZED` — `routes_members.py:217-218`, `routes_education.py:131-132,276-278,312-314`, `routes_meetings.py:330-332`, `routes_officers.py:115-116,184-186`, `routes_visits.py:96-98`
- §2.11 — revise — **mismatch** — the contest whose `entry_count`/`judged_entry_count` a disqualification refreshes is the one cascade resource updated without a version bump — `recompute.py:374-376` *(known item iii)*
- §3.1 — revise — **mismatch** — the organizing-meeting fields are supplied on the petition itself (no other endpoint writes them), null/0 when omitted — `routes_clubs.py:107-112,134`
- §3.1 — insert — ambiguity — only `ORGANIZING`/`SUSPENDED` admits a charter; `CHARTERED`/`REVOKED` → `ERR_INVALID_STATE` before any prerequisite — `routes_clubs.py:168-169`
- §3.1 — insert — ambiguity — a reinstatement short of either bound → `ERR_CHARTER_MINIMUM_NOT_MET` — `routes_clubs.py:194-200`
- §3.2 — revise — **mismatch** — the sweep lapses a membership not already `LAPSED`, a `PENDING` one included (not only `ACTIVE`) — `recompute.py:448-450`
- §3.2 — revise — **mismatch** — removed the 500-cent late fee (no such constant exists); the penalty is the 5 % late line of the next quote — `calc.py:109-114`
- §3.3 — insert — ambiguity — bulk tolerance is confined to email: missing `join_date` → request timestamp, non-boolean `first_time_member` → false, unparseable `join_date` fails the whole request — `routes_members.py:186-195`
- §3.3 — insert — ambiguity — `pay_dues_immediately` also sets `consecutive_cycles_paid` 1 and takes the quote as it stood before payment — `routes_members.py:84-89`
- §3.3 — revise — **mismatch** — the renewal gate is the invoice status alone (no charter-status condition on the `PENDING` route); `ACTIVE` renews unless `PAID`/`VOID`, any other status → `ERR_INVALID_STATE` — `routes_members.py:230-237`
- §3.4 — revise — **mismatch** — `LEVEL_4` needs 1 speech + **1** project, not 2 — `calc.py:49-55`
- §3.4 — insert — ambiguity — a path already at `COMPLETED` holds no level completions and fails the requirement check, not a state check — `routes_education.py:142-148`
- §3.5 — insert — ambiguity — both approval content-requirement failures → `ERR_LEVEL_REQUIREMENTS_NOT_MET` — `routes_education.py:329-342`
- §3.6 — insert — ambiguity — `duration_minutes` must be positive when supplied — `routes_meetings.py:86-87`
- §3.7 — insert — ambiguity — a missing/unpaid nominee shares `ERR_ELECTION_QUORUM_NOT_MET` — `routes_officers.py:150-161`
- §3.7 — revise — **mismatch** — a lapse vacates `NOMINATED`, `ELECTED` and `TRAINED` terms, not `ELECTED` only — `recompute.py:399-405`
- §3.8 — revise — **mismatch** — `club_id`/`area_code` are not otherwise level-constrained; supplied values are stored as given — `routes_contests.py:69-76`
- §3.8 — insert — ambiguity — a ballot on an entry that has left `ENTERED` → `ERR_INVALID_STATE` — `routes_contests.py:317-319`
- §3.8 — insert — ambiguity — `entry_count` = non-`DISQUALIFIED` entries; `judged_entry_count` = `JUDGED`/`ADVANCED`/`ELIMINATED` — `recompute.py:290-295` *(known item i)*
- §3.9 — revise — ambiguity — the queue returns at most 100 candidates however large the `limit` — `routes_clubs.py:47`

### Notes on the three pre-identified items
All three verified as genuine and patched: (i) `judged_entry_count` now pinned to `JUDGED`/`ADVANCED`/`ELIMINATED`; (ii) `contest_participation_count` now explicitly includes `DISQUALIFIED`; (iii) §2.4 and §2.11 rewritten to license the missing bumps, with the affected call sites named inline. Beyond them, the largest previously-unnoticed divergences were the `LEVEL_4` requirement table (PRD 1+2, impl 1+1), the phantom 500-cent late fee, and the §3.2 sweep lapsing `PENDING` memberships.

### Orchestrator audit (not part of the subagent report)

Step 9's 11 "mismatch-revisions" are exactly the shape that can silently paper over implementation bugs rather than PRD ambiguities — rewriting the contract to match a defective implementation. I therefore spot-checked the two highest-risk items against SCAFFOLD.yaml, which is the design source of truth and which Step 9 was forbidden to read.

1. **`LEVEL_4` (1+1 vs 1+2) — Step 9 was RIGHT.** SCAFFOLD.yaml's `EducationPath.level` state machine gives the `LEVEL_4 → LEVEL_5` precondition as `approved_speeches_at_level >= 1 and approved_projects_at_level >= 1`, and `implementation/calc.py:49-55` has `"LEVEL_4": (1, 1)` — impl and scaffold agree. The original PRD §3.4 had collapsed `LEVEL_4` into the `LEVEL_2`/`LEVEL_3` group ("To leave `LEVEL_2`, `LEVEL_3` or `LEVEL_4` it needs at least 1 approved speech and at least 2 approved projects"). That was a genuine **doc-generator transcription error**, and the implementation had silently followed the scaffold rather than the PRD. Step 9 corrected the PRD to the scaffold's (and impl's) value. This is a real defect that Step 7's tests never caught, because no test exercises `LEVEL_4 → LEVEL_5`.

2. **500-cent late fee — Step 9 was RIGHT, but for a subtler reason.** `late_fee_cents` occurs **exactly once** in the entire 1941-line scaffold — in the Membership `ISSUED → OVERDUE` transition side effect ("late_fee_cents = 500 is added to the next quote"). It is **not** a declared field on the Membership entity (0 occurrences in that entity block), and the `dues_quote` calculation's `constants:` block has no such constant (its only late term is `LATE_FEE_RATE: 0.05`, applied as `late_line`). So the scaffold's 500 was a **dangling reference that could never be implemented as written** — there is no field to store it and no constant to compute it. The PRD generator faithfully reproduced both halves; the implementer followed the authoritative, computable formula. Step 9 removed the orphan sentence. Correct reconciliation, not a covered-up gap.

Both checks therefore clear Step 9 of the "rewrite the contract to match a broken implementation" failure mode on the two items where that risk was concentrated. The remaining nine mismatch-revisions were reviewed at the level of their reported impl citations and are consistent with implementation behaviour rather than with a PRD rule the implementation contradicts.

## Step 10: Final Stability Sweep (orchestrator-run) — 2026-10-01T00:00:00.000Z

Re-ran the full 8-round parallel stability sweep myself against the frozen final state, to (a) independently confirm the delivered artifact rather than trust the Step 7 hand-back, and (b) guarantee the `results.{1..8}.json` files the output contract requires are present and green after all later steps.

Command: 8 concurrent `prd-bench-local-run --isolation per-test-server --timeout 120 --test-timeout 30` rounds over `test_suite/`, each writing `workspace/implementation/results.${i}.json`.

Result: **all 8 rounds `passed=78 total=78 failed=0 skipped=0`**; a direct scan of every `tests[]` entry across all 8 files found **0 non-passing entries**. Confirmed `implementation/` source mtimes were unchanged (newest `recompute.py` 13:07:36) both before and after Steps 8–9, so the sweep validates the exact bytes being delivered.

Note: Steps 8 and 9 touched only `workspace/PRD_*.md` — no `implementation/`, `test_suite/`, or `test_helpers/` file was modified after the Step 7 sweep, so the green result is continuous from Step 7 through delivery rather than newly established at the end.

### Process-safety note

Left the host's orphaned `python3 app.py` processes alone. Inspection via `/proc/<pid>/cwd` showed they belong to **several different concurrent pipelines** (`task_3368_*`, `task_3360_*`, and this task), all reparented to PID 1 by the per-test-server isolation runner. Selectively killing even the three whose cwd is this task's `implementation/` was judged not worth the misattribution risk on a host running many pipelines, and the runner's `fcntl.flock` port registry handles allocation regardless. No `pkill`/`killall`/`pgrep | xargs kill` was used at any point in this pipeline.

### Final deliverable

All contract files present: `SCAFFOLD.yaml` (1941 lines), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1664), `SCAFFOLD_CORNER_DESIGN.yaml` (1497), `worklog.md`, `test_helpers/` (9 files), `test_suite/` (9 files, 78 tests), `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md}`, and `workspace/implementation/` (17 files, 3538 lines, 47 endpoint handlers, `start.sh` executable, `results.1..8.json` all green).
