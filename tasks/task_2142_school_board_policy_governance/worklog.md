## Step 1: Create Task Directory — 2026-08-23T00:00:00.000Z

Created `tasks/task_2142_school_board_policy_governance/` and `tasks/task_2142_school_board_policy_governance/workspace/`. Index 2142 derived from highest existing `task_NNNN_*` (2141) + 1.

## Step 3: Copy Shared Files — 2026-08-23T00:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2142_school_board_policy_governance/workspace/INSTRUCTION.md` (1424 bytes).

## Step 2: Generate Scaffold — 2026-08-23T00:00:00.000Z

All three scaffold artifacts are generated, self-consistent, and lint-clean.

## Files

| Path | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2142_school_board_policy_governance/SCAFFOLD.yaml` | 3017 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2142_school_board_policy_governance/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1946 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2142_school_board_policy_governance/SCAFFOLD_CORNER_DESIGN.yaml` | 3724 |

## Scaffold contents (§1.0–§1.7)

- **Profile**: expert; `compliance_audit` × `multi_party_negotiation`; graph topology; cyclic state-machine shape; `segregation_of_duties` roles; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, ops_run_checkpoint. `api_prefix: /governance`.
- **14 entities**, 18 FKs (incl. a self-referential `Meeting.minutes_approved_at_meeting_id`)
- **11 state machines** (PolicyVersion cyclic + emergency branch, Meeting with two parallel axes `status` x `minutes_status`, WaiverRequest branching, AgendaItem, PublicComment, LegalMandate, SuperintendentEvaluation cyclic, ManualPublication, BoardMember, CommitteeAssignment, ConflictDisclosure)
- **2 concurrency rules** (OCC on `Policy.version` and `Meeting.version`), **3 named conservation invariants**
- **7 calculations**, **34 validations**, **52 endpoints**, **58 errors**, **8 roles**

## Design indices

- **§1.8**: 23 instances across all 9 rule_ids — dual_variant 2, combinatorial 3, non_linear 3, cascade 2, priority_pair 3, boundary 3, cross_entity 3, temporal_overlap 2, compensating_invariant 2.
- **§1.9**: 91 instances across all 9 guide sections (entities 13, state_machines 14, calculations 12, validations 27, endpoints 5, errors 5, rbac 8, cross_cutting 6, consistency 1); 6 are `excluded_because` stubs, all citing real §1.8 instance names.

## Verdict block (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     14
  §1.8 instances scanned:     23
  §1.9 instances scanned:     82
  Calls scanned (§1.8+§1.9):  833

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Extra audits run beyond the linter

Zero unbound `${var}` across 833 calls; instance names unique across both files; every one of the 58 error ids is referenced by at least one design instance; all 8 roles appear as an `as:` actor; no forbidden concurrency vocabulary; no fuzzy selector adjectives; design keys appear only in their own files.

Three reachability defects were found and fixed during generation rather than papered over: `ERR_SECOND_READING_SAME_MEETING` was unreachable (agenda-build eligibility for second readings relaxed to `{DRAFT, FIRST_READING_PASSED}`, and its priority moved to 53 so it outranks the minutes rule at 54); `ERR_VOTE_TALLY_EXCEEDS_SEATS` was structurally impossible (voters ⊆ attending ⊆ seated) so the validation row and error were deleted; `MAX_SPEAKERS_PER_ITEM` was lowered 20 → 5 so `ERR_SPEAKER_LIMIT_REACHED` is testable in a short chain.

## Step 4: Generate PRD — 2026-08-23T00:00:00.000Z

