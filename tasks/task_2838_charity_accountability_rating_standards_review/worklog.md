# Worklog — task_2838_charity_accountability_rating_standards_review

## Step 1: Create task directory — 2026-09-05T04:40:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2838_charity_accountability_rating_standards_review` and its `workspace/` subdirectory. Index 2838 was pre-assigned by the orchestrating invocation; no scan of `./tasks/` was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T07:06:00.000Z

All three scaffold artifacts are complete and lint clean.

## Files

| path | lines |
|---|---|
| `SCAFFOLD.yaml` | 3660 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2099 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 7792 |

`SCAFFOLD.yaml` carries §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` keys); the other two files each have exactly one top-level key. No "harder than expert level" text survives in any of the three.

## Counts

13 entities · 58 endpoints · 9 state machines · 2 §1.2.1 concurrency rules · 13 calculations · 32 validations (priority ladder 1–32) · 52 error codes · 6 roles · 4 active complexity layers (`dual_variant_calculation`, `cascading_side_effects`, `version_pinning_on_approval`, `optimistic_concurrency`) · 18 §1.8 instances (9 rules × 2) · 91 §1.9 instances (78 with `test_recipe`, 13 `excluded_because` stubs) · 1137 replayed API calls across both design files.

## Verdict block (verbatim, final run)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  §1.5 endpoints declared:    58
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     78
  Calls scanned (§1.8+§1.9):  1137

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Coverage note

The difficulty design puts two instances behind each of the nine §0.5 rules, all keyed to pre-computed literals: dual-variant divergence (provisional 70.88/NEEDS_IMPROVEMENT vs final 83.38/MEETS_STANDARDS on identical dimension rows, plus INTAKE→INVESTIGATED complaint credibility crossing a severity tier), pinned-order formula composition (fundraising efficiency per-year 0.1867 vs pooled 0.1824; penalty rate keyed on the pre-penalty band), the cyclic two-round correction/appeal loop, four-hop cascades from a substantiated complaint and a granted appeal, priority-pair conflicts (wrong analyst over missing validated filing; completeness floor over the publish window), boundary instants (publish at exactly `correction_deadline_at`), cross-entity state guards, half-open period adjacency with the 30-day methodology buffer, and two conservation invariants (the 8-standard partition across waive/revoke, the penalty ledger across substantiate/reverse). The corner design walks all nine claim-extraction sections — entities 25, state machines 17, calculations 16, validations 10, endpoints 8, rbac 5, complexity layers 5, errors 4, consistency model 1 — and reaches full closure on three independently scripted checks: every one of the 52 error codes is triggered somewhere, every one of the 58 endpoints (including `POST /ops/transition-sweep` and the six remaining reverse lookups) is exercised by at least one chain, and every `grounds:` token resolves to a declared §1.1–§1.7 element with no duplicate instance names across the two files. The 13 stubs are all genuine §1.8 duplicates and each names an existing difficulty instance. Two SCAFFOLD.yaml ambiguities were fixed while writing the last sections: the adopt precondition now guards the null-`effective_until` predecessor case (an open-ended version imposes no lower bound beyond the clock buffer, matching priority 17) and it no longer claims `ERR_INVALID_REQUEST` for a window check that priority 17 owns as `ERR_METHODOLOGY_WINDOW_CONFLICT`.

## Step 3: Copy shared files — 2026-09-05T07:07:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T07:24:00.000Z

PRD generation for task 2838 is complete.

**Output:** `workspace/PRD.md` — **462 lines / 124 KB**, built with 11 chunked `cat >>` appends (line count verified monotonically increasing after each: 71 → 111 → 174 → 198 → 214 → 237 → 267 → 283 → 305 → 323 → 337 → 402 → 462).

**Structure:** §1 Introduction; §2.1–§2.10 (RBAC, verbatim §2.2 envelope, pagination, identity/version, logical clock, rounding order, OCC, the 32-step admission ladder, flat-surface/path resolution, segregation of duties); §3.1–§3.9 (methodology drafting/comment, adoption + impact projection + transition grants, organizations/filings/winning filing, governance standards + waivers, cycle opening + scoring pipeline, composite scoring two variants, org review/corrections/appeals, complaints + accountability cascade, publication/notification/withdrawal); §4 endpoint table; §5 error table. Ends at §5's last table row — no audit footer.

**The four required checks**

1. **Ends at a real boundary** — final line is the last row of the §5 table. No mid-sentence truncation; all 26 headings present in order.
2. **58/58 endpoints present** — §4 table generated programmatically from `endpoints[]`; every scaffold path string found (0 missing).
3. **52/52 error codes present** — every `errors[].id` appears (0 missing).
4. **13/13 calculations and 32/32 validations** — every calculation has a narrative home (including both variants of `composite_score_with_penalty` and of `complaint_credibility_score`); every numeric constant in every `calculations[].constants` block is present in prose (`TRANSITION_GRANT_DELTA: -5.00` and `UNSUBSTANTIATED_ADJUSTMENT: -15` written as "at most negative 5.00" and "a subtraction of 15 points"). §2.8 contains items numbered 1–32 in exact scaffold priority order; automated check confirmed each item carries all of its validation's `error_id` alternatives, its `http_status`, and every endpoint path from its `applies_to` enumeration.

**Hard Contracts:** Contract 1 (Field-Name Coverage) PASS — all 159 entity field names, the 4 common fields, every endpoint input identifier and every `{path_var}` present as standalone backticked tokens; one fix applied (a §2.9 sentence enumerating all path variables, since 12 of them existed only inside longer path strings). Contract 2 (Rule Coverage) PASS — 57/57 state transitions have `from`/`to` co-located with driving action and side effects; both concurrency rules specified in §2.7 with `expected_organization_version` / `expected_rating_cycle_version`, `ERR_STALE_VERSION`, 412; all four-hop cascades written hop-by-hop; all `applies_to` scopes enumerated; sibling branches given equal density. Contract 3 (§3 Path Purity) PASS — 339 distinct backticked tokens in §3, 0 begin with `/`, 0 bare HTTP methods, 0 method+path combos.

**Constraints honored:** neither design yaml was opened/grepped/referenced; no sibling task directory read. §2.2 diffed byte-for-byte against the doc-generator skill's canonical section — identical.

**Orchestrator verification:** `tail -12 workspace/PRD.md` ends on the final `ERR_DATA_COMPLETENESS_TOO_LOW | 409` table row — a real section boundary, not mid-sentence. No truncation, so no regeneration needed. Grep for "expert level" / "harder than expert" in PRD.md returns nothing — the Step 2 difficulty directive did not leak.

## Step 6: Generate implementation — 2026-09-05T07:59:00.000Z

The implementation is complete and verified.

## Files written — `workspace/implementation/`

| file | lines |
|---|---|
| `start.sh` (executable) | 10 |
| `requirements.txt` | 1 |
| `app.py` | 72 |
| `db.py` | 235 |
| `errors.py` | 102 |
| `response.py` | 81 |
| `middleware.py` | 320 |
| `services/__init__.py` | 0 |
| `services/calc.py` | 524 |
| `services/scoring.py` | 241 |
| `services/cascade.py` | 318 |
| `routes/__init__.py` | 0 |
| `routes/listing.py` | 23 |
| `routes/ops.py` | 37 |
| `routes/organizations.py` | 138 |
| `routes/methodology.py` | 479 |
| `routes/filings.py` | 141 |
| `routes/governance.py` | 233 |
| `routes/cycles.py` | 476 |
| `routes/corrections.py` | 219 |
| `routes/appeals.py` | 217 |
| `routes/complaints.py` | 349 |
| `routes/publications.py` | 41 |
| **total** | **4257** |

## Endpoints
**58 of 58 registered, zero duplicates** (verified by introspecting `middleware.ROUTES`): 2 ops/clock, 5 organizations, 12 methodology/comments/grants, 3 filings, 7 governance/standards, 10 rating-cycles, 5 corrections, 5 appeals, 6 complaints, 2 publication-records, plus the standard-evaluation detail read.

## Boot confirmation
`PORT=51838 bash start.sh` boots in <5 s, binds `0.0.0.0`, serves `GET /organizations` → `HTTP 200` with an empty array, then was killed by its exact recorded PID (no `pkill` was used against a shared pattern). Confirmed programmatically that **no entity is seeded at boot** — every one of the 13 collections is empty and the logical clock starts at `2026-08-01T00:00:00Z`; state is wiped completely on every re-invocation.

## End-to-end verification (three scripted scenarios, all green)
1. **Happy path**: org → methodology draft/open/close/adopt → cycle → 3 filings validated → governance profile + evaluate → score → breakdown → dimension override → open-org-review → correction claim/reject → appeal / panel / DENY → publish → publication ledger + rating trend → complaint triage/resolve/reverse.
2. **Ladder + variants**: 401/403/404/400 spot checks, period overlap rejected vs adjacency accepted, `ERR_GOVERNANCE_NOT_EVALUATED` returned before `ERR_NO_VALIDATED_FILING` (ladder order 12 < 30), `UNRATED` grade at 58.33 % completeness, waive/revoke-waiver round trip, `GOVERNANCE_DISCLOSURE` correction ACCEPT rewinding the cycle to `DATA_COLLECTION` with round 1, complaint penalty ceiling (`11` → 422 at MEDIUM tier, `4` → 200) with the full 4-hop cascade onto the open cycle, reversal, all three triage forks, withdrawal + terminal re-withdraw refusal.
3. **Transition grants**: superseding version with reweighted dimensions → adopt blocked by `ERR_UNRESOLVED_COMMENTS` until the comment was disposed → adoption produced a grant with `projected_score_delta -7.84`, `trigger_reason WEIGHT_CHANGE`, org `transition_grace_until` propagated → retired pin refused without the flag (`ERR_METHODOLOGY_NOT_ADOPTED`) and accepted with it, moving the grant `ACTIVE` → `CONSUMED`.

## Key interpretation decisions (all traceable to PRD prose)
- **PRD §2.8's numbered ladder beats narrative order** ("Checks are evaluated in one fixed ascending order, and the **first** failing check determines the response... This ordering is observable and is part of the contract"). So on score, governance (12) precedes filing sufficiency (30); on adopt, window conflict (17) precedes unresolved comments (24); on dimension-overrides, state (8) → OCC (9) → assigned analyst (11).
- Publish order: state → SoD (10) → completeness (31) → publishability (32, which also bars any `STALE` row per §3.9/§3.6); a null `correction_deadline_at` yields `ERR_CYCLE_NOT_PUBLISHABLE`.
- Correction-acceptance **hop 4** (zeroing `failed_standard_count` / the profile's four counts) fires only on the `GOVERNANCE_DISCLOSURE` path, because the PRD says it is "caused by hop three deleting the standard rows".
- `raw_points <= max_points` is checked after FK resolution (it needs the row) but before the state check, since it cannot be evaluated at the check-5 slot.
- Withdrawal executes exactly the side-effect list §3.9 enumerates (stale rows, rejected corrections, dismissed appeals with `decision_note` `cycle withdrawn` and null `decided_by_user_id`) and does not recompute scores.
- `score-breakdown` derives `provisional_band`/`final_band` and both penalties from the **stored** weighted sums, so the read is always internally consistent with the persisted score families.
- `target_field_name` on a correction is validated against the union of filing and governance-profile input fields, per "must be one of the input fields of a filing record or of a governance profile".

## Step 5: Generate unit tests — 2026-09-05T09:00:00.000Z

Both queues are now fully translated and all verification passes are green.

## Deliverables (both at the TASK ROOT, not under `workspace/`)

`test_helpers/` — 2714 lines total: `__init__.py` 46, `api_client.py` 335, `api_errors.py` 117, `assertions.py` 372, `constants.py` 122, `factories.py` 275, `fixtures.py` 894, `test_users.py` 67, `types.py` 486

`test_suite/` — `conftest.py` 67 plus 26 test modules (7106 lines): test_01 123, test_02 142, test_03 119, test_04 272, test_05 231, test_06 138, test_07 190, test_08 159, test_09 193, test_10 238, test_11 361, test_12 407, test_13 52, test_14 345, test_15 459, test_16 396, test_17 276, test_18 263, test_19 261, test_20 288, test_21 437, test_22 403, test_23 379, test_24 487, test_25_optimistic_concurrency_and_pinning.py 374, test_26_immediate_consistency.py 118.

## Test counts

- **123 tests total**, all tagged with exactly one `Design:` line, no untagged/dual-tagged/dangling tags.
- **Queue A (Difficulty, §1.8): 46 tests** covering all 18 instances of the difficulty index, 1:1 coverage with no extras.
- **Queue B (Corner, §1.9): 77 tests**, one per live instance. Machine-checked against the index: 78 live instances, 77 tagged, zero duplicates, zero tags pointing at non-existent instances.

Per-section queue B: entities 24/24, state_machines 13/14, calculations 13/13, validations 10/10, endpoints 8/8, rbac 5/5, cross_cutting_complexity_layers 3/3, consistency_model 1/1. Stubs (13) received no tests, as required.

## Skips

One instance only — `Corner/state_machines/appeal_decide_before_panel_assigned_rejected`: **not uniquely derived**. §2.8 check 2 (role admission) precedes check 8 (state precondition), so an `AppealPanelist` deciding a `FILED` appeal they are not seated on gets `ERR_ROLE_NOT_PERMITTED`, not the design's `ERR_APPEAL_STATE_INVALID`. Left as a gap; not weakened, no xfail/skip marker.

## Design-literal defects corrected against the PRD

- `occ_rule_dimension_override_stale_cycle` asserts `${sum2} == 84.42` for ACCOUNTABILITY back at 21/24. The PRD arithmetic is 29.00 + 21.88 + 20.00 + 13.75 = **84.63**, composite 83.13. Used the correct figure.
- `occ_rule_filing_create_stale_organization` uses `source_kind: "FORM_990"` (not in the PRD enum) and expects filing status `SUBMITTED` (§3.3: "`status` starts at `RECEIVED`"). Used `PUBLIC_FILING` and `RECEIVED`.
- Its closing "`${first_row}` present" was translated as a set-membership assertion rather than positional ordering: both FY2025 rows share `fiscal_year`, `source_precedence` and — because `created_at` reads the logical clock, which does not move in that test — `created_at`, so §3.3's "created_at is the only tie-break" leaves the row order undefined. Total count, both statuses and both precedences are still asserted.

## Verification

`python3 -m compileall -q test_suite` clean; citation audit `tests=123 problems=0` (every quote survives a literal grep of `workspace/PRD.md`); section-label check `bad=0`; AST unused-import sweep clean; no `skip`/`skipif`/`xfail`/`pytest.mark`, no mention of "scaffold"; `__pycache__` removed. `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation` — no stray `workspace/test_helpers/` or `workspace/test_suite/`, and `workspace/implementation/`, `workspace/PRD.md` and `worklog.md` were never written.

`test_helpers/fixtures.py` was extended with a backward-compatible `creator_headers` kwarg on `setup_scored_cycle`; `adopt_successor_methodology` accepts explicit weight and `effective_from` overrides.

## Step 7: Run tests and iterate — 2026-09-05T09:34:00.000Z

Clean. Everything is in place, `worklog.md` untouched, no seeded data or on-disk persistence introduced.

## Summary

**Iterations run:** 2 (each a full 8-round parallel sweep). Iteration 1: 121/123 in all 8 rounds, the same 2 tests failing deterministically in every round (no flakiness, no load-induced failures). Iteration 2: **123/123 in all 8 rounds.**

**Tests deleted:** none wholesale. One assertion removed under STEP 1a PRD silence + STEP 1c partial-coverage handling:

- `test_suite/test_20_priority_conflicts_and_cardinality.py` — `test_a_seat_is_illegal_only_relative_to_the_cycles_own_stored_role_holders` asserted `seated["panel_assigned_at"] == "2026-09-01T00:00:00Z"` (failed `KeyError: 'panel_assigned_at'`). The token `panel_assigned_at` appears **zero times** in PRD.md. §3.7 enumerates the Appeal's fields exhaustively (`filed_by_org_user_id`, `filed_at`, `deadline_at`, `panel_member_user_ids`, `decided_by_user_id`, `decided_at`, `decision_note`) and the seating transition verbatim as "The appeal moves `FILED` → `PANEL_ASSIGNED`, stores the panel and advances its `version` counter by one" — no such timestamp. **Category: response-field silence** (test asserted a response-visible attribute the PRD never names). PRD covers the rest of the test (the four composition refusals, the reviewer-id-is-legal-while-null case, status, panel membership, version 2, cycle unchanged), so only the uncovered assertion was removed.

**Fixes applied to `test_helpers/`:** none. The fixtures, factories and role-header builders were audited against PRD (money as whole-cent JSON numbers, full ISO-8601 instants, correct role-to-resource ownership, conditional `target_fiscal_year`/`target_source_kind` omission for `GOVERNANCE_DISCLOSURE`) and were faithful.

**Fixes applied to `implementation/`:**

- `workspace/implementation/routes/cycles.py`, `create_cycle` — after a `RETIRED` pin spends the organization's `ACTIVE` `TransitionGrant` (`ACTIVE` → `CONSUMED`), the code now calls `cascade.refresh_active_grace(organization)`. It previously left the organization's `transition_grace_until` stuck at the spent grant's deadline, violating §3.3's verbatim invariant on that maintained roll-up: "`transition_grace_until` mirrors the `grace_until` of the organization's `ACTIVE` transition grant and is null when there is none." (Failure was `AssertionError: assert '2026-12-21T00:00:00.000Z' is None` in `test_23_computed_reads_and_operator_sweeps.py::test_the_transition_sweep_expires_grace_strictly_after_the_deadline`.) Deliberately no organization `version` bump was added: §3.2 specifies the parallel clearing on the sweep path ("For every organization the sweep touches, `transition_grace_until` is cleared back to null when that organization holds no remaining `ACTIVE` grant") while enumerating a version advance only for the grant row, so the existing no-bump convention is the PRD-faithful one and stays consistent with `routes/ops.py`.

**Orchestrator verification:** all 8 `workspace/implementation/results.$i.json` re-read independently — every round reports `passed=123 total=123 failed=0`, all written at the same wall-clock minute (09:26). Step 8 is therefore NOT skipped (1 implementation fix + 1 assertion removal).

## Step 8: Finalize PRD — 2026-09-05T09:37:00.000Z

`PRD_FINALIZED.md` is written. Four in-paragraph edits, no new sections, no lines added or removed.

**Line counts:** PRD.md 462 lines / 124,741 bytes → PRD_FINALIZED.md 462 lines / 125,459 bytes. Line delta 0.0%; byte delta +0.58% (+718 bytes, 4 modified paragraphs out of 462 lines = 0.87% of lines touched).

**Changes**

- §3.2 (grant consumption) — revise — the consumption sentence now states that spending an `ACTIVE` grant on a retired-pin cycle creation also refreshes the organization's `transition_grace_until`, clearing it to null when no `ACTIVE` grant remains, and that this refresh does **not** advance the organization's `version` — `routes/cycles.py:171-177` + `services/cascade.py:108-115`.
- §3.2 (transition sweep) — revise — appended that the sweep's identical clearing likewise leaves the organization's `version` untouched — `routes/ops.py:33-36` (no `touch(organization)`).
- §3.3 (organization roll-ups) — revise — softened the absolute "mirrors … and is null when there is none" invariant to: later value on a new mint (per §2.5), cleared to null once no `ACTIVE` grant remains, never recomputed downward while one remains — `routes/methodology.py:336-342`, `services/cascade.py:108-115`.
- §3.7 (panel seating) — insert — the seating writes no field on the appeal beyond `updated_at`/`version`, so there is no seating timestamp to read back — `routes/appeals.py:154-157` (and `routes/appeals.py:67-82` for the Appeal's full field set).

**Per-edit pre-edit search log**

1. **Grant consumption / grace roll-up.** (a) Subject: writes to `Organization.transition_grace_until` and whether they bump the org `version`. (b) Enumerated by `grep -rn "transition_grace_until\|refresh_active_grace\|grace_until"` over all impl modules — the complete write set is `routes/organizations.py:48` (init null), `routes/methodology.py:336-342` (adoption hop 3: later-of, **does** `touch(organization)`), `routes/ops.py:28-36` (sweep clearing, no touch), `routes/cycles.py:171-177` (consumption clearing, no touch), plus `services/cascade.py:108-115` (`refresh_active_grace`, which only nulls when zero `ACTIVE` grants remain and never re-mirrors). Also grepped `touch(organization|org` to confirm the only org version bumps are filings (`filings.py:85`), complaints (`complaints.py:247,325`), adoption (`methodology.py:342`) and publication roll-ups (`cascade.py:301`). (c) Adjustment: wrote "clearing it back to null when the organization holds no remaining `ACTIVE` grant" rather than "recomputes/mirrors the remaining grant", because `refresh_active_grace` leaves a non-null value alone when another `ACTIVE` grant survives; and scoped the no-version-bump claim to this refresh only, so the adoption path's documented org bump is untouched.
2. **Sweep clearing / version.** (a) Subject: same field + org version on the operator sweep path. (b) Same enumeration as (1); read `routes/ops.py` in full. (c) None needed — wording mirrors the already-present sweep sentence and adds only the version fact.
3. **§3.3 roll-up invariant.** (a) Subject: the universal claim about `transition_grace_until`. (b) Same enumerated write set as (1), plus §2.5's existing "later of" prose to keep the cross-reference honest. (c) Widened/softened: the original strict mirror would tell a fresh implementer to recompute the max over surviving `ACTIVE` grants (diverging from impl when a grant is consumed/expires while a longer- or shorter-dated one remains); the new wording states only what the impl does — later-of on mint, null when none remain, never recomputed downward.
4. **Panel seating fields.** (a) Subject: which fields exist on / are written to an `Appeal` at seating. (b) Enumerated `routes/appeals.py` in full (creation field list at 67-82, `assign_panel` at 132-157, `decide` branches at 160+), grepped `panel_assigned_at` repo-wide (zero hits) and `panel` across `routes/`; confirmed `db.touch` (`db.py:231-235`) is the only other field writer (`updated_at`, `version`). (c) Adjustment: phrased as "no further field … beyond the `updated_at` that §2.4 refreshes" instead of "records no timestamp", which would have contradicted §2.4's universal `updated_at` rule; scoped the claim to the appeal row only, so the cycle/other rows are not implicitly constrained.

**Orchestrator verification:** `cmp PRD.md PRD_FINALIZED.md` confirms the files differ (Step 8 genuinely ran).

## Step 9: Complete PRD — 2026-09-05T10:05:00.000Z

Run as **three sequential module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md` (a single agent scanning all 4257 impl lines at once has historically no-op'd on this pipeline). Pass 1 owned the Step-0 `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes 2 and 3 were forbidden to copy.

**Final totals:** PRD_FINALIZED.md 462 lines / 125,459 chars → PRD_COMPLETED.md 462 lines / **142,677 chars** (+17,218 chars, 0 new lines, 0 new sections — every edit in-paragraph). 50 changed lines vs PRD_FINALIZED.md. **60 edits total: 53 ambiguity-pins, 7 mismatch-revisions.**

### Pass 1 — app.py, db.py, errors.py, response.py, middleware.py, routes/{listing,ops,organizations,methodology}.py
Step 0 cp executed before any edit. 133,037 chars after pass; 16 ambiguity-pins, 4 mismatch-revisions:
- §2.1 auth — revise — mismatch — whitespace-only `X-User-ID`/`X-User-Role` also yield `ERR_UNAUTHENTICATED` — middleware.py:281-284
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 24 lowercase-alphanumeric chars — response.py:15-16
- §2.2 — revise — mismatch — `api_request_timestamp` reads the logical clock (not wall clock), on error responses too — response.py:36
- §2.2 `data` — insert — ambiguity — numeric figures serialise as JSON numbers with no trailing zeros; declared scale governs arithmetic, not rendered digits — response.py:19-29
- §2.3 — insert — ambiguity — every ordering ends in an implicit write-order tie-break; the tie-break field is never exposed — listing.py:6-7, db.py:226
- §2.3 — revise — mismatch — `has_more` = offset + rows returned < `total_count`; rating-trend read is `response_type` `object` yet carries all four pagination fields — response.py:51-68, organizations.py:110
- §2.5 — revise — ambiguity — `/_clock/set_current_utc` answers a `data` object whose only field is `current_utc` — ops.py:18
- §2.8 check 4 — insert — ambiguity — body-reached ownership uses the raw body's `rating_cycle_id` pre-validation; absent/non-string/unresolvable defers to checks 5/7 — middleware.py:258-268
- §2.8 check 5 — insert — ambiguity — explicit `null` == absent; string/float coercion; declared scale quantizes half-up; lenient ISO forms normalised to UTC; unparseable body treated as empty; non-object JSON body is `ERR_INVALID_REQUEST`; GET/DELETE bodies ignored — middleware.py:54-89,113-145,178-202
- §2.8 check 6 — revise — ambiguity — pagination validated on list endpoints plus the object-shaped rating-trend read only — middleware.py:304-305
- §2.9 — insert — ambiguity — unrouted path → `ERR_ORGANIZATION_NOT_FOUND` (404); declared path with undeclared method → `ERR_INVALID_REQUEST` 405; trailing slash tolerated — app.py:27,38-49
- §2.9 — insert — ambiguity — filters match by exact equality, never vocabulary-checked; unparseable integer filters match nothing; undeclared query params ignored — listing.py:16-23
- §3.1 — insert — ambiguity — `supersedes_version_id` stored verbatim, not FK-checked — methodology.py:60,89
- §3.1 — revise — mismatch — no state precondition on dispose; parent counts always recomputed by counting — methodology.py:134-141,437-446
- §3.1 — insert — ambiguity — partial weight set is `ERR_INVALID_REQUEST` decided *before* the status precondition, while `ERR_WEIGHTS_NOT_NORMALIZED` is decided after — methodology.py:180-213
- §3.2 — insert — ambiguity — the three adoption gates fire in ladder order (8 → 17 → 24) — methodology.py:261-269
- §3.2 hop one — insert — ambiguity — no predecessor / predecessor not `ADOPTED` ⇒ hops two and three do not run at all — methodology.py:279-289
- §3.2 hop three — revise — mismatch — `transition_grace_until` becomes the *later* of existing and new `grace_until`; the `methodology_pin_locked` re-assertion advances neither the cycle's `version` nor `updated_at` — methodology.py:336-348
- §3.2 sweep — insert — ambiguity — sweep `data` carries only `expired_grant_count` and `expired_grant_ids`, in grant-mint order — ops.py:25-37
- §3.9 — insert — ambiguity — rating-trend roll-ups echoed as stored; each `points` element is a complete publication record; window cut after the newest-first reversal — organizations.py:96-110

### Pass 2 — services/{calc,scoring,cascade}.py, routes/{filings,governance}.py
137,673 chars after pass; 11 ambiguity-pins, 3 mismatch-revisions:
- §3.3 — revise — mismatch — "`created_at` is the only tie-break" contradicted the selector's third key; equal-`created_at` candidates fall back to §2.3 write order, `id` never consulted — calc.py:61
- §3.3 — insert — ambiguity — `decision` enum literals; empty `rejection_code` fails; conditional-requirement failure precedes the `RECEIVED` gate; a code sent with `ACCEPT` is discarded — filings.py:112-119
- §3.4 — insert — ambiguity — `independent_board_member_count > board_member_count` is `ERR_INVALID_REQUEST` evaluated *after* body FK resolution — governance.py:38
- §3.4 — insert — ambiguity — evaluate preconditions ordered profile-status-first — governance.py:100-104
- §3.4 — insert — ambiguity — `observed_value` stringification (lowercase booleans, plain integers, ratio at full 4-decimal scale, 3-fractional-digit instants) — calc.py:155-224
- §3.4 — insert — ambiguity — `waiver_reason` ≥1 char, not blank-checked — governance.py:166
- §3.4 — insert — ambiguity — the row's `result` is tested before the cycle's status on both waive and revoke — governance.py:187-219
- §3.4 — insert — ambiguity — `revocation_note` accepted but persisted on no field — governance.py:167,214-225
- §3.4 — insert — ambiguity — governance substitution coercions; `evaluated_at` cleared while `independence_ratio` is left standing; cross-kind `target_field_name` writes no field yet still resets the profile — cascade.py:162-181
- §3.5 — insert — ambiguity — a re-score also clears `override_reason` and `overridden_by_user_id` — scoring.py:194-195
- §3.5 — revise — mismatch — cycle-level `data_completeness_pct` rounds only the completed sum; declared as the one exception to §2.6 — calc.py:364-368
- §3.5 — insert — ambiguity — scoring recomputes `accountability_penalty_points` from substantiated-complaint penalties; each pre-existing dimension row's `version` advances by exactly one — scoring.py:156,209-212
- §3.6 — revise — mismatch — "final figures stand as last written" was wrong for `standards_penalty_points`, always rewritten from the final variant — scoring.py:110
- §3.7 — insert — ambiguity — filing substitution details (clock-sourced timestamps, eleven monetary figures copied, `source_precedence` re-derived, unparseable numerics keep the copied figure, truncation toward zero, no check-29 re-validation, cross-kind name yields a verbatim clone, missing target is a silent no-op) — cascade.py:121-159

### Pass 3 — routes/{cycles,corrections,appeals,complaints,publications}.py
142,677 chars after pass; 26 ambiguity-pins, 0 mismatch-revisions (within this module set the impl never outright contradicted the PRD):
- §2.8 check 32 — revise — added the "no dimension row is `STALE`" condition and pinned it below check 31 — cycles.py:287-299
- §3.2 — insert — with several matching live grants, the earliest-minted is consumed — cycles.py:82-87,171
- §3.5 — insert — `assigned_analyst_user_id` non-blank; `use_transition_grant` defaults false; org FK before methodology FK; `period_end > period_start` decided ahead of the methodology/grace/overlap tests — cycles.py:51-96
- §3.5 — insert — missing both validated filing and evaluated profile answers `ERR_GOVERNANCE_NOT_EVALUATED` (12 outranks 30) — cycles.py:226-232
- §3.6 — insert — score-breakdown re-derives bands/penalties on the read; never-scored cycle answers nulls, empty `final_included_dimensions`, zero counters — cycles.py:342-392
- §3.6 — insert — `override_reason` 1–500 non-blank — cycles.py:425-431
- §3.6 — insert — `max_points` bound read off the resolved row, so both override verdicts fall after body FKs and before the cycle's status — cycles.py:445-461
- §3.7 — insert — `proposed_value` 1–500 / `target_field_name` 1–100 non-blank; conditional fields stored null on a governance target; both body failures after the cycle FK, before its status — corrections.py:39-99
- §3.7 — insert — correction `decision_note` ≤ 2000 — corrections.py:173
- §3.7 — insert — rewind hop four fires on the `GOVERNANCE_DISCLOSURE` path alone — cascade.py:316-317
- §3.7 — insert — no linkage tested between an appeal's cycle and its contested correction — appeals.py:22-48
- §3.7 — insert — a non-string/blank `panel_member_user_ids` element is `ERR_INVALID_REQUEST` before any composition test — appeals.py:116-122
- §3.7 — insert — appeal `decision_note` ≤ 2000; `PANEL_ASSIGNED` status test precedes the panel-seat test — appeals.py:182-186
- §3.8 — insert — `triage_note`, `finding_note`, `referred_to`, `reversal_reason`, `resolved_at` all null at intake — complaints.py:71-93
- §3.8 — insert — `triage_note` ≤ 2000, `referred_to` ≤ 200 non-blank — complaints.py:126-134
- §3.8 — insert — the `referred_to` requirement precedes the `INTAKE` status test; ignored on other dispositions; `triage_note` stored on all three branches — complaints.py:148-174
- §3.8 — insert — `finding_note` ≤ 2000 — complaints.py:185
- §3.8 — insert — with no penalty target, the org's `substantiated_complaint_count` and `version` still advance — complaints.py:244-250
- §3.8 — insert — an already-`STALE` row absorbs further penalty and stays `STALE`; a never-scored target makes hop two a no-op and hop three stores 0.00/0.00/0.00 and `DOES_NOT_MEET` — complaints.py:252-278
- §3.8 — insert — `reversal_reason` 1–500 non-blank — complaints.py:287-295
- §3.8 — insert — an `OVERRIDDEN` accountability row keeps its status and reason on reversal while `raw_points` is recomputed away — complaints.py:330-343
- §3.8 — insert — reversal restores neither the cycle's `status` nor the terminated corrections/appeals; a null `penalized_rating_cycle_id` reverses without error — complaints.py:311-328
- §3.9 — insert — `publishing_reviewer_note` ≤ 2000, validated but stored nowhere — cycles.py:266-268
- §3.9 — insert — an unfiltered ledger read sorts all organizations together by `sequence_number`, ties by write order — publications.py:30
- §3.9 — insert — `withdrawal_reason` 1–500 non-blank — cycles.py:305-313
- §3.9 — insert — withdrawal retains `review_opened_at` / both deadlines and recomputes neither composite family — cycles.py:323-333

### Closing verification (pass 3 + orchestrator)
- 462 lines; last line is still `| ERR_DATA_COMPLETENESS_TOO_LOW | 409 |`, the final row of the §5 table — ends at a real section boundary, not truncated.
- `cmp PRD_FINALIZED.md PRD_COMPLETED.md` → differs (the scan genuinely ran; not a byte-identical no-op).
- Sampled earlier-pass markers all survive: §2.2 `api_request_id`, §2.3 `has_more`, the Step 8 §3.2 no-version-bump clause, the Step 8 §3.7 panel-seating clause, pass 2's §3.3 "never consults `id`", §3.5/§3.6/§3.7 pass-2 edits, pass 1's §3.9 clause. 50 changed lines = 29 from passes 1–2 + 21 from pass 3; nothing clobbered.
- Orchestrator confirmed `workspace/implementation/` and `test_suite/`/`test_helpers/` have no file modified after 09:22 (Step 7's last fix), so Steps 8 and 9 were documentation-only and the verified 123/123 × 8-round sweep still describes the shipped artifact.

**PIPELINE COMPLETE.**
