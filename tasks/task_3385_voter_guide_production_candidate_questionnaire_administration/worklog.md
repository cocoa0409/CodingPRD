# Worklog — task_3385_voter_guide_production_candidate_questionnaire_administration

## Step 1: Create Task Directory — 2026-10-01T12:50:00.000Z

Task directory `./tasks/task_3385_voter_guide_production_candidate_questionnaire_administration/` was pre-allocated by the command arguments (index 3385 assigned externally, not computed). Verified it exists with an empty `workspace/` subdirectory inside. No new directory created.

## Step 2: Generate Scaffold — 2026-10-01T15:32:00.000Z

All three scaffold artifacts are generated, parse clean, and pass `scaffold_lint.py` with zero violations. No sibling task directories were read at any point.

**Artifacts** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3385_voter_guide_production_candidate_questionnaire_administration/`):
- `SCAFFOLD.yaml` (1067 lines) — §1.0–§1.7 only: 14 entities, 12 state machines, 2 OCC concurrency rules, 7 calculations, 39 ordered validations, 57 endpoints, 40 errors, 7 roles
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (813 lines) — single key `scaffold_difficulty_design`, 18 instances, exactly 2 per §0.5 rule
- `SCAFFOLD_CORNER_DESIGN.yaml` (1494 lines) — single key `scaffold_corner_design`, 56 active corner instances + 15 `excluded_because` stubs

**Final lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(57 endpoints, 14 entities, 18 §1.8 + 56 §1.9 instances, 1120 calls scanned, 0 violations.)

**Design shape** ("harder than expert" via coupling density, not volume):
- Archetype: compliance/audit + workflow orchestration; segregation-of-duties role model (drafter ≠ reviewer, moderator ≠ own-question selector), 5 entity-backed roles + 2 opaque, logical clock with the mandated `2026-09-01T00:00:00Z` default.
- Dual-variant calcs: STRICT/LENIENT word counting (same text → 8 vs 7) and FK/SMOG readability (same text → 2.65 vs 8.84, straddling the 8.0 accessibility gate); all numeric asserts pre-computed by executing the formulas (`banana` fixture, 21-word page-estimate fixture, allocation tie-break 600/400/0).
- Depth-3 cascade (incident → suspension → measure quarantine → contest reversion, which also stale-pins edition snapshots) plus depth-2 withdraw cascade and amend-reinvite cascade.
- Priority pairs: state-beats-temporal on closed-questionnaire submit, safety-beats-constraint on edition READY.
- Overlap rules with genuinely different geometry: half-open jurisdiction forum intervals vs 24h moderator buffer gap; invariants on page-estimate conservation (READY⇄ASSEMBLING) and response-shell cardinality (withdraw/refile).

**Two design corrections made mid-build** (worth knowing downstream): (1) neutrality approval requires 2 distinct NEUTRAL reviews per round — a single review ends the round, which would have made `ERR_DUPLICATE_REVIEW_THIS_ROUND` unreachable dead code; (2) `ERR_QUESTIONNAIRE_NOT_PINNED` and `ERR_ONLY_DRAFTER_MAY_REVISE` were added to the catalog after grounds-resolution checks caught them referenced-but-undeclared. One endpoint-count note: 57 endpoints exceeds the Expert band guideline deliberately (scenario spans 8 workflow areas + 12 mandatory FK reverse-GETs); every FK passes the reverse-reachability check.

Orchestrator verification: all three files exist, parse as YAML with expected top-level keys (`scenario/...` for SCAFFOLD, single design keys for the two index files), and grep confirms 308 domain-term matches (voter/candidate/questionnaire/ballot/forum/chapter) — no foreign-domain contamination.

## Step 3: Copy Shared Files — 2026-10-01T15:33:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-01T15:45:00.000Z

All checks pass. The PRD is complete and verified.

**Generated:** `/home/ubuntu/github/CodingPRD/tasks/task_3385_voter_guide_production_candidate_questionnaire_administration/workspace/PRD.md` (305 lines, written in 6 sequential chunks — one `Write` + five quoted-heredoc appends, so no backtick execution; the withheld `SCAFFOLD_DIFFICULTY_DESIGN.yaml` / `SCAFFOLD_CORNER_DESIGN.yaml` were never opened).

**Structure:** §1 Introduction (2 paragraphs, business-context angle) → §2 with 10 domain-derived subsections (RBAC with per-role `identity:` translations, verbatim §2.2, pagination 10/1/100/0 with `created_at`-ascending sort, logical clock with 2026-09-01T00:00:00Z startup default, resource identity/version semantics, OCC, validation priority ladder, left-to-right path resolution, word-counting/rounding conventions, nonpartisanship safeguards) → §3 with 9 subsections organized along the production pipeline (cycle/registry → filings → questionnaire → responses/sweep → measures/reviews → editions/allocation → forums → incident cascade → publication) → §4 (57-row, 4-column endpoint table) → §5 (40-row, 2-column error catalogue). File ends at §5 with no audit footer.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 90 required, 90 present, 0 missing
- endpoints[].request_body: 54 required, 54 present, 0 missing
- endpoints[].query_params + path_params: 1 required, 1 present, 0 missing
- nested payload keys (position_index, prompt_text, word_limit_override, text,
  channel_code, requested, priority_tier, allocated): 8 required, 8 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 38 checked, 38 expressed (ladder order stated in §2.7
  incl. explicit "state beats temporal" ordering on submit/resubmit), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write operation +
  expected_contest_version / expected_questionnaire_version + ERR_STALE_VERSION/412
  all named), 0 missing
- state_machines[].transitions: 50 checked, 50 fully expressed (incl. system cascades:
  verify→shell create, withdraw/disqualify→WITHDRAWN_HIDDEN, refile→INVITED,
  amend→re-invite, sweep, quarantine→contest revert, moderator-suspension cancels), 0 missing
- calculations[]: 7 checked, 7 fully expressed in reconstruction-safe prose
  (STRICT/LENIENT tokenization, FK 0.39/11.8/15.59 and SMOG 1.043/30/3.1291 formulas,
  waterfall allocation with tier/tie-break order + conservation, pinned per-contest
  rounding with the 21-word worked example, completion index, balance ratio, quorum), 0 missing
- validations[] conditions: 38 matchable to error_id in §2/§3 prose; all 40 error IDs
  mechanically confirmed present in backticks
- endpoints[].side_effects / applies_to: all expressed (validation-5's six-endpoint
  cycle-OPEN scope enumerated; all 41 state values and 75 enum values confirmed present)
- entities[].fields[] structured content: defaults (seat_count/vote_for_count 1,
  word limit 100, STRICT, advocacy_flag false), 90-day attestation, computed-field
  semantics all reconstructible
- sibling-branch symmetry: withdraw FILED-vs-VERIFIED, revise DRAFTING-vs-REMANDED,
  NEUTRAL-vs-remanding verdicts, sweep's two source states rendered with equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 531
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Additional checks:** §2.2 matches `section-2.2-response-structure.md` byte-for-byte; §4 has exactly 57 four-column rows; §5 has exactly 40 two-column rows; no fuzzy/approximating words and no pseudocode operators (`>=`, `==`, `+=`, `->`) anywhere outside code fences; no content from the withheld difficulty/corner design files.

Orchestrator verification: PRD.md is 305 lines with 101 domain-term matches and complete §1–§5 heading structure.

## Step 5: Generate Unit Tests — 2026-10-01T16:05:00.000Z

All checks pass. The suite is complete and frozen.

**Task**: task_3385_voter_guide_production_candidate_questionnaire_administration — full test infrastructure generated.

### Artifacts

**`test_helpers/`** (Stage 5a, written and frozen first, imports cleanly):
- `types.py` — 14 entity TypedDicts (all `common_fields: true`), 21 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (44 endpoints)
- `api_errors.py` — all 40 error IDs + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity shape assertions, `assert_allocation_conservation`, and `assert_instant_equals` (compares logical-clock instants after parsing, since PRD §2.5 renders timestamps with three fractional digits while design recipes spell them without — comparing instants avoids failing correct implementations on spelling)
- `factories.py`, `constants.py` (word limits 100/250, grade threshold 8.0, quorum 2, question cap 5, 24h buffer, 90-day attestation, page-estimate constants, the pinned `EXPLANATION_TEXT` with grades 2.65/8.84)
- `test_users.py` — opaque constants for LeagueAdmin/PublicUser; `make_*_headers(id)` builders for all five entity-backed roles (never the shared fallback for ownership-gated calls)
- `fixtures.py` — composite chains: `fresh_league` (clock + volunteers + OPEN cycle + jurisdiction), contest phase advancement with OCC re-reads, `build_issued_scenario`, `build_locked_candidate_contest`, `build_measure_pipeline` (through approval/lock), `build_distributed_edition`, `build_confirmed_forum`, incident helpers

**`test_suite/`** (Stage 5b): `conftest.py` + 17 test files, **92 tests** — test_01–09 translate the difficulty queue (2 tests × 18 instances), test_10–17 the corner queue by section (56 tests).

### Completion audit (AST-walked, machine-checked)
- Difficulty: 18/18 instances, each with exactly 2 tests = 36 tests
- Corner: 56/56 non-stub instances, 1 test each = 56 tests
- 15 corner stubs correctly not emitted; all 15 `excluded_because` cross-references resolve to real difficulty instances
- 0 phantom tags, 0 untagged/dual-tagged tests, 0 skip/xfail markers, 0 "scaffold" mentions
- 131/131 docstring citation fragments grep verbatim in PRD.md (5 elided quotes were caught and rewritten to complete sentences)
- `python3 -m compileall` clean on both trees; `pytest --collect-only` collects all 92 tests with no import errors

### Adjudications (no instances skipped; three recipe-level corrections, PRD-derived)
1. **`stale_snapshot_blocks_distribute_after_incident_unlock`**: the recipe's trigger has the *just-suspended* drafter call distribute — but PRD §2.1's suspension battery (`ERR_VOLUNTEER_SUSPENDED`, ladder position 10) fires before `ERR_STALE_SNAPSHOT` (position 35). The test distributes via a second, still-active editor so the snapshot rule is what surfaces.
2. **`public_user_question_sourcing_rules`**: emitted the derivable half (PublicUser + PUBLIC_SUBMISSION → 201, `author_volunteer_id` null, born SUBMITTED). The "PublicUser claiming MODERATOR_AUTHORED → 400" half is not uniquely derivable from PRD prose, so it was dropped per the two-reader rule (not weakened to a status-only check — simply not asserted).
3. **Initial-version literals**: `version == 1` assertions in two entity corners are not uniquely derivable (PRD pins "increments by exactly 1 on every mutation", not the seed value); asserted positive-int version at creation and delta +1 across a mutation instead.

All clock-dependent fixtures schedule against the PRD's logical-clock start (2026-09-01T00:00:00Z) with monotonic advances (filing deadline 2026-09-15, questionnaire due 2026-10-01); creates use explicit 201 expectations throughout.

Orchestrator spot-check: test_helpers/ has all 9 expected modules; test_suite/ has conftest.py + 17 test files; `grep` confirms 18 unique `Design: Difficulty/` tags and 56 unique `Design: Corner/` tags; `pytest --collect-only` collects exactly 92 tests with zero import errors.

## Step 6: Generate Implementation — 2026-10-01T17:55:00.000Z

Done. The implementation is complete and verified end-to-end.

## What was built

`tasks/task_3385_voter_guide_production_candidate_questionnaire_administration/workspace/implementation/` — Python + Flask, per-domain modules (no monolith):

- **`start.sh`** — guarded install (`pip` only when flask missing), `exec python3 app.py`, `$PORT` (default 10000), `0.0.0.0`, foreground
- **`app.py`** — blueprint registration + envelope-shaped error handlers (404/405 → `ERR_NOT_FOUND`, 500 → `ERR_INTERNAL`)
- **`store.py`** — in-memory dicts, empty at boot; logical clock starts at `2026-09-01T00:00:00Z`
- **`errors.py` / `respond.py` / `shape.py` / `authz.py`** — the 38-error catalog, the `meta`/`response_type`/`data` envelope (pagination fields in `meta`), band-3 body validation with the no-undeclared-fields rule, and the 7-role auth model with entity-backed capability checks (401) + role membership (403) + the suspended/lapsed battery
- **`calc.py`** — STRICT/LENIENT word counting (URL=0 under STRICT, hyphen-part splitting), FK/SMOG grades (2dp half-up, y-as-vowel runs), balance ratio (4dp, flag strictly > 0.15), completion index (1dp), per-contest nested-rounding page estimate, tiered print-copy waterfall
- **`routes/`** — 11 blueprints covering all 57 endpoints (clock, cycles, contests, filings, questionnaires, responses, measures, editions, forums, volunteers, incidents)

Key fidelity decisions, traced to PRD/scaffold: validation ladder ordering everywhere (state-beats-temporal on submissions; READY gates in 16→33→34→36 order; OCC at band 9 before the volunteer battery); version increments only where the state machine names them (e.g. questionnaire version bumps on SUBMITTED-landing submits but not on over-limit landings or sweeps; contest version untouched by refile/sweep); all counters/ratios derived on read; scoped publish-incident gate per PRD §3.9 (drafters/reviewers/moderators of the cycle); candidate resubmit on another filing's shell → 404 per the error catalog; bad `to=` values → `ERR_INVALID_STATE` per validation 6.

## Verification

- `python3 -m py_compile` clean on all 25 files
- Three self-written smoke suites (~180 checks total) run against fresh `bash start.sh` boots on dynamic ports — all pass: full lifecycle happy paths per domain, the auth ladder, OCC 412s, word-count boundary (at-limit passes, over-limit → `OVER_LIMIT_RETURNED` + resubmit), sweep/re-invite semantics, withdraw/disqualify/refile cascades, 2-reviewer approval + SoD + duplicate-round + remand/revise loop, page estimate = 8 via nested rounding, allocation waterfall conservation, both directions of the accessibility grade gate, forum overlap/24h-buffer/quorum/question-cap/own-question SoD, incident dismiss vs. substantiate with the full suspend→remand→cancel→revert cascade, `ERR_STALE_SNAPSHOT` after a revert, attestation lapse/cure, publish gates, and publish/archive happy path
- Fresh-boot default clock proven (`attestation_expires_at` = +90d from 2026-09-01 before any clock call); all timestamps emitted with 3 fractional digits, matching sibling-task conventions
- Process safety: only PIDs I started were killed (resolved via `ss -ltnp` per port); no broad kill patterns used; final state: no leftover servers, no `__pycache__`, no stray files

One judgment call to flag: for `POST /incidents`, a body-referenced `volunteer_id` that doesn't resolve returns 400 `ERR_INVALID_REQUEST` (the catalog scopes 404 to path ids and the response shell).

Orchestrator spot-check: implementation/ contains start.sh (foreground, `$PORT`-driven via app.py, guarded pip install), 13 top-level modules + routes/ with 11 blueprints; `python3 -m compileall -q .` is clean. Note: subagent's "38-error catalog" vs PRD's 40-row catalogue — Step 7's sweep will adjudicate any real gap.

## Step 7: Run Tests and Iterate — 2026-10-01T18:18:00.000Z

Clean sweep: all 8 rounds pass 92/92. The `results.*.json` files are preserved in `workspace/implementation/` as required output evidence.

**Summary**

- **Iterations run:** 2 (initial sweep: 87/92 in all 8 rounds, 5 deterministic failures; post-fix sweep: 92/92 × 8 rounds).

- **Tests deleted:** none. Every failing rule traced verbatim to PRD; all fixes were consistency repairs, no assertions weakened.

- **Fixes applied to `test_helpers/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_3385_voter_guide_production_candidate_questionnaire_administration/test_helpers/fixtures.py` — `build_issued_scenario`: rewind the logical clock to `CLOCK_START` after ctx resolution. A reused ctx carried the clock past `filing_deadline` from the prior contest's pipeline, so the next contest's filing creation violated PRD §3.2's deadline rule (fixed `test_page_estimate_rounds_per_contest_then_sums`).

- **Fixes applied to `test_suite/`:**
  - `test_06_boundary_precision.py` — `_two_contests_with_filings`: same clock rewind inside the per-contest loop (+ `CLOCK_START`/`set_clock` imports). Fixed `test_forum_quorum_exactly_two_confirms`.
  - `test_11_state_machines.py` — `test_publish_blocked_by_reported_incident`: the fixture reported the incident against the questionnaire *editor*, but PRD declares no creator field on questionnaires/editions, so the editor's status as "a volunteer referenced by the cycle's activity" (§3.9) was not uniquely derivable — the implementation reasonably scoped the gate to PRD-declared volunteer references. The test now builds the pipeline with a forum and reports the incident against its *moderator* (`forum.moderator_volunteer_id`, PRD §3.7), an unambiguous reference; assertion unchanged (`ERR_UNRESOLVED_INCIDENTS_EXIST`, 422, then publish succeeds after dismissal).

- **Fixes applied to `implementation/`:**
  - `workspace/implementation/store.py` — `Store.new_id()`: `uuid.uuid4().hex` → `str(uuid.uuid4())`. PRD §2.5 declares `id` "a server-minted UUID with no type prefix"; the canonical UUID string form is dashed 8-4-4-4-12 (fixed `test_cycle_create_returns_declared_fields_and_starts_draft`).
  - `workspace/implementation/routes/responses.py` — `resubmit_response`: from-state check now admits `WITHDRAWN_HIDDEN` alongside `OVER_LIMIT_RETURNED`, mirroring `submit_response`. PRD §3.4 states resubmits run "under the same four gates", and gate 2 explicitly maps a hidden shell to `ERR_FILING_NOT_VERIFIED` (409); the previous strict from-state check pre-empted it with `ERR_INVALID_STATE`, making that PRD clause unreachable on the resubmit path (fixed `test_resubmit_blocked_when_filing_hidden`).

Orchestrator verification: all 8 `results.${i}.json` files exist (preserved, not deleted) and each reports `passed=92 total=92 failed=0 errors=0`; `find ... -newer results.1.json` over all source trees shows zero post-sweep edits — the clean sweep is current.

## Step 8: Finalize PRD — 2026-10-01T18:35:00.000Z

All edits verified. The diff is exactly three in-place paragraph revisions, nothing else touched.

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_3385_voter_guide_production_candidate_questionnaire_administration/workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md 305 lines vs PRD_FINALIZED.md 305 lines (0% line-count delta — all three changes are inline revisions within existing paragraphs; ~3 sentences added by character count).

### Changes (one per Step 7 item that revealed PRD silence/ambiguity)

- **§2.5 — revise** — `id` definition now pins the rendering: "a server-minted UUID with no type prefix, rendered in the canonical dashed UUID string form — thirty-two lowercase hexadecimal digits grouped 8-4-4-4-12 with hyphens" — `implementation/store.py:37-38` (`new_id` returns `str(uuid.uuid4())`; Step 7 changed it from undashed `.hex`).
- **§3.4 — insert** — after the resubmission sentence: resubmit from-state discipline rejects `INVITED`/`SUBMITTED`/`NONRESPONSE_MARKED`/`LATE_UNPUBLISHED` with `ERR_INVALID_STATE`, but a `WITHDRAWN_HIDDEN` shell proceeds into the four gates and, on a still-`ISSUED` questionnaire, is answered by the filing-verified gate with `ERR_FILING_NOT_VERIFIED`, never `ERR_INVALID_STATE` — `implementation/routes/responses.py:148-150`.
- **§3.9 — insert** — enumerates "volunteer referenced by the cycle's activity" exactly: a measure's `drafter_volunteer_id`, a review's `reviewer_volunteer_id`, or a forum's `moderator_volunteer_id`, whatever the resource's status; pipeline operators (e.g. questionnaire/edition creators, who are recorded nowhere) do not block publishing — `implementation/routes/cycles.py:27-39, 79-83`.

### Step 7 items with no PRD edit
- `test_helpers/fixtures.py` clock rewind and `test_06_boundary_precision.py` clock rewind — pure fixture bugs (reused ctx carried the shared logical clock past `filing_deadline`); PRD §3.2's deadline rule was already correctly stated and the impl matches it.

### Per-edit pre-edit search log

**Edit A (§2.5 id form).** (a) Subject: serialization form of resource `id`. (b) Enumerated: `store.py:37-38` (sole producer), `helpers.py:7-16` (`base_entity`, applies to all 14 resource types), all `helpers.get_*` resolvers (format-agnostic dict lookups — no UUID parsing/validation anywhere; only `store.py` imports uuid), `serialize.py` pass-through of `id`, `respond.py:15` (`api_request_id` with `req_` prefix — a different, already-specified field). (c) Wording scoped to the *minted/rendered* form ("rendered in…") so it imposes no input validation the impl does not perform.

**Edit C (§3.4 resubmit).** (a) Subject: response-shell from-state discipline and the filing-verified gate on candidate submission paths. (b) Enumerated: `responses.py` `submit_response` (admits `INVITED`+`WITHDRAWN_HIDDEN`, lines 110-112), `resubmit_response` (admits `OVER_LIMIT_RETURNED`+`WITHDRAWN_HIDDEN`, lines 148-150), `_submission_gates` ordering (ISSUED → filing → window, lines 87-95), `sweep_nonresponses` (157-183), `shells.py` hide/restore cascades, `filings.py` withdraw/disqualify/refile (withdrawal has **no** contest-state precondition, lines 92-99, so a hidden shell can coexist with a `CLOSED` questionnaire where gate 1 would pre-empt gate 2). (c) Scoped the `ERR_FILING_NOT_VERIFIED` outcome to "a still-`ISSUED` questionnaire" and framed the hidden-shell clause as "not rejected by the from-state check / never `ERR_INVALID_STATE`", so the wording stays true when gate 1 (`ERR_QUESTIONNAIRE_NOT_ACCEPTING_SUBMISSIONS`) fires first; verified the invariant `WITHDRAWN_HIDDEN` ⇒ filing never `VERIFIED` (restore only via refile→`FILED`; verify requires `FILED`).

**Edit B (§3.9 referenced volunteers).** (a) Subject: the publish gate's incident scope. (b) Enumerated: `cycles.py:27-39` (the referenced set — drafters, reviewers, forum moderators, no status qualifiers) and `cycles.py:79-83` (the only `ERR_UNRESOLVED_INCIDENTS_EXIST` raise site, confirmed by grep), `forums.py:160-191` (`author_volunteer_id` is only ever the forum's own assigned moderator, hence already inside the set), `measures.py:55`, `serialize.py` (confirmed no creator/editor field on cycle, jurisdiction, contest, filing, questionnaire, or edition serializers). (c) Added "whatever the resource's current status" (impl includes cancelled forums, remanded measures, all reviews) and used "exactly when" only after confirming `author_volunteer_id` cannot introduce a non-moderator volunteer into the set.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows changes at exactly lines 82, 154, 194 matching the three claimed edits verbatim; both files 305 lines; 0 implementation .py files modified after the clean sweep.

## Step 9: Complete PRD — 2026-10-01T19:10:00.000Z

All edits verified coherent. The task is complete.

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_3385_voter_guide_production_candidate_questionnaire_administration/workspace/PRD_COMPLETED.md`