PRD generated and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2142_school_board_policy_governance/workspace/PRD.md` — 445 lines, 12,323 words.

**Structure:** §1 Introduction (3 paras) · §2 with 10 subsections (2.1 RBAC, 2.2 verbatim envelope, 2.3 Pagination, 2.4 Logical Clock, 2.5 Identity/timestamps/version, 2.6 OCC, 2.7 Path resolution + full refusal ladder, 2.8 Rounding, 2.9 Three-phase compliance recompute, 2.10 Conservation invariants) · §3 with 9 workflow subsections · §4 endpoint table (4 columns) · §5 error table (2 columns). File ends at §5 — no audit footer.

**Coverage verified programmatically against SCAFFOLD.yaml:**

| Element | Scaffold | In PRD |
|---|---|---|
| Endpoints (`| \`path\` |` rows in §4) | 52 | 52 |
| Error IDs in §5 table | 58 | 58 |
| Error IDs also named in §2/§3 prose | 58 | 58 |
| Validations (all 34 priorities in the §2.7 ladder + trigger prose) | 34 | 34 |
| State machines / all transitions | 11 | 11 |
| Calculations (formulas in precise prose) | 7 | 7 |
| Entity field names in backticks | 134 | 134 |
| request_body identifiers | 70 | 70 |
| query_params identifiers | 19 | 19 |
| Sweep output-shape keys | 6 | 6 |
| Roles (exact spelling + `identity:` translated) | 8 | 8 |
| Concurrency rules (OCC) | 2 | 2 |
| Invariants | 3 | 3 |
| All state + enum values as backticked UPPERCASE | — | 0 missing |

**Hard contracts:**
```
Field coverage check: entities 134/134, request_body 70/70, query_params 19/19, output shape 6/6, 0 missing — PASS
Rule coverage check: validations w/ priority 34 expressed (ladder + inline); OCC 2/2 (write_endpoint + expected_policy_version / expected_meeting_version + ERR_STALE_VERSION 412);
  transitions 47/47 incl. the unreachable TABLED->POSTED noted as unreachable; calculations 7/7 full formulas incl. pinned rounding orders;
  validation conditions 34/34 matchable to error_id; endpoint side_effects / applies_to expressed; field structured content (types, defaults, initial values) on owning entities;
  sibling-branch symmetry 6 groups (first_come_capped vs equal_split, midyear vs summative, regular vs emergency adoption, RECOMMEND_GRANT vs RECOMMEND_DENY,
  forward_dated vs clipped grant, sweep_scoped vs policy_scoped) at equal density — PASS
Path purity check (§3 only): 951 backtick tokens scanned; 0 starting with "/", 0 bare HTTP methods, 0 method+path — PASS
§2.2 matches the canonical file byte-for-byte — PASS
```

**One item needing orchestrator attention:** `EFFECTIVE_DELAY_DAYS` is referenced twice in SCAFFOLD.yaml (`PolicyVersion.effective_date` and the second-reading adoption side-effect) but is **never bound to a numeric value anywhere in the scaffold** — no `constants:` block defines it. The PRD binds it to **30 days** ("`effective_date` is set to 30 days after `adopted_at`"; emergency adoptions use 0). If the withheld design indices bind it to a different number, reconcile before test generation or the `effective_date` assertions will diverge.

**Orchestrator reconciliation (post-Step-4):** checked the withheld design indices for the binding. `SCAFFOLD_DIFFICULTY_DESIGN.yaml:915` asserts `adopted_at == 2026-09-24T18:00:00Z` with `effective_date == 2026-10-24T18:00:00Z` (= +30 days), and `SCAFFOLD_CORNER_DESIGN.yaml:1541` asserts an emergency adoption at `2026-08-02T18:00:00Z` with `effective_date == 2026-08-02T18:00:00Z` (= +0 days). Both match the PRD's binding of 30 / 0 days exactly. **No divergence — no reconciliation edit required.**

## Step 6: Generate Implementation — 2026-08-23T00:00:00.000Z

Implementation complete and verified.

## Files written (`workspace/implementation/`, 2873 lines total)

| File | Lines | Role |
|---|---|---|
| `app.py` | 83 | Flask app, blueprint registration, error handlers, per-request lock |
| `store.py` | 259 | In-memory dicts, logical clock, id/seq, `touch`/`set_fields`, serializers |
| `errors.py` | 78 | `ApiError` + the 58-entry error->HTTP catalogue |
| `resp.py` | 53 | `meta`/`response_type`/`data` envelope + pagination block |
| `auth.py` | 62 | `X-User-ID`/`X-User-Role` validation, RBAC role sets, president identity |
| `validate.py` | 218 | Body-shape validators, pagination, path/FK resolution -> not-found codes |
| `calc.py` | 456 | 7 calculations, 3-phase compliance recompute, cascades, constants |
| `routes_board.py` | 323 | Trustees, committees, seats, disclosures |
| `routes_policy.py` | 247 | Policies, versions, legal mandates |
| `routes_meeting.py` | 234 | Scheduling, notice, open, adjourn, minutes axis |
| `routes_agenda.py` | 341 | Agenda items, roll-call vote + adoption/waiver cascades, speaker cards |
| `routes_waiver.py` | 164 | Waiver filing, committee review, revocation |
| `routes_ops.py` | 346 | Evaluations, ratings, publications, sweep, clock |
| `start.sh` | 8 | Guarded `pip install`, `exec python3 app.py`, `0.0.0.0:$PORT` |

