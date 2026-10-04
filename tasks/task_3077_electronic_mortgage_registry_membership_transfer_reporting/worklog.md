# Worklog — task_3077_electronic_mortgage_registry_membership_transfer_reporting

## Step 1: Create Task Directory — 2026-09-29T20:29:00.000Z

Task directory pre-allocated by orchestrator command args: `./tasks/task_3077_electronic_mortgage_registry_membership_transfer_reporting/workspace` — verified exists; no index computed, no other directory created.

## Step 2: Generate Scaffold — 2026-09-29T21:11:00.000Z

Done. Clean lint on the final run; no sibling tasks were inspected at any point.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3077_electronic_mortgage_registry_membership_transfer_reporting/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Design summary** (deliberately harder than Expert band):
- Archetype: compliance_audit + ledger_reconciliation; flat topology, branching shape, segregation-of-duties role model, immediate consistency. Layers: cascading side effects, derived-field reconciliation, dual-variant calculation, OCC.
- **Entities: 11** — Member, AuthorizedSigner, RegisteredLoan, Transfer, TransferMatch, QAReview, QAFinding, AnnualReport, Sanction, SORReconciliationRun, SORException.
- **Endpoints: 53** (incl. `/_clock/set_current_utc` test-driving endpoint with the mandatory 2026-09-01T00:00:00Z startup default).
- **Errors: 50**, all referenced by validations/transitions/OCC rules (audited — zero orphans).
- **Difficulty instances: 18** (exactly 2 per rule × 9 rules), with every differentiation clause honored: dual variants on two domains (Transfer rates vs QAReview freeze), combinatorial modes (a) marginal-tier late fee + (b) per-line-round-then-sum sanctions (pinned 101271 vs 101270), cycles on RegisteredLoan and QAReview, depth-3 termination cascade vs depth-2 reject-match cascade, two priority pairs (state>referential-OCC, safety>fiscal), boundaries on days_late vs MIN check digit, cross-entity pairs Transfer→Member and QAReview→created_by, half-open signer windows vs closed calendar-year overlap, and conserved quantities (rights-holder set vs exactly-one-FINAL-report).
- **Corner instances: 40** across all nine guide sections (36 active + 4 `excluded_because` stubs).
- All formula-derived asserts are precomputed literals (MINs `100000000000000016`/`…24`/`100000100000000014` verified via the Luhn variant, late fees 2500/25000/62500, rates 0.6667/0.5000, scores 0.2500/1.1000/0.5000, standing 40.00 with the exception cap exercised by a 12-match chain, sanction 101271).
- `scaffold_lint.py` verdict, final run: **clean lint** — 53 endpoints, 11 entities, 18 §1.8 + 40 §1.9 instances, 558 calls scanned, zero violations; no forbidden race vocabulary, no unbound `${var}` placeholders, no duplicate instance names.

## Step 3: Copy Shared Files — 2026-09-29T21:12:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-29T21:18:00.000Z

