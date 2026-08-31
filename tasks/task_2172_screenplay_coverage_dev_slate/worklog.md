# Worklog — task_2172_screenplay_coverage_dev_slate

## Step 1: Create task directory — 2026-08-29T14:38:48.370Z

Created `tasks/task_2172_screenplay_coverage_dev_slate/` and `tasks/task_2172_screenplay_coverage_dev_slate/workspace/` (index 2172 = highest existing 2171 + 1).

## Step 3: Copy shared files — 2026-08-29T14:39:08.988Z

Copied `INSTRUCTION.md` → `tasks/task_2172_screenplay_coverage_dev_slate/workspace/INSTRUCTION.md`. (Run early; independent of Step 2.)

## Step 2: Generate scaffold — 2026-08-29T15:29:29.189Z

Scaffold generated for task 2172 (Screenplay Coverage & Development Slate), calibrated above the Expert band on every knob.

### Files written

| File | Lines |
|---|---|
| `tasks/task_2172_screenplay_coverage_dev_slate/SCAFFOLD.yaml` | 3,246 |
| `tasks/task_2172_screenplay_coverage_dev_slate/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2,124 |
| `tasks/task_2172_screenplay_coverage_dev_slate/SCAFFOLD_CORNER_DESIGN.yaml` | 3,541 |

### Counts

- **16 entities**, **9 state machines**, **3 concurrency rules** (all OCC on parent `version`), **18 calculations**, **35 validations**, **78 endpoints**, **47 error codes**, **8 roles**
- **§1.8: 24 difficulty instances** — 2/3/3/2/3/3/3/3/2 across the nine §0.5 rules (min is 2 each; >=18 required)
- **§1.9: 64 corner instances** across all nine claim-extraction sections (61 with executable recipes + 3 `excluded_because` stubs)

### Design profile

`multi_party_negotiation` x `compliance_audit`; layers = OCC, cascading side effects, dual-variant calculation, selector policy; topology `graph` (incl. a self-referential chain-of-title supersede edge); state-machine shape `parallel`; role model `segregation_of_duties` (three distinct SoD pairs: coverage assigner!=approver, milestone approver!=payer, committee member!=owning exec).

Key difficulty mechanics: `DevelopmentProject` carries two independent state axes (`rights_status` x `development_status`); `CoverageReport` has a revision cycle; `GreenlightReview` is a weighted fork-join with veto and a three-way outcome ladder. Dual variants sit on two different domains (coverage scoring 7.65 vs 4.15; option net-purchase 98,500,000 vs 103,500,000). Combinatorial mode (b) = floor-per-line + remainder-to-largest-share (7,500,001 -> 2,500,501/2,499,750/2,499,750); mode (c) = credit cap keyed on the *escalated* price (51,750,000, not 43,500,000). Three interval geometries: closed+12h-buffer (Reader), half-open with adjacency admitted (Property options), aggregate capacity 2 (Writer). Two cascades of depth 5 and 4 from different triggers, two conserved quantities (money ledger, capacity counter). All formula-derived assert values were computed in Python, not estimated.

### Notes

- Logical clock endpoint declared with the mandatory `2026-08-01T00:00:00Z` startup default.
- One latent ladder-masking trap was found and fixed during §1.9 authoring: `ERR_RELEASE_FORM_REQUIRED` was unreachable behind the state check, so priorities 80/82 were swapped and the requirement check was extended to `clear-intake` — §1.8's `release_expired_check_beats_rights_disputed_check_on_assign_reader` was re-grounded accordingly.
- Verified independently: zero duplicate instance names, zero dangling `grounds`, zero unbound `${var}`, every error code triggered by at least one design instance, every role exercised, no forbidden concurrency vocabulary.

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(78 endpoints, 16 entities, 24 §1.8 instances, 61 §1.9 instances, 1025 calls scanned)

## Step 4: Generate PRD — 2026-08-29T15:39:30.791Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — **452 lines** (92,756 bytes), written incrementally in five appends (header/§2.1, §2.2 verbatim copy, §2.3–2.10, §3.1–3.4, §3.5–3.9, §4+§5 generated programmatically from the scaffold).

**Withhold constraint honored:** only `SCAFFOLD.yaml`, the skill `SKILL.md` and `section-2.2-response-structure.md` were read. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

**Coverage verification (machine-checked against SCAFFOLD.yaml):**

| Scaffold table | Required | Represented |
| --- | --- | --- |
| entities | 16 | 16 (14 by CamelCase name; `RightsChainDocument` and `CommitteeVote` by domain prose — "chain-of-title document", "committee ballot" — with all their fields, states and endpoints present) |
| state machines | 9 | 9 — every `from`/`to`/`initial`/`terminal` state string present in backticks |
| calculations | 18 | 18 — every named constant value present (`SIGNATORY_AGENCIES`, `TURNAROUND_HOURS`, escalation/credit bands, tier ladder, milestone templates and day offsets, guild minimums, quorum/approval thresholds, buffer hours, anchor 5.50, etc.) |
| validations | 35 | 35 — all rendered as the explicit §2.6 rejection ladder with `applies_to` scopes enumerated |
| endpoints | 78 | 78 rows matched exactly in the §4 table (4 columns) |
| error codes | 47 | 47 in the §5 table (2 columns) **and** all 47 mentioned in §2/§3 narrative |
| roles | 8 | 8, each named with its `identity:` translated (3 entity-backed, 5 opaque) |

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 129 required, 129 present, 0 missing
- endpoints[].request_body: 67 required, 67 present, 0 missing
- endpoints[].query_params: 29 required, 29 present, 0 missing
- endpoints[].path_params: 1 required, 1 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 35 checked, 35 expressed in prose (ordered ladder, §2.6), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_property_version/expected_project_version + ERR_STALE_VERSION/412 all named, §2.7), 0 missing
- state_machines[].transitions: 9 machines / all transitions checked, all fully expressed, 0 missing
- calculations[]: 18 checked, 18 fully expressed in prose (no pseudocode, no fuzzy words), 0 missing
- validations[] conditions: 35 checked, 35 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 78 endpoints checked, all side effects expressed, 0 missing
- entities[].fields[] structured content: 129 checked, defaults/types/initial values reconstructible, 0 missing
- sibling-branch symmetry: 7 groups checked (ACTIVE/EXTENDED→LAPSED, ACTIVE/EXTENDED→EXERCISED, REQUIRED/SENT→WAIVED, DRAFT/REVISION_REQUESTED→SUBMITTED and →REJECTED, DRAFT_DELIVERED/POLISH_DELIVERED→GREENLIT, VOTING→PASSED/DECLINED/DEFERRED, APPLICABLE/NON_APPLICABLE credit variants), all equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 937
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 was verified byte-identical to `section-2.2-response-structure.md`. §3 contains zero tables and zero schema/field lists; the document ends at §5 with no audit footer.

## Step 6: Generate implementation — 2026-08-29T15:57:36.201Z

Implementation complete and boot-verified.

### Files written (`workspace/implementation/`, 2813 lines total)

| File | Lines | Contents |
|---|---|---|
| `core.py` | 463 | Error catalogue (47 IDs → HTTP), response envelope (`meta`/`response_type`/`data` + pagination fields), logical clock, in-memory `Store`, `X-User-ID`/`X-User-Role` auth + RBAC, three-pass body validation (shape 400 → enum 422 → range 422), pagination/filtering, `add_months` day-clamping, half-up rounding |
| `calc.py` | 522 | All enums + domain constants, the 18 calculations (rights-chain ladder, release-form requirement, turnaround budget, reader selector + window overlap, coverage score pair, calibration bias, heat score/tier, four-step option pricing, milestone waterfall, ledgers) and the shared cascades |
| `routes_property.py` | 142 | Properties, chain-of-title documents, `/_clock` |
| `routes_submission.py` | 212 | Submissions, release forms, clear-intake, withdraw |
| `routes_coverage.py` | 441 | Readers, assign-reader, assignments, reports (submit/revision/approve/reject), tracking board |
| `routes_option.py` | 195 | Option draft/execute/extend/exercise/lapse/terminate |
| `routes_project.py` | 126 | Projects, turnaround, reversion notice |
| `routes_writer.py` | 342 | Writers, engagements, milestone payments |
| `routes_greenlight.py` | 279 | Committee seats, reviews, weighted ballots, close ladder |
| `app.py` | 80 | Blueprint registration, error handlers, global request lock, `0.0.0.0:$PORT` |
| `start.sh`, `requirements.txt` | 11 | Guarded `pip install` (only when flask missing) + `exec python3 app.py` |

### Coverage
**78 / 78 declared endpoints implemented** (verified by enumerating `url_map`). Storage is pure in-memory dicts; **no seeding anywhere** — `app.py` only registers blueprints.

### Boot verification
`PORT=18732 bash start.sh` came up in under 4 s; `GET /_clock` → 200 `{"current_utc":"2026-08-01T00:00:00Z"}`, `GET /literary-properties` → 200 with empty `data` and correct pagination meta, `POST /literary-properties` → 201 with the full envelope; server killed cleanly, no processes left.

### Behaviour spot-checked (4 smoke suites, all green)
Weighted composite/normalized scores + calibration bias, heat score & tier ladder, four-step option pricing incl. re-pricing when a project links (escalation band moves 0 → 1500 → 2500 bps), calendar-month clamping (Jan 31 + 1 mo → Feb 28; Aug 31 + 18 mo → Feb 29 2028), milestone waterfall (floor-then-remainder-to-largest-pct, lowest index on tie; sums reconcile exactly for all four templates), conserved ledgers (assign→recall, attach→terminate), the five-link approval cascade, lapse and turnaround/reversion cascades, OCC on all three superseding creates, lazy release-form expiry, reader selector ranking/exclusions, and the rejection ladder (401 → 403 → 404 → 400 → 422 enum → 422 range → 403 owner → 412 → 409 state → 409 terminal → 403 SoD → release → rights → temporal → business → fiscal).

### Two PRD ambiguities resolved (worth flagging)
1. **§2.6 rung 14/15 vs §3.3 prose** disagree on whether release-form checks or `ERR_PROPERTY_RIGHTS_DISPUTED` wins on assign-reader. I followed §2.6 (release checks first) because `SCAFFOLD.yaml` validation priorities (80/82 vs 86) agree with it.
2. Where a *foreign* resource's state is a precondition (option status on attach, maturity vs option-EXERCISED on reversion, rights-OWNED vs dev-status on open-voting), the generic ladder doesn't cleanly apply, so I followed the §3 prose order — which the scaffold's `state_machines` preconditions also list in that order.

## Step 5: Generate unit tests — 2026-08-29T16:10:14.820Z

Test infrastructure and suite generated and verified.

### Files written

**`test_helpers/`** (2,626 lines)
| file | lines |
|---|---|
| `__init__.py` | 55 |
| `types.py` | 506 |
| `api_client.py` | 350 (one method per PRD endpoint, incl. `/_clock`) |
| `api_errors.py` | 109 (47 error ids + status map, registered with the framework) |
| `assertions.py` | 417 |
| `factories.py` | 154 |
| `constants.py` | 115 |
| `test_users.py` | 101 |
| `fixtures.py` | 819 |

**`test_suite/`** (4,440 lines) — `conftest.py` (78) plus 9 thematic files: `test_01_submission_intake` (420), `test_02_chain_of_title` (189), `test_03_reader_assignment` (824), `test_04_coverage_and_tracking_board` (653), `test_05_option_agreements` (593), `test_06_development_slate` (418), `test_07_writer_engagements` (642), `test_08_greenlight_committee` (418), `test_09_access_control` (205).

### Coverage

- **Queue A (Difficulty): 48 tests** — all 24 instances covered by exactly 2 tests each.
- **Queue B (Corner): 61 tests** — all 61 non-stub instances covered by >=1 test. The 3 `excluded_because:` stubs were *not* translated; all three cross-references were verified to resolve to real difficulty instances.
- 109 test functions → 122 collected pytest items (the not-found sweep is parametrized x14). Zero shortfalls, zero unknown/dual tags, zero `skip`/`xfail`.
- A verification script confirms every docstring carries >=1 quoted PRD citation that survives a whitespace-normalized literal grep of `PRD.md`, and exactly one `Design:` line.

### Instances skipped: none

Every instance passed the PRD-first two-condition filter. Three judgement calls worth flagging:

1. **The two assign-reader precedence pairs** (`release_expired_check_beats_rights_disputed_check_on_assign_reader`, `reader_window_conflict_check_beats_reader_capacity_check`) are in tension with PRD §3.3's *narrative* ordering, which walks the rights check before the release checks and the capacity check before the window check. I kept both tests and cited §2.6's dedicated rejection ladder — which states normatively that "a check never fires before one above it has passed" and numbers expiry(14) < rights(15) and temporal(16) < remaining-constraints(17). §3.3 makes no claim about which error wins when two rules are violated, so §2.6 uniquely determines the outcome. If the implementation-side reviewer disagrees, these four tests are the ones to look at first.

2. **`second_attach_exceeds_writer_budget_cap_aggregate_check` had an unreachable setup chain.** The corner design proposes two `PROPOSED` `ORIGINAL_DRAFT` engagements on one project, but PRD §3.7's superseding create would `TERMINATE` the first when the second is proposed, so the design's asserted end state (`E1 ATTACHED`, `E2 PROPOSED`) is unreachable. I kept the instance's exact claim — each 8,000,000-cent engagement fits the 12,000,000-cent cap individually, the aggregate does not — by giving the second engagement a different `engagement_type` (`REWRITE`, guild floor 5,000,000). No assertion was weakened.

3. **`option_credit_cap_tier_keyed_on_escalated_price` has a wrong number in its `setup:` prose** (it claims a pre-trigger `net_purchase_due_cents` of 22,500,000; the PRD's four steps give 30,000,000 — credit is `min(60,000,000 fees, 67,500,000 cap)`). The `assert:` block is only about post-trigger values and is correct, so I asserted only those.

**Other notes:** datetime assertions compare parsed instants rather than exact strings (`assert_instant_equals`), because §2.4 pins the three-fractional-digit format only for `created_at`/`updated_at` — asserting a literal `.000Z` on `option_end_at`, `paid_at` etc. would have failed the two-reader test on serialization, not on the rule.

## Step 7: Run tests and iterate — 2026-08-29T16:18:47.164Z

Clean green sweep. Final state: 109 test functions → 122 collected items, all passing in all 8 parallel rounds.

**Iterations run:** 2 (initial sweep → one assertion fix → confirming sweep).

**Sweep results**
- Iteration 1: 121/122 in all 8 rounds; a single, perfectly reproducible (non-flaky) failure — `test_close_below_quorum_is_refused_and_the_review_stays_voting`, `assert 0.0 == 59.99`.
- Iteration 2: **122/122 in all 8 rounds, union of failures = 0.**

**Tests deleted:** none.

**Assertions removed (STEP 1c partial-coverage split):**
- `test_suite/test_08_greenlight_committee.py::test_close_below_quorum_is_refused_and_the_review_stays_voting` — removed only `assert review["quorum_pct"] == 59.99`. **Category: COMPUTED-FIELD SILENCE / non-unique-derivability.** PRD §3.9 names `quorum_pct` only inside the close ladder ("First, the two percentages are computed…"), and §3.9's read paragraph enumerates what a review read exposes as "the frozen eligible weight and the running tallies" — the tallies being explicitly the four (`cast_weight_bps`, `decisive_weight_bps`, `approve_weight_bps`, `veto_cast`), which "default to 0" before any ballot. Nothing in PRD says a *refused* close persists the computed percentage. Two PRD-faithful readings exist: (a) the request is rejected under §2.6's "reports the highest-precedence violation and stops", so nothing is written and `quorum_pct` keeps its 0.00 default (what the implementation does); (b) the percentages are computed-and-stored ahead of the ladder, so 59.99 survives the refusal. Both are admissible → the assertion goes, the rest of the test stays. All other assertions in that test are verbatim-covered (`ERR_QUORUM_NOT_MET`/409, review stays `VOTING`, `eligible_weight_bps == 10000`, `cast_weight_bps == 5999`, project stays `DRAFT_DELIVERED`) and were kept and pass. Scaffold rule that drove the test: `Corner/validations/close_review_below_quorum_returns_quorum_not_met_and_stays_voting`.

**Fixes applied to `test_helpers/`:** none — no fixture, factory, or role-header bug surfaced.

**Fixes applied to `implementation/`:** none.

**Adjudication of the three flagged judgement calls** (all resolved in favour of keeping the tests as written; all pass):
1. **Assign-reader precedence pairs.** §2.6 is normative and explicit ("The ladder below is evaluated strictly top to bottom; a check never masks one above it"), numbering release-expiry/requirement at rung 14, rights posture at 15, temporal admissibility at 16 and remaining business constraints (incl. `ERR_READER_AT_CAPACITY`) at 17. §3.3's narrative walks the flow but makes no claim about which error wins when two rules are violated, so it does not compete with §2.6. Both `release_expired_check_beats_rights_disputed_check_on_assign_reader` tests and both `reader_window_conflict_check_beats_reader_capacity_check` tests are uniquely derivable from §2.6. The Step 6 implementation resolved the same tension the same way, so test and implementation agree — no fix needed.
2. **`second_attach_exceeds_writer_budget_cap_aggregate_check`.** The REWRITE rework is PRD-faithful: §3.7's superseding create only terminates prior proposals "on the same project that is still `PROPOSED` **and carries the same `engagement_type`**", so a REWRITE second proposal legitimately coexists with an ORIGINAL_DRAFT. Guild floors (7,500,000 / 5,000,000) both clear at 8,000,000; cap is 12% of 100,000,000 = 12,000,000; 8M + 8M > 12M → `ERR_BUDGET_EXCEEDED` at the re-applied attachment-time headroom test. Verbatim-covered, kept.
3. **`option_credit_cap_tier_keyed_on_escalated_price`.** Arithmetic re-derived independently against §3.5's four pinned steps: 90,000,000 × 11500/10000 = 103,500,000; 103,500,000 >= 100,000,000 selects the 5000 bps cap; credit = min(60,000,000 fees, floor(103,500,000 × 5000/10000)) = 51,750,000; net = 51,750,000. The test asserts only post-trigger values, so the wrong pre-trigger number in the scaffold's `setup:` prose never reaches an assertion. Kept.

**Orchestrator verification:** all 8 `results.{1..8}.json` re-read independently — 122/122 in every round.

## Step 8: Finalize PRD — 2026-08-29T16:21:39.302Z

Only one PRD edit was warranted.

### Line counts
- `PRD.md`: 452 lines (92,756 bytes)
- `PRD_FINALIZED.md`: 452 lines (93,158 bytes)
- Line delta: 0 (+0.0%). The single change is an in-place extension of one paragraph (+439 characters, ~+0.5% by bytes). *(Orchestrator-verified: +402 bytes on disk.)*

### Changes
- **§3.9 (The Greenlight Committee, close-ladder paragraph, line 306)** — *revise* — pinned that `quorum_pct` and `approval_pct` are working values during the close and are persisted onto the review **only by a close that resolves**; a close refused at rung one (`ERR_QUORUM_NOT_MET`) writes nothing, so the stored pair stays at the 0.00 it is given when the review is convened — `implementation/routes_greenlight.py:116-117` (create defaults) and `implementation/routes_greenlight.py:236-239` (`fail(...)` raises ahead of the two assignments).

### Pre-edit search log

**Edit 1 — §3.9 percentage persistence**
- **(a) Subject:** where and when a `GreenlightReview`'s `quorum_pct` / `approval_pct` fields are written, and what they hold when they have not been written.
- **(b) Impl paths enumerated:**
  - `grep -n "quorum_pct\|approval_pct" implementation/*.py` → exactly four sites: `routes_greenlight.py:116,117` (row creation, `Decimal("0.00")`) and `routes_greenlight.py:238,239` (post-ladder assignment in `close_review`). No other module reads or writes them.
  - `routes_greenlight.py` `close_review` (full body read): `recompute_review_tallies` → local `quorum`/`approval` computation → `fail("ERR_QUORUM_NOT_MET")` at rung one → only *after* that, `review["quorum_pct"]`, `review["approval_pct"]`, `review["decision_note"]`, outcome, `touch(review)`. Confirms nothing is persisted on the refusal and `version` does not advance.
  - `calc.py:513-522` `recompute_review_tallies` — the one mutation that *does* run before the refusal; it touches only `cast_weight_bps`, `decisive_weight_bps`, `approve_weight_bps`, `veto_cast`, and is idempotent because every `cast_vote` already recomputed them (`routes_greenlight.py:200`). So the refusal is observationally a no-op.
  - Parallel review-mutating endpoints checked for any competing write/reset of the pair: `create_review` superseding sweep (`routes_greenlight.py:122-129`), `open_voting` (`:150-168`), `cast_vote` (`:171-202`), `withdraw_review` (`:256-268`). None assign either field.
  - `core.py:117,156-161` — `Decimal` serialization / `round_half_up`, confirming the fields surface as two-decimal numbers on the review read (`GET /greenlight-reviews/{id}`, `routes_greenlight.py:133-136`).
- **(c) Wording adjustment:** drafted first as "are reset to 0.00 on a refused close", which would have falsely implied a write on the refusal path and would have mis-described the supersede/withdraw paths that never touch the fields. Re-scoped to "left exactly as they were — both are 0.00 from the moment the review is convened, and they stay there until a resolving close writes them," which is true on every enumerated path. Also deliberately omitted any explicit `version`-on-refusal claim, since §2.4's general rule already covers it and a fresh sentence there could over-constrain.

### Items intentionally left unedited
- The three Step 7 adjudications (assign-reader precedence, same-`engagement_type` superseding create, credit cap keyed on the escalated price) all resolved as *PRD already determines it, impl agrees*. §2.6 rungs 14-17, §3.7's "**and carries the same `engagement_type`**", and §3.5's four pinned steps are already normative and match `routes_coverage.py:106-132`, `routes_writer.py`, and `calc.py`'s pricing. Per method step 2 those paragraphs stay verbatim.
  - One note for the record: §3.3's narrative orders the rights-disputed check *before* the release-form-requirement check, while `routes_coverage.py:109` (required) precedes `:113` (disputed). §2.6's ladder — declared "evaluated strictly top to bottom" — puts requirement at rung 14 and rights posture at rung 15, matching the impl, and no test exercises the pair. I left both paragraphs untouched rather than introduce a precedence claim that §2.6 already settles.

## Step 9: Complete PRD — 2026-08-29T16:29:34.245Z

`PRD_COMPLETED.md` is written. All 10 implementation modules were walked; 32 inline edits landed across 28 paragraphs.

**File stats** — `PRD_FINALIZED.md`: 452 lines / 93,158 chars → `PRD_COMPLETED.md`: 452 lines / 97,925 chars (**+4,767 chars**). Headings and both reference tables (§4 endpoints, §5 error catalogue) are byte-identical; no sections added.

**Counts** — 27 ambiguity-pins, 5 mismatch-revisions.

**Changes**

- §2.1 — revise — mismatch — the five-operation ownership list implied a `ERR_NOT_RESOURCE_OWNER` on ballots; impl always takes `member_id` from `X-User-ID`, so the check is structural and never issues — routes_greenlight.py:179,192
- §2.3 — revise — ambiguity — a non-integer `limit`/`offset` is also `ERR_VALUE_OUT_OF_RANGE` — core.py:407-420
- §2.3 — revise — ambiguity — `created_at` ties (routine under a frozen clock) break by server creation order — core.py:286
- §2.3 — insert — ambiguity — an unparseable integer filter matches nothing; an unparseable boolean filter is ignored — core.py:436-458
- §2.4 — insert — ambiguity — a PATCH leaves omitted fields alone and still bumps `version`/`updated_at` even when it changes nothing — routes_coverage.py:71-80, routes_greenlight.py:66-75
- §2.5 — insert — ambiguity — clock set and read both return `{current_utc}`, echoing the supplied string verbatim — routes_property.py:208-222
- §2.6 rung 4 — revise — mismatch — "six operations" → seven; convening a greenlight review also resolves a body FK — routes_greenlight.py:96
- §2.6 rung 5 — insert — ambiguity — an explicit JSON `null` is treated as an omitted field — core.py:367
- §3.1 — revise — ambiguity — `supersedes_document_id` resolves across the whole document set; same-property is not enforced — routes_property.py:149-151
- §3.1 — insert — ambiguity — the per-property document listing accepts `doc_type` alone — routes_property.py:182
- §3.2 — insert — ambiguity — all three open-release-form refusals are `ERR_INVALID_STATE` — routes_submission.py:79-85
- §3.2 — insert — ambiguity — send/execute past `expires_at` is `ERR_INVALID_STATE`, not `ERR_RELEASE_FORM_EXPIRED` — routes_submission.py:121,136
- **§3.3 — revise — mismatch — the adjudicated open item: narrative reordered so expiry → release-form-requirement → rights-disputed, matching impl and §2.6 rungs 14/15** — routes_coverage.py:103-113
- §3.3 — insert — ambiguity — selector `created_at` ties fall back to seating order — calc.py:288
- §3.3 — insert — ambiguity — recalling a `SUBMITTED` assignment is `ERR_INVALID_STATE` — routes_coverage.py:209
- §3.4 — insert — ambiguity — `composite_score`/`normalized_score` start null; the body edit is not gated on report status and never moves it — routes_coverage.py:145-162,255-278
- §3.4 — revise — mismatch — board entries are archived only by a passed greenlight; a newer entry does not supersede an older one — routes_greenlight.py:261-264
- §3.4 — insert — ambiguity — premature rejection is `ERR_INVALID_STATE`, not `ERR_REVISION_LIMIT_EXCEEDED` — routes_coverage.py:402
- §3.4 — revise — mismatch — recall rejects only `DRAFT`/`REVISION_REQUESTED`, but withdrawal rejects everything not already `APPROVED`, `SUBMITTED` included — routes_submission.py:205, routes_coverage.py:219
- §3.5 — insert — ambiguity — the two non-temporal extension gates fail with `ERR_INVALID_STATE` — routes_option.py:118-121
- §3.5 — insert — ambiguity — a missing linked `OPTIONED` project on exercise is `ERR_INVALID_STATE`, checked after expiry — routes_option.py:141-144
- §3.5 — insert — ambiguity — a premature lapse is `ERR_INVALID_STATE` — routes_option.py:161
- §3.5 — insert — ambiguity — engagements terminated by a lapse carry a null `termination_reason` — routes_option.py:177
- §3.6 — insert — ambiguity — an attachment/delivery not matching a declared transition still succeeds and leaves the axis unchanged — routes_writer.py:138-146,222-234
- §3.7 — insert — ambiguity — budget test outranks guild test when both fail at proposal — routes_writer.py:88-94
- §3.7 — revise — ambiguity — delivery matches the lowest-`sequence_index` `SCHEDULED` row of the type; none at all is `ERR_INVALID_STATE` — routes_writer.py:211-218
- §3.7 — insert — ambiguity — an unsettled milestone refuses completion with `ERR_INVALID_STATE` — routes_writer.py:244-246
- §3.8 — insert — ambiguity — turnaround-terminated engagements carry a null `termination_reason` — routes_project.py:291
- §3.8 — insert — ambiguity — the option-`EXERCISED` gate runs after maturity and fails with `ERR_INVALID_STATE` — routes_project.py:301-308
- §3.9 — insert — ambiguity — a non-delivered development state at open-voting is `ERR_INVALID_STATE` — routes_greenlight.py:159
- §3.9 — insert — ambiguity — the acting member's `X-User-ID` must resolve to a seat or `ERR_MEMBER_NOT_FOUND` (404) — routes_greenlight.py:179
- §3.9 — revise — mismatch — "Three checks" listing duplicate-vote second → four checks ordered `VOTING` → seat `ACTIVE` → SoD → duplicate — routes_greenlight.py:180-191

---

## Pipeline complete — 2026-08-29T16:29:34.245Z

All nine steps finished. Final artifact state: 8/8 sweep rounds at 122/122 passing; `PRD.md` (452 L) → `PRD_FINALIZED.md` (+402 B) → `PRD_COMPLETED.md` (+4,767 B).
