# Worklog — task_3223_volunteer_moderator_governance_community_policy_enforcement

Scenario: Volunteer Moderator Governance & Community Policy Enforcement (Reddit) — community creation with
volunteer moderators setting local rules within sitewide policy, moderator tooling (removal, ban, automated rule
enforcement with audit logs), escalation path when local rules conflict with sitewide policy and administrator
intervention, moderator team succession, inactivity removal and top-moderator disputes, content policy enforcement
across reports, automated detection and appeals with account sanctions, brigading and vote manipulation detection
across communities, community quarantine and restriction states with reinstatement conditions, protest events where
communities restrict access and platform response.

## Step 1: Create task directory — 2026-09-30T12:04:35.477Z

Task directory was pre-allocated by the caller as
`./tasks/task_3223_volunteer_moderator_governance_community_policy_enforcement/` with an empty `workspace/`
subdirectory already present. No index computation and no directory creation were performed; verified the path
exists and `workspace/` is empty. Proceeding to Step 2 (scaffold generation).

## Step 2: Generate scaffold artifacts — 2026-09-30T13:04:09.126Z

Scaffold generation is complete and lint-clean. Final summary:

## Files written

| File | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_3223_volunteer_moderator_governance_community_policy_enforcement/SCAFFOLD.yaml` | 2,486 |
| `…/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1,394 |
| `…/SCAFFOLD_CORNER_DESIGN.yaml` | 2,005 |

## Lint verdict (§1.8/§1.9 → §1.5, run verbatim)

```
Coverage
  §1.5 endpoints declared:    75
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     43
  Calls scanned (§1.8+§1.9):  394

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5
and all §1.1 FKs have reverse-reachability in §1.5.
```

## Coverage produced (beyond Expert band, per the harder directive)

- **14 entities** (Community, CommunityRule, Moderator, TeamSuccession, Post, Account, ContentReport, AutoDetectionBacklogItem, ContentDecision, AccountSanction, BrigadingCluster, Appeal, ProtestEvent, ProtestApproval) — graph topology, self-referential `moderator_account_id`, polymorphic `content_source_type/source_id`, 15 FK declarations all reverse-reachable.
- **9 state machines / 46 transitions** — Community (6 states, compound + posture-driven + a 6-way cyclic fan-out), TeamSuccession, Moderator, ContentReport, ContentDecision, AccountSanction, BrigadingCluster, Appeal, ProtestEvent. Each carries explicit preconditions and side effects; several state machines are self-contained cycles.
- **4 concurrency rules**, all true CREATE-with-supersede races resolved by OCC on `Community.version` with `expected_community_version`.
- **14 calculations / 20 variants** — three distinct dual-variant families (per-report vs summed rounding; status-AND-age vs flag-only; record-then-recompute); evaluation order pinned on every combinatorial formula.
- **20 validations**, priorities 1–20, with the required cross-category conflicts (`business_safety` vs `existence`, `business_fiscal` vs `state`).
- **75 endpoints**, **32 errors**, **6 roles** (all with mandatory `identity:`), 4 complexity layers (version-pinning on approval, contagion/risk propagation, pagination with filtering, cascading side effects).

## Difficulty / corner instances

- **§1.8: 18 instances** across all nine §0.5 rules (2 each), covering both differentiation axes per rule — dual-variant across community vs account domains, combinatorial mode (a) and (b), non-linear machines on TeamSuccession and Appeal, depth-3 and depth-2 cascades from different triggers, boundary checks on `overlap_ratio` and the 90-day window, cross-entity pairs Moderator→Community and ProtestEvent→Moderator, overlap semantics on restriction intervals vs publication age, and conserved quantities on karma/index vs OPEN-report count.
- **§1.9: 43 active instances + 6 `excluded_because` stubs**, spanning all nine claim-extraction-guide sections (Entities 11, State Machines 5, Calculations 4, Validations 6, Endpoints 3, Errors 4, RBAC 3, Cross-Cutting Layers 5, Consistency Model 1).

Every `assert:` value derived from a formula was computed by executing the formula's constants in Python (e.g. `99.01`, `0.67`, `88.00`, `55.00`, `70.00`, `40.00`, `85.00`, `2.64`, `150/250/250/400`, `48/39/64`), and every `setup_api_calls`/`trigger` chain was replayed call-by-call against §1.2/§1.4/§1.6 with placeholder closure verified mechanically.

Notes on two judgement calls worth flagging: (1) `api_prefix` and the FK reverse-reachability GETs use the literal `{id}` placeholder on the owning parent segment, because the linter's check (f) is a literal `startswith` that no `{parentResourceId}`-style template can satisfy; (2) no random/UUID value participates in any business decision — the one `id`-derived flag I first drafted was replaced with `AccountSanction.account_wide_enforcement_counted`, a copy of `ContentDecision.is_account_wide`, and the only tie-break fallbacks are `created_at`.

## Step 3: Copy shared INSTRUCTION.md — 2026-09-30T13:04:21.376Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes, md5
`60ec3841647dd4af7332162d5ff7b3c1`, identical to source). Proceeding to Step 4 (PRD generation).

## Step 4: Generate PRD document — 2026-09-30T13:14:16.737Z

The PRD is complete and all three hard contracts audit clean. Final summary below.