## Coverage
- **Endpoints: 52 / 52** (matches `grep -c "^  - method:" SCAFFOLD.yaml`).
- **Error IDs: 58 / 58** wired — every catalogue entry is actually raised in route/validation code (verified by set-difference against `errors.py`).
- 14 entities, 11 state machines, 7 calculations, 34 validations, 8 roles implemented.

## Key fidelity decisions
- Refusal ladder implemented in §2.7 order per endpoint (e.g. OCC at step 8 outranks agenda-lock at 15; `ERR_SECOND_READING_SAME_MEETING` before `ERR_MINUTES_NOT_APPROVED`; quorum before `ERR_MEETING_NOT_YET_DUE` at open).
- `version` bumps are deduplicated per request via a dirty-set, so a multi-hop cascade touching the same policy yields exactly +1; newly created records are pre-marked so they stay at version 1.
- Money-free but score-precise: `Decimal` + `ROUND_HALF_UP` for the two composite scores (domain mean rounded first, then weighted, renormalized, rounded again); all minute/day math is integer floor.
- Allocation ordering is `(submitted_at, created_at, speaker_name)` — with a frozen logical clock all cards share timestamps, so lexicographic `speaker_name` is load-bearing.
- Storage is in-memory dicts only; **nothing is seeded** — verified on a fresh boot that all 8 list endpoints return `total_count: 0` and the clock reads `2026-08-01T00:00:00.000Z`.
- Requests are serialized under a `threading.Lock` with `threaded=True`, so read-modify-write sequences stay atomic while many connections are accepted (12 parallel reads verified).

## Gap worth flagging
PRD §3.2 says clearing a disclosure is blocked while an agenda item on that policy is `POSTED` on an `OPEN` meeting, but names **no error ID** for it. I return `ERR_INVALID_MEETING_STATE` (409) as the closest state-precondition code.

## Boot verification
Booted repeatedly via `PORT=<n> bash start.sh` and exercised three end-to-end smoke suites (full two-reading adoption + publication + sweep; emergency adoption + equal-split allocation + resignation/term-expiry cascades; waiver grant/revoke + failed-second-reading revision loop + concurrency). All assertions passed; all test servers have been stopped.

## Step 5: Generate Unit Tests — 2026-08-23T00:00:00.000Z

Generation complete. All audits pass.

## Files written

**`test_helpers/`** (2113 lines)
| file | lines |
|---|---|
| `__init__.py` | 33 |
| `types.py` | 510 |
| `api_client.py` | 190 |
| `api_errors.py` | 131 |
| `assertions.py` | 243 |
| `factories.py` | 164 |
| `constants.py` | 63 |
| `test_users.py` | 28 |
| `fixtures.py` | 751 |

**`test_suite/`** (4701 lines, 128 tests)
| file | lines | tests |
|---|---|---|
| `conftest.py` | 53 | — |
| `test_01_policy_register_and_versions.py` | 496 | 16 |
| `test_02_board_roster_and_committees.py` | 272 | 9 |
| `test_03_conflict_disclosures.py` | 179 | 5 |
| `test_04_meetings_notice_and_agenda.py` | 666 | 21 |
| `test_05_public_comment_allocation.py` | 579 | 14 |
| `test_06_roll_call_vote.py` | 389 | 10 |
| `test_07_adoption_cycle.py` | 381 | 8 |
| `test_08_policy_waivers.py` | 644 | 16 |
| `test_09_superintendent_evaluation.py` | 334 | 12 |
| `test_10_manual_publication_and_compliance.py` | 525 | 12 |
| `test_11_access_control_and_not_found.py` | 183 | 5 |