- Source: `PRD_FINALIZED.md` (305 lines / 57,210 chars) → `PRD_COMPLETED.md` (306 lines / 61,436 chars); delta +1 line, +4,226 chars.
- Diff shape: 29 hunks — 28 single-line revisions + 1 appended table row (`ERR_INTERNAL | 500`). No sections added; all edits inline.
- **Counts: 22 ambiguity-pins, 7 mismatch-revisions** (29 total).

### Mismatch-revisions (PRD said X, impl does Y)

- **§2.6** — revise — mismatch — questionnaire `version` advances only when a submission lands `SUBMITTED`; an over-limit landing does not advance it — `routes/responses.py:72-84` (`touch(questionnaire)` only in the non-over branch).
- **§2.7** — revise — mismatch — removed "incomplete answer coverage" and "missing minutes_text" from the pre-path band-3 list and pinned their real positions: answer coverage is checked after the response shell resolves (missing shell yields `ERR_NOT_FOUND` first) and before the shell from-state check; the `minutes_text` rule fires after the forum resolves and ownership is confirmed — `routes/responses.py:103-112`, `routes/forums.py:135-140`.
- **§3.4** — revise — mismatch — restructured the "four gates" into the impl's actual order: coverage → shell from-state (initial submission proceeds only from `INVITED`/`WITHDRAWN_HIDDEN`) → `ISSUED` → filing-verified → window — `routes/responses.py:99-116`.
- **§3.4** — revise — mismatch — resubmission wording "the same four gates" → "the same gates", plus pinned that a path shell id belonging to another filing answers `ERR_NOT_FOUND` — `routes/responses.py:139-142`.
- **§3.6** — revise — mismatch — READY gate evaluation order changed to impl order: cycle-OPEN → neutrality-outstanding → language → accessibility-grade → contests-locked (was: locked listed second) — `routes/editions.py:107-132`.
- **§4 preamble** — revise — mismatch — candidate answer submission responds 201 although it mutates the pre-existing shell (exception to the creates-only-201 rule) — `routes/responses.py:116`.
- **§4 table** — revise — mismatch — forum `HELD` row: "clock past `scheduled_end`" → "at or past" (impl allows exactly at) — `routes/forums.py:152`.