## Report

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3223_volunteer_moderator_governance_community_policy_enforcement/workspace/PRD.md` — **457 lines**, ~99 KB, English prose PRD.

**Section structure**
- §1 Introduction (3 paragraphs: governance collision surface, coherence under pressure, document organisation)
- §2 Global Specifications — 2.1 User and Role-Based Access Control (all 6 roles, each `identity:` translated), 2.2 API Response Structure (verbatim fixed block, byte-matched), 2.3 Pagination, 2.4 The Governance Clock, 2.5 Common Resource Properties (incl. `ProtestApproval`'s `common_fields: false` exception), 2.6 Nested Resource Retrieval and Validation Precedence (the full 20-priority cascade rendered as ranked bands), 2.7 Optimistic Concurrency Control (both `expected_community_version` / `expected_moderator_version`), 2.8 Precision and Rounding, 2.9 Posture Propagation and Cascade Semantics, 2.10 Moderation Attribution and the Audit Reference
- §3 Business Logic — 10 subsections, grouped by lifecycle/role/institution rather than the canonical 7: founding & local law; team appointment/seniority/handover; posts/reports/automated detection; content decisions & sanction registry; brigading; appeals; protests; community posture; moderator dormancy; role-segregated read surfaces
- §4 Endpoint Definitions — intro paragraph on status-code rules + 75-row, 4-column table (Method, Path, Description, Authorized Role(s))
- §5 Error Code Catalogue — 32-row, 2-column table (Error ID, HTTP Status)

**Coverage audit (all scaffold rules rendered, none omitted)**
- Entities: 14/14; entity field names 107/107 in backticks
- State machines: 9/9; transitions 46/46 (each `from`/`to` named, every precondition paired with its `error_id`, every `side_effect` stated); states 32/32
- Calculations: 14/14 fully expressed in precise prose — all 20 variants (both dual/dual/triple-variant families) with their pinned vs superseded readings and worked examples; all `constants` embedded in business context
- Validations: 20/20 conditions matchable to their `error_id`; priority ordering expressed as an explicit ranked cascade in §2.6
- Concurrency rules: 4/4 (write endpoint, OCC field, parent entity, `ERR_STALE_VERSION` + 412 all named; framed purely in stale-version terms, no race framing)
- Endpoints: 75/75 in the §4 table; every `request_body`/`input` identifier (66) and every path parameter (11, matching scaffold `{id}` literal) present in backticks
- Errors: 32/32 in the §5 table and every one additionally mentioned in §2–§4 narrative
- Roles: 6/6 with exact spelling and per-role identity prose in §2.1

**Contract results:** Contract 1 PASS (0 missing across fields/inputs/path params); Contract 2 PASS (all 8 categories walked, several fidelity gaps found and repaired during audit — report `OPEN → DISMISSED` dismissal path, `ProtestApproval` field set, `handle`/`account_state`, `decision_id`/`protest_id`/`approved_on_utc`, and the corrected 5-condition quarantine vs 4-condition restricted reinstatement sets); Contract 3 PASS (§3 contains zero `/`-prefixed, bare-method, or method+path tokens — the only `POST` backtick in §3 is the report `content_source_type` enum member, not an endpoint identifier).

**Constraints honoured:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced; no sibling `task_*/` directory was read. PRD ends at §5 with no audit footer.

## Step 5: Generate unit test suite — 2026-09-30T14:05:45.356Z

Generation complete. Summary below.

## Files written

**`test_helpers/`** (2307 lines total)

| File | Lines |
|---|---|
| `__init__.py` | 27 |
| `types.py` | 442 |
| `api_client.py` | 245 |
| `api_errors.py` | 76 |
| `assertions.py` | 225 |
| `factories.py` | 146 |
| `constants.py` | 137 |
| `test_users.py` | 46 |
| `fixtures.py` | 963 |

**`test_suite/`** (2847 lines total)

| File | Lines |
|---|---|
| `conftest.py` | 39 |
| `test_01_community_health.py` | 126 |
| `test_02_decision_tiers.py` | 312 |
| `test_03_lifecycle_chains.py` | 310 |
| `test_04_succession_and_cascades.py` | 345 |
| `test_05_state_machines.py` | 293 |
| `test_06_rbac_and_validation.py` | 381 |
| `test_07_content_and_reports.py` | 782 |
| `test_08_fields_and_consistency.py` | 259 |

`ApiClient` exposes 81 endpoint methods; the error map registers all 32 catalogued ids. Everything byte-compiles and `pytest --collect-only` resolves 76 tests with no import errors (server not started; execution is the runner's job).

## Test count and breakdown

- **76 test functions**, 0 untagged, 0 dual-tagged, 0 tags pointing at non-existent instances.
- **Queue A (Difficulty): 31 tests across 15 of 18 instances** — every covered instance has ≥2.
- **Queue B (Corner): 45 tests across 42 of 43 non-stub instances.**
- All 6 `excluded_because:` stubs skipped; every `difficulty_instance` cross-reference resolves to a real `name:` in the difficulty index.

## Instances SKIPPED (PRD-first reason)

**§1.8 (queue A) — 3 instances skipped:**

1. `moderation_action_window_on_publication_age` (resource_temporal_overlap) — **unique-derivability fails.** The instance asserts `legitimacy_score == 48` for a freshly-detected item at 2-dp overlap 0.10, but PRD §3.3 works the PRD-consistent case: with report_count 2 the pinned reading gives `penalty = min(40, floor(2 * 1.5 * 1.5 * 1.5)) = 6`. Since the recompute is stated to count "the `OPEN` report count for this very detection", one report yields `floor(1 * 1.0 * 1.5 * 1.5) = 2` → `48` only under the *superseded* order the PRD explicitly warns against (which is the same order that makes the PRD's own "64" example come out 66). Two PRD-only readers cannot agree on 48.
2. `coordinator_approval_requires_active_moderator_row` (cross_entity_state_dependency) — **no verbatim PRD coverage.** The instance asserts that a resigned approver's approval stops counting toward quorum, and that `required_quorum_count` drops to 2. PRD §3.7 defines `quorum_approval_count` solely as "After each approval the server recomputes ... from the whole approval set"; it never states that approval rows are filtered by the approving moderator row's current status.
3. `karma_and_sanction_index_conserved_across_reinstate_then_lift` (compensating_invariant) — **no PRD trigger for the asserted values.** The setup lifts the ban via a *grant*, and PRD §3.6 makes evidence movement a hard precondition of GRANT ("the appeal must carry evidence movement ... otherwise the request is refused with `ERR_NO_NEW_EVIDENCE`"), so the instance's `new_evidence_url: null` + `sanction_misapplication_present: false` grant cannot succeed. The asserted index 0.50 is further underivable: with a LIFTED row plus one counted ACTIVE row the pinned denominator gives 1/2, which matches only if the pre-lift warning-sanction row is discarded — contradicting "every `AccountSanction` row of that account, whatever its status".

**§1.9 (queue B) — 1 non-stub instance skipped:**

4. `conditional_posture_gate_on_declared_maturity` (cross_cutting_complexity_layers) — **unique-derivability fails.** The instance asserts `ERR_RULE_CONFLICT` for a band-3 `is_sitewide_floor` rule inside an all-ages community. PRD §3.1 names the conflict as "a `rule_band` below the sitewide floor band" but never states the sitewide floor band's value, so a reader placing it at 1 would accept the write. The PRD also gives no floor band as a function of `is_over_18`, so the implied 2 ≠ 2 comparison is unstated.

## Additional PRD-first prunings during verification

- `Corner/calculations/sanction_award_points_tier_ladder` — kept, but the third rung's `award_points == 250` dropped: PRD §3.4 pins only rung 1 → 150, rung 2 → 250 and rung 4 → 400.
- The two correctness assertions in the community-health instance (three tier-1 reports → 0.99 / 99.01) are kept, since PRD §3.5 states that example verbatim.
- Where the brigade per-cluster penalty is genuinely ambiguous (PRD §3.5 says "the cluster's `overlap_ratio` multiplied by its `signal_severity_band`" while also stating the §1.3 floor step), fixtures drive health below the quarantine line and assert `<= 40.00` rather than an exact value.

## Stage-2 audits

- **Tag coverage:** 76/76 tagged; every non-stub corner instance ≥1; every *covered* difficulty instance ≥2; zero stray tags.
- **PRD-citation pass:** all 151 quoted fragments ≥20 chars in every docstring contain a ≥8-word verbatim (whitespace-normalized) match against `workspace/PRD.md`; 0 misses. No scaffold/table references remain in either tree; no `pytest.mark.skip`/`skipif`/`xfail` anywhere.
- **Hygiene:** 0 unresolved imports, 0 unused imports, no dangling references after the prunings.

## Step 6: Generate implementation — 2026-09-30T14:39:21.468Z

The implementation is complete and verified. Final summary:

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_3223_volunteer_moderator_governance_community_policy_enforcement/workspace/implementation/`