## Coverage

- **Queue A (Difficulty)**: 46 tests — all 23 §1.8 instances covered by exactly 2 tests each.
- **Queue B (Corner)**: 82 tests — all 82 non-stub §1.9 instances covered by exactly 1 test each.
- 9 `excluded_because:` stubs not translated; all 9 `difficulty_instance` cross-references verified to resolve to real §1.8 `name:` values.

## Instances SKIPPED

**None.** Every non-stub instance in both indices passed the PRD-first two-condition filter — the PRD verbatim-covers each asserted rule (error id, threshold, transition, side effect) and uniquely derives the outcome.

## One deviation from a design-index literal

`Corner/errors/first_reading_item_on_an_already_read_version_returns_not_eligible` asserts `HTTP status == 422`, but PRD §5's catalogue pins `ERR_POLICY_VERSION_NOT_ELIGIBLE` at **409**. Since the PRD is the contract the implementer sees, the test asserts the `error_id` through `validate_error()`, which cross-checks against the PRD-derived status map (409). The design index's 422 is a corner-design bug, not an implementable expectation.

## Verification performed

- `python3 -m py_compile` on every generated file — clean.
- `pytest --collect-only` — **128 tests collected**, no import or fixture errors.
- Automated audit script confirmed: every test docstring carries **exactly one** `Design:` tag resolving to a real, non-stub instance; every quoted PRD citation (>=6 words) survives a whitespace-normalized literal match against `workspace/PRD.md`; zero `skip` / `skipif` / `xfail` markers; zero occurrences of the word "scaffold" in generated code or comments.

## Step 7: Run Tests and Iterate — 2026-08-23T00:00:00.000Z

Clean sweep on the first iteration — no fixes were needed.

## Summary

**Iterations run:** 1 (single 8-round parallel stability sweep)

**Result:** All 8 concurrent rounds passed **128/128** — `failed=0, errors=0, skipped=0` in every round, ~166s per round. No test failed in any round, so there is no flakiness signal and no union failure set to triage.

**Tests deleted:** None. No test failed, so STEP 1's PRD-silence / unique-derivability filter was never triggered.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:** None.

### Audit performed while the sweep ran

Since no failures surfaced, I used the sweep's wall time to verify the two soft spots the generators flagged, plus the highest-risk PRD rules:

- **Soft spot 1 (PRD §3.2 disclosure-clear blocked while an agenda item on that policy is `POSTED` on an `OPEN` meeting, no error id named).** This is genuinely PRD-silent on the error id, but **no test exercises the blocked path** — `clear_disclosure` appears only in `test_suite/test_03_conflict_disclosures.py` (the `ERR_DISCLOSURE_ALREADY_CLEARED` case). The implementation's choice of `ERR_INVALID_MEETING_STATE` is therefore untested and cannot cause an unfair failure. No action required.
- **Soft spot 2 (422 vs 409 for `ERR_POLICY_VERSION_NOT_ELIGIBLE`).** Already correctly resolved at generation time: `test_helpers/api_errors.py` installs an HTTP status map that matches PRD §5 verbatim (`ERR_POLICY_VERSION_NOT_ELIGIBLE` -> 409), and tests assert the `error_id` through that map rather than the design index's 422.
- **Refusal-ladder conformance (PRD §2.7)** verified by reading against the code in `routes_agenda.py` (`record_vote`: POSTED -> MEETING_NOT_OPEN -> version/waiver eligibility -> recused -> quorum -> same-meeting -> minutes -> attendance -> duplicate voter), `routes_meeting.py` (`open_meeting`: MEMBER_NOT_SEATED -> QUORUM_NOT_MET -> MEETING_NOT_YET_DUE), and `routes_waiver.py` (`committee_recommendation`: identity binding before waiver-state check). All match the ladder's declared precedence.
- **No-seeding / in-memory contract** confirmed: `workspace/implementation/store.py` builds `db` as empty Python dicts on import with no seeded rows and no on-disk persistence, so `start.sh` re-invocation under `per-test-server` isolation wipes all state.
- **No `pytest.mark.skip` / `xfail` anywhere.** The one grep hit for "skip" is the word *skipping* inside a verbatim PRD quote in a docstring in `test_suite/test_07_adoption_cycle.py:96`, not a marker.

