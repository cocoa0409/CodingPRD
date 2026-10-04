# Worklog — task_3396_military_transition_internship_authorization_employer_partner_program

## Step 1: Create task directory — 2026-10-01T16:19:00.000Z

Task directory pre-allocated by the caller as `./tasks/task_3396_military_transition_internship_authorization_employer_partner_program/` with `workspace/` inside; verified it exists and no new index was computed. Difficulty instruction for scaffold-generator: "Generate task much harder than expert level!"

## Step 2: Generate scaffold — 2026-10-01T17:45:00.000Z

Done. All three scaffold artifacts are generated and lint-clean.

**Lint verdict (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
  §1.5 endpoints declared:    39
  §1.1 entities declared:     10
  §1.8 instances scanned:     18
  §1.9 instances scanned:     45
  Calls scanned (§1.8+§1.9):  746
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Deliverables** (in `/home/ubuntu/github/CodingPRD/tasks/task_3396_military_transition_internship_authorization_employer_partner_program/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys), 10 entities, 39 endpoints, 52 errors, 29 ordered validations, 6 state machines, 6 calculations, 2 OCC concurrency rules, 6 roles with `identity:` declared
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — `scaffold_difficulty_design:` with all 9 rules × 2 instances = 18, each with full structured replayable chains
- `SCAFFOLD_CORNER_DESIGN.yaml` — `scaffold_corner_design:` with 45 real instances + 12 `excluded_because:` stubs across 8 sections

**Design highlights (difficulty pushed past Expert via density, not volume):**
- Archetype: compliance/audit + temporal windowing; flat FK topology; parallel state dimensions on ServiceMember (service_status × tap_stage) and InternshipMatch (match_status × plan_status), plus cyclic appeal loop (InternshipApplication) and suspend/remediate/lapse cycle (Employer).
- Two dual-variant calcs on different domains: employer hiring rate (cohort-by-separation-date vs rolling-90-day-by-completed_at — asserted 50.00 vs 0.00 on identical data) and training progress (resolution_ratio vs mastery_ratio — full resolution with 0.50 mastery blocks completion).
- Combinatorial modes (a) and (b): nested-min duration gate (policy cap vs separation headroom bind in different fixtures) and per-finding-rounded compliance score (77.50 CLEARED vs 0.00 clamped SANCTIONED).
- Two depth-3 cascades on different triggers (audit sanction → revoke → close openings → void/terminate matches; wage violation → flag → ledger → threshold suspension).
- Segregation of duties on appeal adjudication; OCC on EmployerOpening (match create) and ServiceMember (PATCH), both placeholder-driven per lint rule (e).

**Pitfalls actively handled:** all constants pinned with literals (verified by cross-file grep); two dead-error traps found and fixed pre-lint (ERR_MAX_APPEALS_REACHED unreachable under DENIED_FINAL — redesigned so the appeal budget itself rejects; ERR_OPENING_NOT_OPEN unreachable because openings only closed on revocation — added `POST /employer-openings/{id}/close`); every fixture date computed against the 2026-09-01T00:00:00Z clock default and verified with Python; no sibling task directories were read.

## Step 3: Copy INSTRUCTION.md — 2026-10-01T17:46:00.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-10-01T17:50:00.000Z

All contracts pass. The PRD is complete at `workspace/PRD.md` (351 lines), ending at §5 with no audit footer.

**What was generated:** A prose PRD for the SkillBridge-style military transition internship program, structured as §1 Introduction (2 paragraphs), §2 with 10 subsections (RBAC with per-role identity translation, verbatim §2.2 envelope, pagination + list filters, logical clock with pinned 3-sweep order and `2026-09-01T00:00:00Z` startup default, common resource properties including the reduced `id`/`created_at`-only set for SupervisionReport/WageRecord/ConversionRecord, OCC, a 30-entry validation priority ladder, installation policy variation, precision rules, slot ledgers/cascades), §3 with 8 lifecycle subsections (intake/TAP, application+appeal cycle, employer authorization/review/lapse, openings+match proposal with the pinned 13-gate order, training plans+installation decision, execution/supervision/wage attestation, completion/conversion/hiring-rate, audits+sanction cascade), §4 with a 39-row 4-column endpoint table, §5 with a 52-row 2-column error table.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoint inputs + query params: 98 required, 98 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] priority ladder: 28 priorities expressed as a pinned 30-entry ordered list in §2.7, plus per-endpoint pinned orders restated in §3 (match creation, duration gates, appeal window-before-count, completion content gates)
- concurrency_rules[] OCC: 2/2 expressed (PATCH member -> expected_service_member_version; POST matches -> expected_employer_opening_version; both ERR_STALE_VERSION 412, OCC framed purely as stale-version rejection)
- state_machines[].transitions: all 29 transitions expressed (incl. review self-loop, lapse strict-> boundary, DENY-needs-no-plan asymmetry, appeal cycle with budget 2, plan revision cycle with budget 3)
- calculations[]: 6/6 in reconstructible prose (eligibility 30..180 inclusive; nested-min duration cap with 7-day buffer; dual-variant hiring rate with 0.00 zero-denominator; resolution vs mastery ratios; floor(duration/7) supervision with 34/35-day boundary example; per-finding-round-then-sum compliance score with 100 base, 70 threshold, 0.5 repeat multiplier, 5.00/20.00/45.00 severity bases)
- validations[] conditions: all matchable to error_ids in §2/§3 prose (52/52 error ids present)
- endpoints[].side_effects / applies_to: all expressed
- entities[].fields[] structured content: defaults and computed semantics reconstructible (ratios 1.0-when-empty, ledger resets, null-until-event timestamps)
- sibling-branch symmetry: APPROVE/DENY, OVERTURNED/UPHELD, PASS/FAIL, COHORT/ROLLING, resolution/mastery all at equal density
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 546
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verifications: §2.2 matches the fixed source file byte-for-byte (substring check passed); all 50 enum/state values present verbatim; all 15 named constants pinned to their scaffold values in prose; no fuzzy/approximating words; no pseudocode operators (`>=`, `==`, `->`, `FLOOR(`, etc.) anywhere; endpoint table 39/39 rows, error table 52/52 rows. No unnamed-but-valued or valued-but-unnamed constant bugs were found in the scaffold — every constant had both a name and a concrete value. The withheld design files were never opened.

## Step 5: Generate unit tests — 2026-10-01T18:05:00.000Z

Complete. The full generation pipeline ran clean.

## What was built

**`test_helpers/`** (Stage 5a, frozen before test emission):
- `types.py` — 10 entity TypedDicts (ledger entities SupervisionReport/WageRecord/ConversionRecord correctly omit `updated_at`/`version` per PRD §2.5), 12 status/role enums
- `api_client.py` — 39 endpoint methods, all under `/skillbridge`
- `api_errors.py` — all 51 PRD §5 error ids mapped and registered with the framework
- `constants.py` — only PRD-verbatim-pinned values (each grep-verified against PRD.md)
- `factories.py`, `test_users.py` (per-instance builders for both entity-backed roles), `assertions.py` (entity assertions + `canonical_instant`/`assert_instant`/`assert_two_dp` comparators), `fixtures.py` (the `setup_match` pipeline walking proposed→active, completion-ready/completed setups), `worlds.py` (hiring-rate, audit-cascade, two-active-matches worlds)

**`test_suite/`** (Stage 5b): `conftest.py` + 13 concern-grouped test files, **81 tests**.

## Verification results

- **AST tag audit (real `ast` parse)**: Queue A 18/18 difficulty instances with ≥2 tests each (36 tests); Queue B 45/45 non-stub corner instances with ≥1 test (45 tests); all 12 `excluded_because:` stubs correctly untranslated; zero phantom/untagged/dual-tagged tests; every tag sits at docstring end and resolves to a real yaml `name:`.
- **PRD citation check**: all 121 quoted docstring fragments grep verbatim against PRD.md (whitespace-normalized). Initial pass caught ~40 ellipsis-abbreviated quotes; all rewritten to complete sentences.
- **`pytest --collect-only`**: 81 collected, zero import/collection errors; `pyflakes` clean.
- **Dates**: all 29 date/duration literals in the recipes verified with Python against the 2026-09-01T00:00:00Z clock default (180-day horizon → 2027-02-28, rolling window start 2026-12-10, 34/35-day supervision floor, etc.).

## Notable deviations (both documented in the affected test docstrings)

1. **Corrected a bad design literal**: corner instance `separation_date_patch_conflict` patches to 2026-11-15 claiming match end 2026-10-31 > 2026-11-15−7d = 2026-11-08 — arithmetically false, so the PATCH would succeed under the PRD rule. I changed the patch target to 2026-11-05 (boundary 2026-10-29 < 2026-10-31) so `ERR_SEPARATION_DATE_CONFLICT` genuinely fires; the asserted error and instance tag are unchanged.
2. **Two-reader weakenings**: (a) initial `version` asserted as positive-int, not `== 1` — the PRD never pins the initial version value, so all OCC tests capture versions from responses instead; (b) all timestamp assertions compare instants semantically, since PRD §2.5 mandates three fractional digits while §2.4 writes the clock default without any — both serializations are PRD-faithful.

## Step 6: Generate implementation — 2026-10-01T18:35:00.000Z

Implementation complete and verified.

## Summary

Built a complete Python + Flask implementation at `workspace/implementation/` covering all 10 entities, 39 endpoints, 52 error codes, 6 state machines, and 6 calculations from the PRD/SCAFFOLD.

**Layout** (per-domain modules, no monolith): `app.py` (entry, blueprint registration under `/skillbridge`, error handlers), `db.py` (in-memory store, logical clock pinned at `2026-09-01T00:00:00Z`, never seeded), `constants.py` (every PRD constant defined exactly once), `errors.py` (full catalog), `util.py` (ISO parse/format, half-up 2dp rounding, serializer), `response.py` (exact envelope: `meta`/`response_type`/`data`, pagination `limit/offset/total_count/has_more` in meta), `middleware.py` (X-User-ID/X-User-Role auth, role gate, schema validators), `services.py` (slot ledgers, ratios, cascades, the three pinned-order clock sweeps, compliance score with per-finding rounding, dual-variant hiring rate), and `routes/{clock,installations,members,applications,employers,openings,matches,records,audits}.py`.

**Verified by self-smoke-test on a dynamic free port** (62/62 checks passed, server PID killed exactly): full lifecycle (install → member → application → commander approve → employer authorize → opening → OCC match proposal → plan submit/review → installation approve → clock auto-start → 4 supervision reports → zero wage record → clock to end → complete → separation sweep → conversion → hiring-rate), plus error probes for auth headers, schema-before-role ordering, ownership, eligibility window, TAP sequencing, duplicate application, DENY-without-reason, stale version 412, plan-not-approved, duplicate week report, conversion uniqueness, appeal SoD conflict, duration-exceeds-headroom, start-in-past, audit clear (87.50 with per-finding repeat multiplier) vs sanction (35.00 → REVOKED → opening closed cascade), and pagination meta. Fresh-boot isolation verified: a second `start.sh` process serves empty state.

**Interpretations chosen** (ambiguities resolved, per the no-invented-guards rule):
1. **submit-plan** is allowed whenever `match_status == PROPOSED` regardless of `plan_status`; the revision budget (3) is enforced only on the documented `PLAN_RETURNED → PLAN_SUBMITTED` resubmission edge. The PRD documents no plan-source-state error for this endpoint, so no extra guard was invented.
2. **Version semantics**: versions start at 1; one increment per entity per mutation event. Endpoint-stated increments honored exactly (e.g. match-create bumps the opening, not the member); sweep/cascade-mutated entities (voids, closes, lapses, activations, and ledger-count changes within cascades) each bump once per §2.10.
3. **Temporal precision**: appeal window compares instants (`clock <= appeal_deadline`); employer lapse compares dates (`clock date > next_review_due_date date`); separation/auto-start/duration windows compare dates — each following its own PRD sentence.
4. **Serialization**: date-precision fields as `YYYY-MM-DD`; all timestamps as ISO 8601 UTC with 3 fractional digits; ratios/scores as JSON numbers.
5. `note` in audit findings is optional (finding_code/severity strictly validated); `limit`/`offset` out-of-range are clamped to [1,100]/[0,∞) while non-integer values yield `ERR_VALIDATION`; hiring-rate `variant` must be exactly `COHORT`/`ROLLING` else `ERR_VALIDATION`.

## Step 7: Run tests and iterate — 2026-10-01T18:50:00.000Z

Clean sweep: all 8 rounds pass 81/81. The final action was the sweep — no edits after it, and the `results.{1..8}.json` evidence files remain in `workspace/implementation/`.

## Summary

**Iterations run:** 2 (sweep 1: 80/81 in all 8 rounds, one consistent non-flaky failure; sweep 2 after fix: 81/81 × 8).

**Failure diagnosed:** `test_slot_ledger_fill_release_cycle` (test_06) — asserted the opening's `version` increments by exactly 1 when a match termination recomputes `filled_count` 1→0; the implementation deliberately bumps only the match's version.

**Tests deleted:** none (partial-coverage split per STEP 1c — one assertion removed, test kept).

**Assertion removed** (test_suite/test_06_opening_capacity_and_schedule.py, `test_slot_ledger_fill_release_cycle`):
- Removed: `after_terminate["version"] == after_create["version"] + 1`. Collapse pattern: **computed-field/recompute-vs-modify ambiguity** (unique-derivability failure). PRD §3.6's termination effect list names only "increments the match's `version`"; PRD §2.10 explicitly labels `filled_count`/`active_match_count` "**computed counters** ... recomputed on every match creation, termination, void, denial, and completion"; §2.5's blanket "every modification to the resource" never settles whether re-deriving a computed counter is a version-bumping modification. The PRD names opening-version bumps explicitly where intended (§3.4 creation: "increments the opening's `version` by 1"; wage violation: "both the match's and the employer's"; audit close: "both the audit and the employer") — and the identically-phrased denial (§3.5) and completion (§3.7) slot-releases also name only the match's version. Two faithful PRD-only readers diverge (derived-on-read counters vs. stored-counter write), so the assertion fails the two-reader test. Covered assertions retained: `ERR_OPENING_AT_CAPACITY` block, `TERMINATED_EARLY` transition, `filled_count` release 1→0. Scaffold rule that drove generation: `Difficulty/compensating_invariant/opening_slot_ledger_roundtrip` (scaffold types `filled_count` as `source: computed` — feedback for unit-test-generator: computed-field recompute does not uniquely determine a version bump).
- Suite-internal consistency verified before the fix: sibling `test_slot_ledger_retry_after_release_succeeds` re-reads the opening version before re-proposing (insulated either way); the only other version-bump assertions in the suite trace to PRD-explicit bumps (member patch §3.2, match create §3.4).

**test_helpers fixes:** none.

**implementation fixes:** none — the implementation's reading (direct endpoints bump exactly the versions their PRD sentences name; sweeps/cascades bump every mutated entity per §2.10) is deliberate, coherent across `routes/matches.py` and `services.py`, and PRD-faithful.

Orchestrator verification: all 8 results.*.json present with passed=81/total=81; no implementation, test_suite, or test_helpers file is newer than results.8.json (final sweep was the last write); the claimed assertion removal spot-checked against test_06_opening_capacity_and_schedule.py — weakening note and retained covered assertions confirmed inline.

## Step 8: Finalize PRD — 2026-10-01T19:00:00.000Z

The diff shows exactly the intended two-line change and nothing else. Task complete.

## Summary

**File produced:** `workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md 351 lines, PRD_FINALIZED.md 351 lines (0% line-count delta; 2 of 351 lines revised in place, ~0.6% of lines touched). `diff` confirms the copy differs only at the two §2.10 paragraphs — no silent no-op.

### Change list

- **§2.10, paragraph 1** — insert (one sentence appended) — pins that on the direct match-lifecycle endpoints, rewriting `filled_count`/`active_match_count` does not by itself increment the hosting opening's/member's `version` or refresh `updated_at`: each endpoint performs exactly the version increments its workflow effect list names (creation also bumps the opening per §3.4; denial §3.5, termination §3.6, completion §3.7 bump only the match) — `implementation/routes/matches.py:161-163` (create: opening touched, member untouched), `matches.py:220-229` (deny: recompute only, touch match), `matches.py:293-301` (terminate), `matches.py:330-338` (complete).
- **§2.10, paragraph 2** — revise (clause appended to final sentence) — pins the cascade/sweep side: a counter that changes value makes its host one of the mutated entities whose `updated_at`/`version` advance; a counter that recomputes to its prior value does not by itself mutate the host — `implementation/services.py:80-83` (separation cascade touches opening iff `filled_count` changed), `services.py:103-106` (opening-close cascade touches member iff `active_match_count` changed), `services.py:132-143` (revocation cascade, same conditionals).

### Per-edit pre-edit search log

Both sentences are one logical edit (same subject, committed together); the search covers both.

- **(a) Subject:** whether recomputing the two §2.10 ledger counters increments the counter-hosting entity's `version` / refreshes `updated_at`, on every code path that recomputes them.
- **(b) Impl paths enumerated and read:** `routes/matches.py` (create_match:161-163, installation_decision DENY:220-229, terminate:293-301, complete:330-338, submit_plan:257, review_plan:277); `routes/openings.py` (close_opening:101-103 → `services.cascade_opening_closed`:87-106); `services.py` in full (`touch`:9-12, `recompute_*`:15-30, `cascade_member_separated`:59-84, `cascade_employer_revoked`:109-143, `run_sweeps`:148-181); `routes/records.py` (supervision:76-82 touches match after ratio recompute; wage violation:121-132 touches match+employer per PRD §3.6's explicit sentence — `pending_violations` is not a §2.10 counter, out of scope); `routes/members.py` (patch:126, tap:144 — no counter recompute); `routes/applications.py`, `routes/employers.py`, `routes/audits.py` (touches all match PRD-named bumps; audit-close sanction path routes through `cascade_employer_revoked`); `routes/clock.py` (delegates to `run_sweeps`).
- **(c) Wording adjustments made:** (1) Rejected a flat "counter recompute never bumps version" — false for cascades, where changed counters do bump their hosts (`services.py:80-83,103-106,132-143`); scoped the no-bump clause to direct match-lifecycle endpoints and added the cascade clause "changed counter ⇒ mutated host". (2) Attributed creation's opening bump to the §3.4 effect list rather than the counter rewrite, so the member-side silence on creation (member counter 0→1 with no bump, `matches.py:163`) is also pinned. (3) Phrased the cascade clause as set inclusion ("one of the mutated entities", "does not by itself mutate the host") so the separating member (status flip + counter recompute in one call) still gets exactly one §2.4 increment, and the opening-close caller's unconditional touch on a status flip is not excluded by an unchanged counter.

No other Step 7 items existed (no test deletions, no test_helpers fixes, no implementation fixes), so no further edits were warranted.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly the two §2.10 sentence changes described above and nothing else — not a silent no-op.

## Step 9: Complete PRD — 2026-10-01T19:40:00.000Z

Done. `PRD_COMPLETED.md` produced at `workspace/PRD_COMPLETED.md`.

**Source vs output:** `PRD_FINALIZED.md` 351 lines / 56,010 chars → `PRD_COMPLETED.md` 353 lines / 60,091 chars (char-delta +4,081; the +2 lines come from the §2.7 carve-out paragraph). `diff` confirms exactly 20 hunks matching the 22 edits below (two edits share the §3.3 review paragraph → one hunk); not a byte-identical copy. `results.*.json` files untouched (mtimes 19:34, pre-session).

**Counts:** 18 ambiguity-pins, 4 mismatch-revisions.

**Change list:**

- §2.3 — revise — ambiguity — pin pagination clamping: limit clamps into [1,100], negative offset clamps to 0, non-integer limit/offset is `ERR_VALIDATION` — `implementation/response.py:38-61`
- §2.3 — revise — ambiguity — pin created_at sort tiebreak by insertion order (logical clock makes ties common) — `implementation/routes/members.py:75`, `implementation/db.py:13`
- §2.3 — revise — ambiguity — pin `total_count` (post-filter, pre-pagination) and `has_more` formula (offset + returned < total_count) — `implementation/response.py:62-69`
- §2.4 — revise — ambiguity — clock set adopts target unconditionally (no monotonicity guard); date-only → midnight UTC, timezone-less → UTC — `implementation/routes/clock.py:21-25`, `implementation/util.py:5-21`
- §2.7 step 2 — revise — ambiguity — query-parameter validation (pagination, hiring-rate variant/cohort) runs after role and path-existence checks, not at schema step — `implementation/routes/employers.py:122-137`
- §2.7 (after list) — insert — **mismatch** — ladder's global 8→11→12 ordering is inverted by impl on match proposal and installation decision (state gates 12 run before employer 11 and active-duty 8); per-endpoint §3.4/§3.5 order governs — `implementation/routes/matches.py:87-98`, `implementation/routes/matches.py:205-215`
- §2.9 — revise — **mismatch** — carve appeal deadline out of the date-precision blanket rule: it is an instant-precision timestamp comparison (`now > decided_at + appeal_window_days`); also pin date-typed fields accept full timestamps truncated to UTC date — `implementation/routes/applications.py:148`, `implementation/util.py:24-29`
- §3.1 — revise — ambiguity — `days_until_separation` computed at read time on every member response — `implementation/services.py:46-49`
- §3.2 — revise — ambiguity — `appeal_deadline` is a timestamp (decided_at instant + days) serialized with three fractional digits — `implementation/routes/applications.py:131,183`
- §3.2 — revise — ambiguity — `appeal_reason` type-validated but not persisted — `implementation/routes/applications.py:141`
- §3.3 — revise — ambiguity — `next_review_due_date` stamped from clock instant, serialized as timestamp; lapse sweep compares its date part — `implementation/routes/employers.py:74`, `implementation/services.py:158`
- §3.3 — revise — ambiguity — review `notes` validated but not persisted — `implementation/routes/employers.py:85`
- §3.3 — revise — ambiguity — FAIL review leaves `authorized_at`/`next_review_due_date` untouched — `implementation/routes/employers.py:97-100`
- §3.5 — revise — **mismatch** — submit-plan accepted from any `plan_status` (not only PLAN_DRAFT/PLAN_RETURNED) while match is PROPOSED; revision-budget check fires only from PLAN_RETURNED; submission recomputes both ratios — `implementation/routes/matches.py:245-257`
- §3.5 — revise — ambiguity — review-plan `feedback` validated but not persisted — `implementation/routes/matches.py:267`
- §3.6 — revise — ambiguity — `week_start_date` window is both-bounds-inclusive (report on `end_date` accepted despite exclusive end_date in duration math) — `implementation/routes/records.py:54`
- §3.6 — revise — ambiguity — wage period bounds: both `period_start_date` and `period_end_date` within [`start_date`, `end_date`] inclusive — `implementation/routes/records.py:104-107`
- §3.7 — revise — ambiguity — unrecognized `variant` and malformed cohort dates are `ERR_VALIDATION`; cohort bounds need not be ordered; cohort params ignored under ROLLING — `implementation/routes/employers.py:124-137`
- §3.7 — revise — ambiguity — `window_start_date`/`window_end_date` serialize as `YYYY-MM-DD` — `implementation/services.py:255-256`
- §3.8 — revise — ambiguity — new audit carries empty `findings`, null `compliance_score`, null `closed_at` — `implementation/routes/audits.py:47-56`
- §3.8 — revise — **mismatch** — `findings` array optional (omission → no findings → 100.00) and per-finding `note` optional/nullable, not mandatory — `implementation/routes/audits.py:14-33`
- §5 — revise — ambiguity — three transport-level ids outside the catalogue: `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) — `implementation/app.py:42-54`

Everything else walked (all 9 route modules, services, middleware, response, db) checked out as already uniquely pinned — notably the §2.10 version-increment rules (creation touches only the opening; denial/termination/completion touch only the match; cascade hosts touched only on counter change), sweep ordering and per-sweep `created_at` processing, compliance-score per-finding rounding/cap, wage-violation suspension states, and all per-endpoint gate orders beyond the two ladder inversions flagged above.

Orchestrator verification: `diff PRD_FINALIZED.md PRD_COMPLETED.md` = 40 changed lines across ~20 hunks (not a silent no-op); all 8 `results.*.json` evidence files remain in `workspace/implementation/` with passed=81/total=81.