```
start.sh                  9
requirements.txt          0   (Flask>=3.0,<4.0)
app.py                   61   entry point, error handlers, before_request clock sweep
db.py                   214   in-memory store, logical clock, UUID/ISO helpers, round2
errors.py                59   ApiError + full error catalogue with HTTP statuses
middleware.py           117   auth headers, RBAC, moderator/account ownership
response.py             243   envelope, pagination, request-body validation
routes/  (10 files)     999   accounts, administration, brigades, communities,
                              detection, moderators, posts, protests, rules, successions
services/ (6 files)   1863   community (476), content (677), teams (354), protests (187),
                              appeals (162), __init__
                              total 3686 lines
```

## start.sh

`set -euo pipefail`, `cd "$(dirname "$0")"`, guarded `if ! python3 -c "import flask"` install, then `exec python3 app.py`. Binds `0.0.0.0` on `$PORT` (default 10000). Verified ready in **1 second** from a cold `bash start.sh`, clean log.

## PRD → module mapping

- **§2.1 auth / §1.7 RBAC** → `middleware.py` (`X-User-ID`/`X-User-Role`, six roles, entity-backed ownership).
- **§2.2 envelope / §2.3 pagination** → `response.py` (`meta`/`response_type`/`data`; `limit`/`offset`/`total_count`/`has_more`, 1..100).
- **§2.4 clock** → `db.py` + `POST /_clock/set_current_utc`; default `2026-09-01T00:00:00Z`, never wall-clock.
- **§2.6 precedence cascade** → each route orders auth → segregation-of-duties → existence → OCC → state → referential → business rules.
- **§2.7 OCC** → `expected_community_version` / `expected_moderator_version`, refused 412 ahead of any state check.
- **§2.9/3.8 posture** → `services/community.py` (self-loop recompute, RESTRICTED/INSTITUTION_NEGOTIATION/QUARANTINED/ARCHIVED, archive cascade).
- **§3.3 legitimacy, §3.4 decisions/sanctions, §3.5 brigading + health** → `services/content.py`.
- **§3.2 team, succession, §3.9 inactivity** → `services/teams.py`.
- **§3.6 appeals + watchdog, §3.7 protests + quorum/cross-power** → `services/appeals.py`, `services/protests.py`.