No files were modified in `test_suite/`, `test_helpers/`, or `workspace/implementation/`. The eight `results.${i}.json` files are left in `workspace/implementation/` as the sweep evidence.

**Orchestrator verification (post-Step-7):** independently re-read all 8 `results.*.json` — every round reports `passed=128, failed=0, errors=0, skipped=0, total=128`. Also ran a design-index leakage probe over `implementation/**/*.py` for literals that appear only in the withheld indices (`2026-09-24`, `2026-10-24`, `2026-08-02`, `BP-4119`, `BP-0900`, `2026-FALL`) — **zero hits**, so the green first sweep reflects a faithful PRD-only implementation, not an index leak.

## Step 8: Finalize PRD — SKIPPED — 2026-08-23T00:00:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits at the sites Step 7 would have targeted, so no `<step_7_diff>` exists to drive a finalizer pass. `PRD_FINALIZED.md` is intentionally absent; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-08-23T00:00:00.000Z

**Files**
- Source: `workspace/PRD.md` — 444 lines, 89,195 chars
- Output: `workspace/PRD_COMPLETED.md` — 444 lines, 91,085 chars (**+1,890 chars**, 9 lines revised in place, no lines added or removed, no new sections)

**Counts:** 9 ambiguity-pins, 0 mismatch-revisions. (Walked all 14 modules / 52 endpoints / 58 error ids; every other impl behavior — ladder ordering at every endpoint, all 7 calculations, both allocation variants, all 11 state machines, all cascades and sweep counters — was already pinned uniquely by PRD prose.)

**Changes**
- §2.3 Pagination — insert — ambiguity — non-integer `limit`/`offset` and out-of-enum filter query values are also `ERR_INVALID_REQUEST` — `validate.py:145-172` (`pagination`, `query_enum`)
- §2.3 Pagination — insert — ambiguity — `created_at` ties in list ordering break by server creation order — `store.py:153` (`sorted_rows` sorts on `(created_at, _seq)`)
- §2.5 Record Identity — insert — ambiguity — `version` increments at most once per request per record; a no-op write bumps nothing; a record created by the request stays at 1 — `store.py:109-145` (`create` pre-seeds `_dirty`; `touch` guards; `set_fields` only touches on real change)
- §2.7 Path Resolution — insert — ambiguity — an unresolvable rubric-rating id answers `ERR_EVALUATION_NOT_FOUND` (no rating-specific code) — `validate.py:464` (`_TABLE_ERROR["ratings"]`)
- §3.2 Disclosure clearing — revise — ambiguity — the open-meeting block names `ERR_INVALID_MEETING_STATE`; the item's policy resolves through its linked version or its linked waiver; `ERR_DISCLOSURE_ALREADY_CLEARED` is evaluated *first* — `routes_board.py:305-317`, `calc.py:312-319`
- §3.6 Calling to order — revise — ambiguity — an `attending_member_ids` entry matching no trustee gives `ERR_BOARD_MEMBER_NOT_FOUND` (body-FK rung, before the presidential identity check); only a resolved-but-unseated trustee gives `ERR_MEMBER_NOT_SEATED` — `routes_meeting.py:139-152`
- §3.7 Regular path — insert — ambiguity — a *failing* `POLICY_FIRST_READING` leaves the version wholly untouched (`DRAFT`, `reading_count` 0, `first_reading_meeting_id` null, own `version` unchanged); the `DRAFT` eligibility check runs regardless of outcome — `routes_agenda.py:204-208, 265-272`
- §3.8 Waiver window overlap — revise — ambiguity — overlap always compares the *existing request's* `requested_start_date`/`requested_end_date`, never a granted/clipped window — `routes_waiver.py:45-46`
- §3.9 Rating phase stamp — revise — ambiguity — `SUMMATIVE` for `SUMMATIVE_DRAFT` **or** `ADOPTED`; `FORMATIVE` for every other stage including `PLANNING` (PRD had left `PLANNING` and `ADOPTED` unstated) — `routes_ops.py:327-328`