### Ambiguity-pins (PRD silent, impl behavior pinned)

- **§2.2** — insert — ambiguity — error envelope also covers the 500 `ERR_INTERNAL` fallback — `app.py:40-43`.
- **§2.3** — revise — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST`; `created_at`-ascending ordering applies with or without filters, ties broken in creation order; unmatched filter values yield an empty page — `shape.py:127-145`, `helpers.py:194-203`.
- **§2.4** — insert — ambiguity — the logical clock may be moved to any instant, forward or backward — `routes/clock.py:13-20`.
- **§2.5** — revise — ambiguity — `version` starts at 1 at creation — `helpers.py:8-16`.
- **§2.5** — insert — ambiguity — request-body timestamps parse as ISO 8601, missing offset read as UTC — `timeutil.py:12-23`.
- **§2.7** — insert — ambiguity — resource-dependent ownership checks (forum moderator, measure drafter, attestation self-match) evaluate immediately after the resource resolves; `ERR_QUESTIONNAIRE_NOT_PINNED` added to the compliance band; forum `scheduled_start < scheduled_end` added to band 3 — `routes/forums.py:135-137`, `routes/contests.py:116-120`, `routes/forums.py:47-49`.
- **§3.2** — revise — ambiguity — `office_name` may be omitted *or explicitly null* for ballot measures; `seat_count`/`vote_for_count`/`questionnaire_word_limit` must be integers ≥ 1 when supplied; `filing_deadline` accepted at any instant — `routes/contests.py:38-55`.
- **§3.2** — insert — ambiguity — only the advance into `QUESTIONNAIRE_PHASE` consults cycle status; `GUIDE_READY`/`LOCKED` advances do not require `OPEN` — `routes/contests.py:104-105`.
- **§3.2** — revise — ambiguity — disqualify `reason` may be an empty string and is not recorded on the filing — `routes/filings.py:117-118`.
- **§3.3** — revise — ambiguity — `due_at` accepted at any instant; `position_index` may be any integer; `word_limit_override` must be ≥ 1 when supplied — `routes/questionnaires.py:22-44,52`.
- **§3.5** — insert — ambiguity — text with no words or no sentences (incl. empty `explanation_text`) yields grades 0.0/0.0 — `calc.py:59-61`.
- **§3.5** — insert — ambiguity — arguments may be filed while the measure is in any status — `routes/measures.py:103-125`.
- **§3.5** — insert — ambiguity — a verdict recorded while the measure is not `IN_NEUTRALITY_REVIEW` → `ERR_INVALID_STATE` — `routes/measures.py:180-181`.
- **§3.6** — revise — ambiguity — the cycle-OPEN rule scopes to the transitions endpoint (ready/re-open/retire); distribution does not consult cycle status — `routes/editions.py:143-144` vs `190-193`.
- **§3.6** — insert — ambiguity — `snapshot_contest_ids` ordered by `created_at` ascending, creation order breaking ties — `routes/editions.py:151-152`.
- **§3.6** — revise — ambiguity — `channel_code` is an opaque string (not restricted to the channel enum); `requested` may be zero — `routes/editions.py:184-189`.
- **§3.7** — insert — ambiguity — a `moderator_volunteer_id` referencing no volunteer → `ERR_MODERATOR_NOT_QUALIFIED` — `routes/forums.py:58-68`.
- **§3.7** — revise — ambiguity — a failed confirmation still leaves the recomputed `eligible_candidate_count` on the forum — `routes/forums.py:145-150`.
- **§3.7** — insert — ambiguity — a `PublicUser` supplying any source other than `PUBLIC_SUBMISSION` → `ERR_UNAUTHORIZED_ROLE` — `routes/forums.py:168-171`.
- **§3.8** — revise — ambiguity — incident `volunteer_id` must reference a live volunteer, checked after the acting coordinator's battery, failing with `ERR_INVALID_REQUEST` — `routes/incidents.py:29-31`.
- **§4 preamble** — insert — ambiguity — undeclared paths and unsupported methods both answer `ERR_NOT_FOUND` (404) — `app.py:30-37`.
- **§5** — revise + row — ambiguity — `ERR_INTERNAL` (500) catalogued as the catch-all in the same envelope — `app.py:40-43`.

Everything else walked — all 40+ endpoints, RBAC tables, state machines, cascades, formulas (word counts, FK/SMOG, balance ratio, completion index, page estimate, allocation waterfall), OCC rules, and error HTTP statuses — was already uniquely pinned by the PRD and matches `implementation/`.

Orchestrator verification: `diff -q PRD_FINALIZED.md PRD_COMPLETED.md` confirms a real diff (306 lines, not a no-op); `find` over implementation/test_suite/test_helpers shows zero post-sweep source edits, so the Step 7 clean sweep (92/92 × 8 rounds) remains valid; all 8 `results.*.json` evidence files remain in place.

## Pipeline Complete — 2026-10-01T19:10:00.000Z

All 9 steps done. Final state: SCAFFOLD.yaml + both design indices (clean lint), PRD.md → PRD_FINALIZED.md (3 Step-8 pins) → PRD_COMPLETED.md (29 Step-9 pins), 92 tests (36 difficulty + 56 corner, all Design-tagged), Flask implementation (25 modules, 57 endpoints), 8/8 sweep rounds at 92/92 with results evidence preserved.