All 14 calculations implemented with the PRD's pinned orders (per-report rounding, unrounded gate comparison, band-before-penalty, registry-size-before-insert, `min(linear,wrap)` width, health-escalator-after-recompute). **75/75 declared endpoints** implemented, zero extras (verified by diffing the route map against the scaffold table).

## Bugs found and fixed by driving the API

1. `moderator_version` was never incremented — the OCC field for all four moderator mutations.
2. Legitimacy score started its report count at 1 instead of counting OPEN reports (PRD §3.3 anchors two reports → 64).
3. Award points used a post-insert registry size, contradicting the PRD's 150/250/400 anchors → pinned to pre-insert size.
4. Ownership checks ran after existence/OCC, violating the priority-2 band → reordered across all moderator-scoped routes.
5. Account reads were mutating `updated_at`/`version`; now purely projective.
6. `escalation_severity` survived revive/dismiss; `participant_count` below 1 returned 404 instead of 400.

## Constraints honored

- **No seeded data**: `db.STATUS` is born empty; nothing is registered at import. Accounts are materialized only as a side effect of creating the sanctions/detections that reference them. No `seed_*`/preload/fixture anywhere.
- **No on-disk persistence**: only source files exist in `implementation/` (no sqlite/json/tmp artifacts); `grep` for `open(`/`json.dump`/`sqlite` finds nothing.
- **Fresh boot wipes state**: create a community on boot A → `total_count` 1; kill and re-run `start.sh` → `total_count` 0.
- **Isolation rule respected**: no read of `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_suite/`, or `test_helpers/` (grep confirms no references); the test suite was never run. No sibling `task_*` directory was listed, globbed, grepped, or read.
- **Process safety**: every server I started was killed by PID resolved from its own port; no `pkill`/`killall`/`pgrep` was ever used.

Verification was done with two throwaway `/tmp` smoke drivers (39 checks, all passing) that assert only PRD-stated numbers; these are not part of the deliverable.

## Step 7: Run tests and iterate to PASS — 2026-09-30T16:07:58.457Z

All 8 parallel rounds now pass **75/75** with zero flakiness.

## Summary

**Iterations run:** 6 parallel 8-round sweeps (48→57→66→72→74→75 passing). Every failing test was deterministic across all 8 rounds in every iteration, so the union never hid a timing race.

**Tests deleted (1):**
- `test_demotion_fails_once_the_community_has_no_top_moderator` (`test_suite/test_04_succession_and_cascades.py`) — *ENUM-MEMBERSHIP / no verbatim coverage.* PRD §3.2 enumerates exactly three demotion preconditions (distinct-account segregation of duties, `moderator_role == TOP_MODERATOR`, matching moderator version) and explicitly places the self-demotion refusal *after* the state check. It never ties demotion to `active_top_moderator_count`, and §2.6 lists no such priority level. The test's own title ("no top moderator") also contradicts its own assertion (`active_top_moderator_count == 1`), and its fixture reuses one row as both actor and target, so any faithful ownership check rejects it at the priority-2 band — the asserted error is unreachable. Scaffold rule that drove it: `Difficulty/cross_entity_state_dependency/moderator_demotion_requires_active_top_moderator`.

**Fixes to `test_helpers/`:** none — every test-side bug was localized to `test_suite/`.

**Fixes to `implementation/`:**
- `services/content.py` — `signal_severity_band`: link-breadth rungs now accumulate (breadth 10 → 4) instead of overwriting; §3.5 states "+1" at each of 5/10/20. Also removed a pre-escalation health recompute in `escalate_cluster` so the severity reads after "the escalation's own health recompute".
- `services/community.py` — `brigade_health_penalty` (STEP 2) now sums per-cluster `min(band*(1+floor(overlap*10)), 30)` per §3.5's `brigade_penalty_points`, not `min(sum(overlap*band), 30)`, which undercounted for overlaps ≥ 0.50.
- `routes/communities.py` — community creation now requires `description` (§3.1 names only `is_over_18` and `founding_moderator_account_id` as optional).
- `services/teams.py` — `floor_band` defaults raised (2 for all-ages, 3 for over-18) so a band-1 `is_sitewide_floor` rule conflicts, as §3.1 requires.
- `routes/administration.py` — sanction-reinstatement reports `ERR_ACTIVE_SANCTION_CONFLICT` when the target is already `ACTIVE` (§2.6 ranks that band above state eligibility; §3.6 names the already-ACTIVE case).
- `routes/moderators.py` — demote route no longer runs a community-membership check ahead of its state check (§2.6: "the demote route carries its state check first").
- `services/protests.py` — removed the `ACTIVE` precondition on *requesting* a protest; §3.7 places that gate on coordination only, not on request.
- `routes/accounts.py` — account-scoped reads now recompute (materialize) the account rather than 404 with `ERR_ACCOUNT_NOT_FOUND`, so an account sanctioned only via a community decision is readable (§3.4 recomputes the subject account as the sanction write completes).