Confirmed: `MATCH_WINDOW_DAYS` has no numeric value in the scaffold (only the appeal window's 30 days is given, which I included). Referring to it as "the match window" is the faithful projection. Also note the match expiry has two triggers — clock passing the window, or transfer reject-match — both covered in my prose.

One more check: the appeal error says "more than 30 days after sanction created_at" — I wrote "no more than thirty days after" — correct (filing at exactly 30 days is within the window).

Final verification pass on the whole document for remaining audit items: validation priorities are expressed with explicit ordering (numbered tiers 1–16 covering priorities 0–15 — "evaluated last" for OCC is explicit). Sibling-branch symmetry: foreclosure modes both specified, sanction adjudication decisions all three specified with equal density, transfer types all three specified, both reporting-rate variants specified with equal density including the divergent example.

All three contracts pass:

```
Field coverage check:
- entities[].fields: 61 required, 61 present, 0 missing
- endpoints[].request_body/input extras (to_iso8601, expected_member_version, signer_id, assignment_out, records, resolution_note, decision, reduced_total_cents, force_regenerate, servicer_org_id, investor_org_id): 10 required, 10 present, 0 missing
- endpoints[].query_params (status, member_type, registering_member_id, current_investor_id, current_servicer_id, loan_id, from_member_id, to_member_id, reported_by_member_id, member_id, review_id, severity, report_year, run_id, exception_type, limit, offset): 17 required, 17 present, 0 missing
- borrower-inquiry output fields (min, loan_id, loan_status, current_investor_id, current_investor_org_id, current_servicer_id, current_servicer_org_id): 7 required, 7 present
Status: PASS

Rule coverage check:
- validations[] priority ordering: 16 tiers (priority 0–15) expressed as a numbered cascade with explicit "evaluated last" for OCC, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write operation + expected_loan_version/expected_member_version + ERR_STALE_LOAN_VERSION 412 / ERR_STALE_MEMBER_VERSION 412), 0 missing
- state_machines[].transitions: 25 transition rows across 9 machines checked, 25 fully expressed (from/to states, preconditions with error ids, side effects incl. cascades, reject-match no-rollback asymmetry, WAIVED unreachable note, termination never auto-completes a run, superseded-exception detail), 0 missing
- calculations[]: 7 checked (min_check_digit Luhn construction, transfer_late_fee tiered 2500/5000/10000 with 10-day window and exact boundary, qa_discrepancy_score weights 1.0/0.5/0.2, sanction_assessment per-line round-then-sum with bases 500000/100000/25005 and 1.5 repeat multiplier incl. the 101271-vs-101270 discriminator, dual-variant reporting rates with vacuous 1.0 and the 0.6667-vs-0.5000 divergence example, member_standing_score 60/40/2-per-exception-capped-at-10 clamped [0,100], sor_match_rate with protective denominator), 0 missing
- validations[] conditions: all matchable to their error_id in §2.9/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed in the relevant workflow narratives, 0 missing
- entities[].fields[] structured content: enums, defaults (null, 1.0), system-derived provenance, uniqueness scopes all reconstructible from prose, 0 missing
- sibling-branch symmetry: foreclosure modes, adjudication decisions, transfer types, both rate variants, all SOR exception kinds rendered with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 379
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_3077_electronic_mortgage_registry_membership_transfer_reporting/workspace/PRD.md` — 327 lines.

**Sections produced:**
- §1 Introduction (3 paragraphs, business-context angle)
- §2 Global Specifications in 9 subsections: 2.1 RBAC with per-role identity translation; 2.2 response envelope (verbatim fixed block); 2.3 pagination (limit 10/1/100, offset 0, created_at ascending); 2.4 logical clock (startup default 2026-09-01T00:00:00Z, timed re-evaluation on advance); 2.5 common resource properties + identifier discipline (org_id/min/idempotency_key); 2.6 MIN/Luhn construction; 2.7 precision and standing bands; 2.8 OCC (the two guarded writes only); 2.9 sixteen-tier validation priority cascade
- §3 Business Logic in 9 subsections: membership admission and signers, loan registration, foreclosure/assign-out/rescind/satisfy, transfer reporting + late fees + match protocol, QA reviews/findings/sanctions, annual reporting with dual rate variants and standing score, termination with portfolio deactivation cascade, SOR reconciliation with derived run state, borrower inquiry
- §4 Endpoint table — 53 rows (the scaffold's header comment said 40 but actually defines 53; table matches the scaffold exactly), 4 columns
- §5 Error catalogue — all 50 error ids, 2 columns

**Audits:** All three hard contracts PASS (reports above). Zero missing field names, zero missing rules, zero path leaks in §3, zero missing error ids or enum values. Two scaffolding inflections handled: `MATCH_WINDOW_DAYS` has no numeric value in the allowed scaffold sections, so it is referenced as "the match window" rather than inventing a constant; the termination `effective_date` past-vs-at-clock boundary was reconciled to the error catalog's authoritative phrasing. The withheld difficulty/corner design files were not opened.

## Step 5: Generate Unit Tests — 2026-09-29T21:59:00.000Z

Generation complete. Here is the summary.

## Files written

**`/home/ubuntu/github/CodingPRD/tasks/task_3077_electronic_mortgage_registry_membership_transfer_reporting/test_helpers/`** (9 files):
- `types.py` — 11 entity TypedDicts (all `common_fields: true`, so all carry id/created_at/updated_at/version) + status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (clock, members, signers nested+flat, loans, transfers, matches, borrower-inquiries, QA reviews/findings nested+flat, sanctions, annual reports, SOR runs/exceptions)
- `api_errors.py` — all 50 error IDs + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + `assert_loan_rights_conserved`
- `factories.py`, `constants.py` (fee tiers, weights, windows, band floors), `test_users.py` (opaque role constants + `make_member_rep_headers(member_id)` for the entity-backed role), `fixtures.py` (clock, member/signer/loan/transfer/QA/sanction composite builders, all member-scoped calls threaded through per-instance `member_rep(member_id)`), `__init__.py` barrel.

**`test_suite/`**: `conftest.py` + 16 test files (`test_01`–`test_09` queue A depth, `test_20`–`test_26` queue B breadth).

## Test counts

- **Queue A (difficulty): 36 tests** — exactly 2 per instance × 18 instances (all 9 rules).
- **Queue B (corner): 41 tests** — 1 per non-stub instance × 41 instances.
- **Total: 77 test functions.**

## Skipped instances (queue B `excluded_because:` stubs — not translated, per spec)

| Stub | Cited owner | Cross-reference |
|---|---|---|
| `calculations/reporting_rate_boundary_deadline_day_counts_as_ontime` | `transfer_deadline_day_ten_is_ontime_day_eleven_is_late` | resolves |
| `calculations/qa_score_weighted_average_and_precision` | `qa_score_provisional_draft_vs_frozen_issue_diverge` | resolves |
| `cross_cutting_layers/version_increments_on_every_mutation` | `transfer_success_moves_rights_and_bumps_loan_version` | resolves to a §1.9 endpoints instance (odd pointer, but the OCC assertion is covered by queue A test 05 + that endpoints test) |
| `cross_cutting_layers/derived_member_portfolio_counts_reconcile_after_termination` | `termination_cascade_member_loan_sorexception_run` | resolves |

No non-stub instance was skipped for PRD-silence — every translated assertion traces to a verbatim PRD sentence. (Notable PRD gap encountered: the PRD never states the numeric match-window length, so the match-expiry test advances the clock past the window via §2.4's timed-evaluation rule rather than asserting a day count.)

## Stage 2 self-audit results

- **Tag audit (C4):** all 77 tests carry exactly one `Design:` line; every tag resolves to a real `name:` in the source yaml; zero dual-tag/untagged; all 18 difficulty instances have ≥2 tests; all 41 non-stub corner instances have ≥1 test.
- **PRD-citation audit (C1):** 161 quoted fragments across all docstrings — 0 fail the literal whitespace-normalized substring check against `workspace/PRD.md` (three bold-marker mismatches and one comma splice were caught and repaired).
- **Skip markers:** none (`skip`/`skipif`/`xfail` absent).
- **Import audit:** all 39 names imported from `test_helpers` by the suite resolve; all files compile.
- One assertion softened from the recipe: the match-expiry test asserts PENDING → EXPIRED → 409 `ERR_MATCH_NOT_PENDING` without pinning the 60-day number (PRD says "the match window" without a value — the two-reader test fails on the number, passes on the transition).

## Step 6: Generate Implementation — 2026-09-29T22:10:00.000Z

NOTE: The Step 6 subagent's session ended mid-verification while resolving suspected test-vs-scaffold arithmetic questions (its returned "report" was an in-progress analysis fragment about late-fee day arithmetic and match-window expiry boundaries, not a completion summary — no final smoke-boot verdict was emitted). Artifacts verified on disk by the orchestrator:

Files written in `workspace/implementation/`:
- `app.py` (3.2 KB) — Flask app factory + route registration
- `db.py` (0.8 KB) — in-memory stores
- `domain.py` (13.9 KB) — state machines, calculations, cascades
- `errors.py` (2.3 KB) — error catalog
- `middleware.py` (1.1 KB) — RBAC header handling
- `response.py` (1.1 KB) — response envelope
- `views.py` (5.4 KB) — serializers
- `routes_members.py` (12.0 KB), `routes_loans.py` (7.0 KB), `routes_transfers.py` (8.1 KB), `routes_qa.py` (10.6 KB), `routes_sor.py` (6.4 KB)
- `start.sh` (executable launcher, reads $PORT, binds 0.0.0.0, foreground)
- `requirements.txt`

Open questions left for Step 7 to adjudicate via the PRD-first diagnostic protocol: (a) late-fee `days_late` arithmetic for the 2026-03-02 vs 2026-02-10 pair (tests assert 20/fee 62500 vs diff-minus-window yielding 10/25000 — possible test bug or leap arithmetic confusion); (b) match-window expiry trigger boundary (`>=` vs `>` at effective+60d). Step 7's STEP 1/STEP 2 protocol (PRD verbatim coverage + unique derivability) is the arbiter for both.

## Step 7: Run Tests and Iterate — 2026-09-29T22:28:00.000Z

All 8 rounds pass 75/75. Clean exit.

Summary:

- Iterations run: 3 sweeps (8 parallel rounds each). Final sweep: all 8 rounds 75/75.

- Tests deleted:
  - `test_transfer_match_expires_after_window_on_clock_advance` (two duplicate copies in `test_suite/test_21_corner_state_machines.py`): PRD says only "more than the match window" without ever stating the window's length — any assertion pinning a specific day count (here 60 days → EXPIRED) is a unique-derivability failure (ENUM/threshold silence; known open question b). Scaffold rule: match-window expiry day count.

- Fixes applied to `test_suite/` (no `test_helpers/` changes needed — the helpers were correct; the NameError was a missing import in the test file itself):
  - `test_02_combinatorial_formulas.py`: added missing `settle_review` import (NameError in 2 tests); fixed `test_fee_spans_tier_one_and_tier_two_marginaly` arithmetic — 2026-02-10→2026-03-02 is a 20-day diff → 10 days late per PRD's "grace window of ten days is subtracted", so clock moved to 2026-03-12 to keep the tier-spanning 20-days-late/62500 scenario PRD-faithful (open question a: PRD pins days_late = caldiff − 10, so the 20/62500-at-03-02 variant was the wrong side).
  - `test_01_dual_variant_calculations.py`: `tr3` assertions corrected to `days_late == 10` / `late_fee_cents == 25000` (same caldiff−10 rule); first-issue `discrepancy_score` corrected to 0.5000 — two MAJOR findings over a 2-loan sample is (0.5+0.5)/2 = 0.5 per PRD's weighted-total/sample-size formula (test had 0.25).
  - `test_24_corner_endpoints.py::test_transfer_success_moves_rights_and_bumps_loan_version`: stale-version probe now transfers from B to a fresh member C — per PRD §2.9 tier ordering, the old probe (B→B self-transfer with stale version) must report ERR_SELF_TRANSFER (tier 13) before OCC (tier 16); "stale-version rejections are a guarantee about otherwise-valid requests."
  - `test_25_corner_errors_and_rbac.py::test_signer_scope_and_window_gate_foreclosure`: signer windows made endpoint-touching (s2: 01-01→03-01 ALL; s1: 03-01→open REGISTRATION) — PRD forbids any positive-length window overlap per member.
  - `test_03_nonlinear_state_machines.py::test_cycle_preserves_rights_and_registry_presence`: alternating foreclose/rescind pairs — consecutive forecloses on an already-FORECLOSING loan must fail with ERR_LOAN_NOT_ACTIVE (PRD tier 7).
  - `test_04_transitive_cascades.py` (both termination-cascade tests): setup now moves BOTH rights off member E (and confirms the matches) before termination — PRD §3.7 gate refuses termination while any loan in any status names the member as holder; in test 1, F (new holder) satisfies loan1, and the SOR run is opened while E still holds loan2 so it is born OPEN with one REGISTRY_ONLY exception.
  - `test_22_corner_calculations.py::test_standing_score_exception_cap_limits_penalty_to_ten`: scenario reworked — old math (100−60−40×0.5−2×10) bottoms at the 0 clamp and cannot distinguish the cap; now on-time transfers + no settled review isolate the exception penalty, asserting 80.00 (capped) vs 76.00 (uncapped).
  - `test_23_corner_validations.py::test_termination_blocked_while_member_holds_rights`: final assertion corrected to INACTIVE_TERMINATED — the PRD cascade keys on `registering_member_id` ("every loan the member originally registered ... that is still ACTIVE"), not the current holder.

- Fixes applied to `implementation/`: none — every failure traced to test-side PRD inconsistencies; the implementation was PRD-faithful throughout.

## Step 8: Finalize PRD — 2026-09-29T22:32:00.000Z

Done. Summary:

## Result

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_3077_electronic_mortgage_registry_membership_transfer_reporting/workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md = 327 lines, PRD_FINALIZED.md = 327 lines (0% delta — single in-place sentence revision, no lines added or removed).

### Changes (one edit total)

- **§3.4 (Transfer Reporting, Timeliness Fees, and the Match Protocol) — revise** — pinned the previously-unstated match-window length: the window is sixty calendar days, measured as the calendar-day difference between the logical clock and the transfer's `effective_date` (each truncated to its calendar day, same convention as `days_late`) strictly exceeding 60; added an exact-boundary sentence (day 60 still answerable, day 61 expires at the next clock advance). — `implementation/domain.py:14` (`MATCH_WINDOW_DAYS = 60`), `implementation/domain.py:440-441` (`(clock.date() - eff.date()).days > MATCH_WINDOW_DAYS` inside `run_timed_evaluations`).

All other Step 7 diff items were pure test-side fixes against behavior the PRD already pins verbatim (days_late = caldiff − 10 grace rule, weighted-total/sample-size discrepancy formula, §2.9 tier ordering, half-open signer window overlap, `ERR_LOAN_NOT_ACTIVE` on re-foreclosure, termination gates, exception cap of ten, termination cascade keyed on `registering_member_id`). The implementation matches the PRD on every one of them, so no further PRD edits were warranted.

### Per-edit pre-edit search log

- **Edit 1 (match-window expiry):**
  - (a) Subject: the length of the match window and the exact condition under which a `PENDING` TransferMatch flips to `EXPIRED`.
  - (b) Impl paths enumerated and read: `implementation/domain.py:14` (constant), `domain.py:427-442` (`run_timed_evaluations` — sole auto-expiry site, calendar-day comparison, strictly-greater-than-60, only PENDING matches), `implementation/routes_transfers.py:99-107` (match creation, PENDING at birth), `routes_transfers.py:135-174` (confirm requires PENDING; reject flips the match to EXPIRED directly without consulting the window — so the edit's wording is scoped to clock-driven expiry only and does not touch the reject path), `domain.py:357-359` (`open_exceptions` counts PENDING or EXPIRED matches — consistent, since the edit only defines how EXPIRED arises), `routes_members.py:137-140` (termination gate reads PENDING matches only — unaffected), `app.py:50-57` (clock endpoint is the only caller of `run_timed_evaluations`, matching the PRD's existing "next timed evaluation" phrasing). Grepped all of `implementation/` for `EXPIRED`/`MATCH_WINDOW`/`match window` — no other path touches the subject.
  - (c) Wording adjustment: kept the existing "more than the match window ... on the next timed evaluation" structure and inserted only the length pin plus the measurement convention and boundary sentence; deliberately did not restate the trigger (§2.4 already pins clock-advance as the evaluation moment) and did not mention the reject path (which flips matches to EXPIRED independently), so every enumerated path remains accurately described.

## Step 9: Complete PRD Scan — 2026-09-29T22:41:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_3077_electronic_mortgage_registry_membership_transfer_reporting/workspace/PRD_COMPLETED.md` is written.

## Summary

**Source vs output:** `PRD_FINALIZED.md` 327 lines / 55,441 chars → `PRD_COMPLETED.md` 327 lines / 58,320 chars (+2,879 chars, 21 in-place hunks, no lines added or removed — all revisions are inline).

**Counts:** 17 ambiguity-pins, 4 mismatch-revisions.

**Changes (section — kind — class — what — impl anchor):**

- §2.3 — insert — ambiguity — list sort ties broken by `id` ascending after `created_at` — domain.py:158
- §2.4 — revise — mismatch — timed evaluations run on every clock *set* (forward or back), not only "advancing"; also pins that system timestamps come from the logical clock, serialized whole-second — app.py:50-57, db.py:27-29
- §2.7 — insert — ambiguity — rates/scores published as JSON numbers — domain.py:282-291
- §2.9 tier 5 — insert — ambiguity — acting-member identity (`X-User-ID`) resolved as a Member yields `ERR_MEMBER_NOT_FOUND` — routes_loans.py:31-33, routes_transfers.py:32-34
- §2.9 tier 7 — insert — ambiguity — member lifecycle state errors (activate/suspend/reinstate/terminate from wrong status) reported as `ERR_MEMBER_NOT_ACTIVE` — routes_members.py:76-78,92-93,104-105,122-124
- §2.9 tier 9 — insert — ambiguity — `ERR_SIGNER_NOT_AUTHORIZED` also guards revoking a non-ACTIVE signer — routes_members.py:268-269
- §2.9 tier 12 — insert — ambiguity — malformed signer window reported before overlap within the tier — routes_members.py:195-206
- §2.9 tier 13 — revise — mismatch — rights-holder check precedes self-transfer check (was listed in reverse) — routes_transfers.py:56-67
- §3.1 — insert — ambiguity — activation/suspension/reinstatement from a wrong status refused with `ERR_MEMBER_NOT_ACTIVE` — routes_members.py:76-111
- §3.1 — insert — ambiguity — revoking a non-ACTIVE signer refused with `ERR_SIGNER_NOT_AUTHORIZED` — routes_members.py:268-269
- §3.4 — revise — mismatch — guard narrative reordered to impl (receiver resolution+activeness before loan state; holder before self-transfer) — routes_transfers.py:28-67
- §3.4 — insert — ambiguity — `from_member_id` is pre-transfer current investor for BENEFICIAL/BOTH, current servicer for SERVICING — routes_transfers.py:73-74
- §3.4 — insert — ambiguity — match answering requires the acting member to be ACTIVE; party check precedes match-state check — routes_transfers.py:142-147
- §3.4 — insert — ambiguity — auto-finding on rejection pins `expected_value`=transfer's `from_member_id`, `actual_value`=`to_member_id` — routes_transfers.py:164-172
- §3.5 — insert — ambiguity — DRAFT review born with placeholder `sample_size` 0 / `discrepancy_score` 0.0 — routes_qa.py:35-36
- §3.5 — insert — ambiguity — settle returns the settled review (sanction visible via sanction endpoints) — routes_qa.py:199
- §3.5 — insert — ambiguity — appeal window measured in truncated calendar days vs `created_at`; state guard precedes window check — routes_qa.py:230-237
- §3.5 — insert — ambiguity — `reduced_total_cents` must be an integer, else `ERR_INVALID_REQUEST` — routes_qa.py:262-264
- §3.7 — insert — ambiguity — termination requires an ACTIVE member (`ERR_MEMBER_NOT_ACTIVE`) — routes_members.py:122-124
- §3.8 — revise — mismatch — superseded-run open exceptions' `detail` gets `" (superseded)"` appended, not set — routes_sor.py:33-37
- §3.8 — revise — mismatch — malformed records (`min` not a string) fail before the run is created (impl raised mid-creation), supersession of the prior OPEN run still precedes the failure — routes_sor.py:30-58
- §3.8 — insert — ambiguity — exception resolution: only the run's owning member may resolve (wrong member draws `ERR_NOT_SANCTION_PARTY`); run-not-OPEN precedes exception-not-OPEN; non-string `resolution_note` is `ERR_INVALID_REQUEST` after state guards; note appended to `detail` after ` | ` — routes_sor.py:139-152
- §3.9 — insert — ambiguity — borrower-inquiry response echoes the presented `min` — routes_loans.py:177

Notable existing PRD pins verified against impl with no change needed: 60-day match window, 10-day grace, tiered late fees (2500/5000/10000), per-line round-then-sum sanction math, MINOR base of 25,005 cents, Luhn construction, standing-band boundaries, and all error-to-HTTP mappings in §5.

## Pipeline Complete — 2026-09-29T22:41:00.000Z

All 9 steps finished. Final state: 75 tests (36 difficulty + 39 corner), 8/8 stability rounds green under `--isolation per-test-server`. Artifacts: SCAFFOLD.yaml + both design indices, PRD.md → PRD_FINALIZED.md (1 pin: 60-day match window) → PRD_COMPLETED.md (21 inline pins), test_helpers/ + test_suite/, workspace/implementation/ (Python+Flask, in-memory, no seeding).