**Fixes to `test_suite/` (fixture/assertion bugs, all made ≥ faithful to PRD):**
- `test_07` — brigade boundary fixture used 3/4 legitimate participants (giving 0.70/0.60); corrected to 7/8 so the gap is exactly 0.30 vs 0.20. Both watchdog fixtures now take a *third* referral so the appeal is parked in `UNDER_WATCH` (§3.6: the two directions traverse opposite edges). Award ladder now uses four distinct outcomes — §3.4 refuses a same-outcome duplicate. Added missing `author_rule`/`moderator_rows`/`record_decision`/`sanction_rows` imports; `.000Z` timestamp shapes per §2.5.
- `test_03` — added missing `audit_decision`/`validate_success` imports; conservation fixture now uses tier-3 reports so the reopened report weighs 0.67; index assertion corrected 0.67→0.00 per §3.4's numerator disjunction; referral-toggle community state corrected `ACTIVE`→`INSTITUTION_NEGOTIATION` (§3.8: the fixture's account-wide sanction clears both posture gates).
- `test_06` — duplicate-rule-code test now carries the community's advanced version (§3.1: rule mutations carry `expected_community_version`), otherwise the OCC band masks the duplicate code.
- `test_08` — restricted-exit test rewritten to isolate the health-floor arm; §3.8 expressly excludes the ninety-day clock from the restricted exit.
- `test_04` — revert-cycle test rewritten to assert the PRD-stated post-remedy reset (0), dropping the PRD-silent four-round accumulation.
- `test_05` — appeal-window arm advanced 7 days, since §3.6 says "7 days or more" is refused.
- `test_02` — karma assertion corrected 100→97 (the decision-route MUTE synthesis is immediate per §3.4).

No skips, no xfails, no assertion downgrades to HTTP-status checks; all edited files compile and carry no unused imports. Scratch/debug files were written only under `/tmp` and are removed.

## Step 8: Finalize PRD to implementation — 2026-09-30T16:59:54.861Z

All edits are applied and verified. The probe server is stopped.

## Summary

**Deliverable**: `/home/ubuntu/github/CodingPRD/tasks/task_3223_volunteer_moderator_governance_community_policy_enforcement/workspace/PRD_FINALIZED.md`

**Line counts**: PRD.md = 457 lines; PRD_FINALIZED.md = 457 lines; **0.0% line delta**. Character delta: 99,206 → 100,388 (+1,182 chars, +1.19%). Six lines revised; no sections added.

### Changes (one bullet per edit)

- **§2.6** — revise — account routes report the dedicated `ERR_ACCOUNT_NOT_FOUND` only on the single-account read and the per-account detection-backlog read; the account-scoped sanction/post/appeal collection reads recompute the account and return a possibly-empty result, and a nested appeal that does not resolve reports generic `ERR_NOT_FOUND` — `routes/accounts.py:26,35,52,83,94-99`, `routes/detection.py:61,64`, `services/content.py:216,237,244`
- **§2.6** — revise — demote route imposes no precondition that the acting moderator belong to the target community (state check → self-demotion refusal → no membership gate) — `routes/moderators.py:125-132`, `services/teams.py:209-223`, `middleware.py:81-94`
- **§3.1** — revise — `description` is a required, non-empty creation input (only `is_over_18`/`founding_moderator_account_id` optional); omission → `ERR_INVALID_REQUEST` — `routes/communities.py:22-31`, `services/community.py:319-343`
- **§3.1** — insert — sitewide floor band is 2 (all-ages) / 3 (over-18), so a floor rule may not declare band 1, nor band 1/2 in an over-18 community — `services/teams.py:14-20,64,91`
- **§3.5** — revise — health-index STEP 2 brigade penalty is the sum of the per-cluster penalty already defined in §3.5 (`min(band*(1+floor(overlap*10)),30)`), replacing the loose "`overlap_ratio` × `signal_severity_band`" form — `services/community.py:44-56`, `services/content.py:618-626`
- **§3.6** — revise — already-`ACTIVE` reinstatement target is refused with `ERR_ACTIVE_SANCTION_CONFLICT` rather than the state error — `routes/administration.py:31-46`, `services/content.py:543-556`

### Per-edit pre-edit search log

1. **§2.6 account not-found**: (a) subject = not-found code on account-scoped routes. (b) grepped `load_account`/`recompute_account`/`ensure_account`/`ERR_ACCOUNT_NOT_FOUND`; read `routes/accounts.py`, `routes/detection.py:61`, `services/content.py:216-274`; probe-confirmed empty-list for unknown-account sanctions/posts/appeals vs 404 for the record read. (c) Adjusted: first draft said the reads "materialize" the account — `recompute_account` does not `ensure_account`, so narrowed to "recompute the account from its sanction registry"; scoped the 404 claim to collection reads + appeal detail only.
2. **§2.6 demote ordering**: (a) subject = demote route preconditions/order. (b) read `routes/moderators.py:125`, `services/teams.py:161,209`; grepped `require_community_member` (present on remove/resign/reinstate, absent on demote). (c) Kept the existing "state check first, self-demotion after" clause; scoped the new clause to the demote route only so it does not mis-describe its siblings.
3. **§3.1 description required**: (a) subject = requiredness of `description`. (b) read `routes/communities.py:22`, `services/community.py:319`; no community-update route exists. (c) None.
4. **§3.1 floor band**: (a) subject = sitewide floor band value. (b) read `services/teams.py:14-20,64,91`; grepped all `floor_band` callers (only create/update rule); probe-confirmed all-ages rejects band 1, over-18 rejects bands 1 and 2. (c) None.
5. **§3.5 brigade penalty**: (a) subject = brigade penalty term in health index. (b) read `services/community.py:44-56,101-111`, `services/content.py:618-626`; confirmed the parallel `content.py` function uses the same formula and that the §3.5 escalation paragraph already defines the correct total, making §3.5's health STEP 2 the lone contradictory statement. (c) None (reference to "the per-cluster penalty defined above" ties it to the already-correct paragraph).
6. **§3.6 already-ACTIVE conflict**: (a) subject = error code for reinstating an already-ACTIVE sanction. (b) grepped `ERR_ACTIVE_SANCTION_CONFLICT` (only `routes/administration.py:45`, `services/content.py:548,550`). (c) First draft claimed the "conflict band outranks the state check" — that invokes a §2.6 ranking ordered the other way, so dropped the ranking claim and stated only the observed code.

### Step 7 items deliberately NOT edited (PRD already matches impl)
- `signal_severity_band` breadth accumulation — PRD §3.5 states "+1" at each of 5/10/20; impl adds cumulatively (`content.py:571-584`). No silence.
- `escalate_cluster` recompute removal — PRD §3.5 says the health escalator is "evaluated after the escalation's own health recompute"; impl does not recompute health before reading it (`content.py:642-665`), matching the literal prose.
- Protest-request `ACTIVE` precondition (`services/protests.py:71`) — §3.7 states no request-state precondition; impl agrees.
- Restricted-exit 90-day clock (`community.py:387`) — §3.8 already excludes the ninety-day clock from the restricted exit; impl agrees.
- Remaining Step 7 bulleted items (test_02 karma 97, test_03 index/referral, test_04 revert 0, test_05 window, test_07 fixtures) are consistent with the unchanged PRD; they were pure test-side fixes.

**NO-NEW-MISMATCH**: every edit was re-scoped after enumerating all impl paths on the same subject; no wording narrowing, redefining, or reordering behavior that the implementation exhibits elsewhere.

## Step 9: Complete PRD vs implementation — 2026-09-30T17:29:29.891Z

Done. PRD_COMPLETED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_3223_volunteer_moderator_governance_community_policy_enforcement/workspace/PRD_COMPLETED.md`.

## Summary

**Source:** `PRD_FINALIZED.md` existed, so it was copied to `PRD_COMPLETED.md`.
- Lines: 457 → 457 (unchanged; all edits are inline within existing paragraphs)
- Chars: 100,388 → 118,349 (**+17,944**, +17.9%)
- Paragraph count: 158 → 158 (no new sections or paragraphs added)

**Counts:** 59 paragraphs revised. Of these, roughly 55 are ambiguity-pins (PRD silent on a behavior impl exhibits) and 4 are mismatch-revisions (PRD described a different behavior): the duplicate-dismissal sentence in §3.4, the `AUDITED`→`SETTLED` auto-settlement, the §3.9 inactivity-anchor worked example, and the §3.7 cross-power "ranks 1, 2 and 3" example. Most paragraphs mix both classes; counts below name the dominant one per change.

### Changes (one bullet per change)

- §2.1 Actor identity — insert — ambiguity — an acting `Moderator` id resolving to a row in another community is `ERR_FORBIDDEN_ROLE`; an id resolving to no row is opaque and records no attribution — `middleware.py:81-105`, `teams.py:37-47`
- §2.3 Pagination — insert — ambiguity — empty-string/null `limit`/`offset` fall to defaults; non-integer pagination args give `ERR_PAGINATION_INVALID` — `response.py:54-68,98-107`
- §2.3 List ordering — insert — ambiguity — creation-timestamp ties broken by ascending `id` — `db.py:213-215`
- §2.4 Clock — insert — ambiguity — clock advance returns new value; invalid ISO is `ERR_INVALID_REQUEST`; naive timestamps read as UTC; the clock may move backwards — `routes/communities.py:57-66`, `db.py:26-36,90-104`
- §2.5 `id` format — insert — ambiguity — plain UUID in canonical hyphenated form — `db.py:107-109`
- §2.5 `updated_at` — insert — ambiguity — a mutation at the same clock instant yields an identical stamp string — `db.py:82-87,169-181`
- §2.6 Request-shape band — insert/revise — ambiguity — required-field treats absent/null/whitespace alike; integral floats accepted as ints; booleans rejected as ints; non-object body is `ERR_INVALID_REQUEST`; method-not-allowed surfaces `ERR_INVALID_REQUEST` on HTTP 405 — `response.py:146-243`, `app.py:30-36`
- §2.7 OCC version fields — insert — ambiguity — the version field is optional; omitting it skips the comparison — `routes/rules.py:90-96`, `routes/moderators.py:18-24`
- §2.9 Posture propagation — insert — ambiguity — health-driven quarantine also fires on read after a clock advance — `community.py:271-299`
- §2.9 Archival cascade versions — insert — ambiguity — cascade also advances each archived moderator's `moderator_version` — `community.py:451-473`
- §2.10 Attribution — insert — ambiguity — attribution is written only for an acting `Moderator`, never an administrator — `teams.py:37-47`
- §3.1 Community creation — insert — ambiguity — synthesized founder row gets `display_name` `Founder` and a stamped `promoted_at_utc` — `community.py:349-363`
- §3.1 Accounts — insert — ambiguity — accounts are materialized lazily on first reference (no create route), starting `HONORED`/100 karma with `handle`=id — `content.py:216-234`
- §3.1 Rule authoring — insert — ambiguity — `rule_code`/`rule_band` required, `rule_text` optional/null; band outside 1-3 is `ERR_INVALID_REQUEST` — `routes/rules.py:26-31`, `teams.py:53-79`
- §3.1 Escalation — insert — ambiguity — `escalation_note` optional; response returns the rule; non-`ACTIVE` target is `ERR_INVALID_STATE` — `routes/rules.py:73-87`, `teams.py:105-124`
- §3.1 Rule amendment — insert — ambiguity — non-`ACTIVE` rule amendment is `ERR_INVALID_STATE`; omitted fields are preserved — `teams.py:82-102`
- §3.2 Appointment — insert — ambiguity — `moderator_account_id`/`moderator_role` required, `display_name` optional/null — `routes/moderators.py:45-47`, `teams.py:130-155`
- §3.2 `promoted_at_utc` — insert — ambiguity — stamped only on a false→true top-seat transition, cleared on true→false, preserved otherwise — `community.py:117-139`
- §3.2 Inactivity removal — insert — ambiguity — the five conditions are checked in a fixed order (state, top-seat, final-moderator, inactivity, version) — `teams.py:175-195`
- §3.2 Resignation — insert — ambiguity — requires the row to be `ACTIVE` — `teams.py:198-206`
- §3.2 Demotion — insert — ambiguity — the self-match compares the acting id against both the row id and `moderator_account_id`; no community-membership precondition; state and role checked together; refreshes derived fields — `teams.py:209-223`, `routes/moderators.py:125-132`
- §3.2 Reinstatement — insert — ambiguity — non-`DEMOTED` row is `ERR_INVALID_STATE` — `teams.py:226-238`
- §3.2 Action log — insert — ambiguity — the action vocabulary is the five kinds; `action_at_utc` is the clock instant — `teams.py:26-47`
- §3.2 Discussion rounds — insert — ambiguity — `round_note` optional; non-eligible state is `ERR_INVALID_STATE`; most-recent author tracked per community — `teams.py:273-286`
- §3.2 Dispute/SoD — insert/revise — ambiguity — `dispute_note` optional; the SoD check fires via the community-level recorded author and also for a non-resolving succession id; `blocked_by_moderator_id` is the acting `X-User-ID` — `teams.py:289-313`, `routes/successions.py:58-79`
- §3.2 Succession completions — insert — ambiguity — deadline reached inclusively; the no-`ACTIVE`-moderators and zero-top tests coincide; settling is idempotent and once per clock value — `teams.py:329-358`, `community.py:284-292`
- §3.3 Posts — insert — ambiguity — `author_account_id`/`post_type` required, `title`/`body` optional/null; `status` enumerated — `routes/posts.py:18-31`, `content.py:43-59`
- §3.3 Content reports — insert — ambiguity — required set; no source/reporter existence check; `reporter_account_id` optional — `routes/posts.py:57-68`, `content.py:65-97`
- §3.3 Report filing — insert — ambiguity — earliest matching backlog item is linked; filing fires the recompute and advances the version — `content.py:77-97`
- §3.3 Detection recording — insert — ambiguity — at most one `OPEN` item per source (`ERR_INVALID_STATE`); subject account materialized `WARNED`; `legitimacy_score`/`legitimacy_band` are response-only, absent from the single-item read — `content.py:149-201`, `routes/detection.py:51-59`
- §3.3 Legitimacy score — insert — ambiguity — score and band are integers; ages compared as whole days — `content.py:133-146`
- §3.4 Decision recording — insert — ambiguity — required-field set and the non-negative precedent count — `routes/detection.py:72-88`
- §3.4 Decision cascade — revise — **mismatch** — PRD said a duplicate report may be auto-dismissed during the sweep; impl has no such path (`maybe_autodismiss_duplicates` is dead code). Revised to state no sweep dismissal, plus the exact per-status sweep transitions and version bump — `content.py:406-427`
- §3.4 Account-wide sanction — insert — ambiguity — the synthesized decision is created `SETTLED` with sealed `audit_log_ref` and null tier; any of the seven outcomes accepted — `content.py:489-540`
- §3.4 `award_points` — insert — ambiguity — the tier-selecting registry size is the post-write size (one more than pre-write) — `content.py:280-307`
- §3.4 Account standing — insert — ambiguity — `account_state` precedence (`BANNED`>`MUTED`>`WARNED`>`HONORED`) over `ACTIVE` sanctions; `account_sanction_index` is the displayed two-decimal ratio — `content.py:244-274`
- §3.4 Decision lifecycle — revise — **mismatch** — PRD claimed an audited-but-unreversed decision auto-settles from `AUDITED` to `SETTLED`; impl has no such path. Revised to the single tier≤3 auto-settle, plus state preconditions on audit/re-audit/revise and the direct-`SETTLED` account-wide decision — `content.py:430-486`
- §3.5 Cluster recording — insert — ambiguity — all four counts required and non-negative; over-count legitimate participants clamps overlap at 0 rather than erroring — `routes/brigades.py:25-28`, `content.py:587-615`
- §3.5 Cluster fields — insert — ambiguity — `escalation_severity` cleared on revival/dismissal; `evidence_complete` is stored at recording; recording fires no recompute — `content.py:587-615`
- §3.5 Escalation — insert/revise — ambiguity — `cluster_id` mandatory, `sanction_ladder` optional; non-`DETECTED` cluster is `ERR_INVALID_STATE`; the escalation-severity formula restated unambiguously as `floor(B * (1 + R))`; cluster version advances twice — `routes/administration.py:68-77`, `content.py:642-665`
- §3.5 Revival/dismissal — insert — ambiguity — non-`ESCALATED` revival is `ERR_INVALID_STATE`; non-`DETECTED` dismissal is `ERR_INVALID_STATE`; `DISMISSED` is terminal — `content.py:668-692`
- §3.5 Health index — insert — ambiguity — `open_report_weight` held to two decimals; `DETECTED` clusters contribute nothing — `community.py:32-111`
- §3.6 Appeal filing — insert — ambiguity — required set; `ERR_SANCTION_NOT_FOUND` for non-resolving or cross-account sanction; non-`ACTIVE` sanction is `ERR_INVALID_STATE`; initial nulls — `routes/accounts.py:69-80`, `appeals.py:26-54`
- §3.6 Deciding — insert — ambiguity — invalid `decision` is `ERR_INVALID_REQUEST`; `decision_reason_code` resolution precedence — `appeals.py:92-127`
- §3.6 Referral/watchdog — insert — ambiguity — mandatory `appeal_id`, non-resolving is `ERR_NOT_FOUND`, wrong-state is `ERR_INVALID_STATE`; watchdog applies its lift only to an `ACTIVE` sanction — `routes/administration.py:53-62`, `appeals.py:76-162`
- §3.6 Sanction reinstatement — insert — ambiguity — non-resolving `sanction_id` is `ERR_SANCTION_NOT_FOUND`; recomputes the issuing community's derived fields — `routes/administration.py:31-47`, `content.py:543-556`
- §3.7 Protest request — insert — ambiguity — mode required, conflicting list optional/empty; no community-state precondition; list recorded verbatim; initial field values — `routes/protests.py:26-38`, `protests.py:71-102`
- §3.7 Approvals — insert — ambiguity — both fields required; moderator must resolve in-community (`ERR_NOT_FOUND`); only `REQUESTED` protests approvable; quorum counts distinct moderator rows — `routes/protests.py:86-99`, `protests.py:108-132`
- §3.7 Cross-power breadth — revise — **mismatch** — PRD said positions are "ranks 1, 2 and 3" inside the sorted set; impl gives positions 1..power, so an account moderating four communities has width 2 not 3. Revised to state positions are ranks 1..power, with the four-community worked case — `protests.py:26-50`
- §3.7 Coordination — insert — ambiguity — four conditions with quorum arithmetic ordered before the access-mode restriction; the protest's own version advances — `protests.py:138-162`
- §3.7 Policy advisory — insert — ambiguity — non-`PROTEST_RESTRICTED` community is `ERR_INVALID_STATE` — `community.py:409-420`
- §3.8 Institution negotiation — insert — ambiguity — the manual door requires `RESTRICTED` (`ERR_INVALID_STATE`); the automatic door opens only from `ACTIVE` — `routes/administration.py:152-158`, `community.py:250-265`
- §3.8 Quarantine — insert — ambiguity — the health line is read on the recompute path and on read; the cadence comparison is against the moment of entry — `community.py:187-228`
- §3.8 Regulation cadence — insert — ambiguity — recordable in any posture; changes only the later automatic move and the version — `community.py:217-220,423-428`
- §3.8 Reinstatement request — insert — ambiguity — a community in neither `QUARANTINED` nor `RESTRICTED` is `ERR_INVALID_STATE` — `community.py:371-403`
- §3.8 Lifetime counters — insert — ambiguity — only the reinstatement counter is ever moved; `quarantine_approval_count` stays zero — `community.py:325-343,393-396`
- §3.8 Archival — insert — ambiguity — non-`QUARANTINED` is `ERR_INVALID_STATE`, re-archival is `ERR_ARCHIVED_COMMUNITY`; explicit cascade field details; reads still succeed — `community.py:442-478`
- §3.9 Inactivity anchor — revise — **mismatch** — the worked example claimed a 100-day community anchor overrides a 10-day own action; the pinned rule (and impl) uses the own action. Revised so the example matches impl — `community.py:64-76`
- §3.10 Approval reads — insert — ambiguity — the two approval-list scopes read the same join records and differ only in addressing — `routes/protests.py:69-83`
- §4 Status codes — insert — ambiguity — added succession creation to the `201` list (impl returns 201) — `routes/successions.py:17-27`

### Notes
- `test_helpers/`, `test_suite/`, `SCAFFOLD*.yaml` and `worklog.md` were not read as authority (tests) or at all (scaffold/worklog, which were excluded).
- Two impl behaviors remain genuinely unobservable through the HTTP surface and were pinned at the source level rather than as endpoint behavior: `stored open_report_weight` (`community.py:32-36`) and the cadence reference instant (`community.py:198-207`). Both are pinned in prose so the PRD matches what impl computes.