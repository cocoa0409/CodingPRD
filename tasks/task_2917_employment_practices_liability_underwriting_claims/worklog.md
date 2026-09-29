# Worklog — task_2917_employment_practices_liability_underwriting_claims

## Step 1: Create task directory — 2026-09-05T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2917_employment_practices_liability_underwriting_claims/` and its `workspace/` subdirectory. Index 2917 was pre-assigned by the orchestrating prompt; no scan of ./tasks/ was performed and no index was auto-allocated.

## Step 2: Generate scaffold — 2026-09-05T18:24:07.000Z

Subagent summary (verbatim):

Done. All three scaffold artifacts are complete and the lint is clean.

Output files (all under `tasks/task_2917_employment_practices_liability_underwriting_claims/`)

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3140 | 170,755 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2722 | 188,423 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4263 | 275,742 |

SCAFFOLD.yaml (§1.0–§1.7), `api_prefix: /epli`
- 13 entities (Jurisdiction, RatePlan, Applicant, RiskManagementService, ExposureAssessment, Policy, Claim, RelatedClaimGroup, PreSuitResolution, IndemnityPayment, DefensePanelFirm, DefenseAssignment, DefenseInvoice), topology `graph`, consistency `immediate`
- 12 state machines, 3 OCC concurrency rules (§1.2.1: `assessment-create-stale-applicant`, `payment-create-stale-policy`, `group-attach-stale-group`)
- 12 calculations (incl. dual-variant `indicated_premium` QUOTE/BOUND_AUDIT, `exposure_score` weighted scoring, `indemnity_waterfall`, `claim_retention` with stacking multipliers, `panel_firm_selection`, `blended_rate`, `invoice_audit`)
- 32 validations on a 10+ priority ladder, 71 errors, 63 endpoints (26 GET / 36 POST / 1 PATCH), 7 roles with `segregation_of_duties` role model and three four-eyes gates
- Contains no `scaffold_difficulty_design` / `scaffold_corner_design` keys (15 top-level keys, all §1.0–§1.7)

SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)
Single top-level key. 9 rule_ids / 24 instances: `dual_variant_calc` (2), `combinatorial_formula` (2), `non_linear_state_machine` (2), `transitive_cascade` (3), `priority_pair_validation_conflict` (3), `boundary_precision_check` (3), `cross_entity_state_dependency` (3), `resource_temporal_overlap` (3), `compensating_invariant` (3).

SCAFFOLD_CORNER_DESIGN.yaml (§1.9)
Single top-level key, the nine guide sections only, 75 instances = 52 full `test_recipe`s + 23 `excluded_because` stubs (every stub's `difficulty_instance` resolves to a real §1.8 instance; no stub carries a `test_recipe`):
entities 11 · state_machines 15 · calculations 13 · validations 18 · endpoints 4 · errors 4 · rbac 4 · cross_cutting_complexity_layers 5 · consistency_model 1

Verification: §1.5 endpoints declared 63; §1.1 entities 13; §1.8 instances 24; §1.9 instances 52; calls scanned 1006. VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5. All three files parse under PyYAML; all 71 error ids appear in the design files; no forbidden concurrency vocabulary.

Flags raised by the subagent:
1. `SCAFFOLD.yaml`'s `scenario:` block still opened with `Generate task harder than expert level!` — known leak path into PRD.md.
2. Numeric anchors computed with Decimal/ROUND_HALF_UP: premium `1803600` (hc 40 / TX T2 / 4 separations / agg 10,000,000 / retention 2,500,000, no risk services) and `1690374` (same applicant with one ACTIVE 0.06 hotline credit); downstream steps should reuse verbatim rather than recompute.

Orchestrator action after Step 2: stripped the leading `Generate task harder than expert level!` line (plus the following blank line) from `SCAFFOLD.yaml`'s `scenario:` block so the difficulty directive cannot reach PRD.md via the doc generator. Re-verified the file still parses under PyYAML with all 15 §1.0–§1.7 top-level keys; SCAFFOLD.yaml is now 3138 lines. Grep confirms the phrase appears in none of the three scaffold files.

## Step 3: Copy shared files — 2026-09-05T18:24:07.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (bash only, no subagent).

## Step 4: Generate PRD — 2026-09-05T18:39:12.000Z

Subagent summary (verbatim):

PRD generation for task_2917 is complete. All three Hard Contracts verified mechanically (twice).

Output: `workspace/PRD.md` — 480 lines, 105,014 characters. Built in 11 incremental appends (initial `Write` + 10 heredoc/script appends); no single call exceeded the output cap. `tail -40` confirms the file ends on the last row of the §5 error table (`ERR_DUPLICATE_PANEL_FIRM_NAME | 409`) — a real section boundary, with no audit footer, no contract-report block, and no trailing prose.

Section list
- §1 Introduction (3 paragraphs; `/epli` mount, basis drift, limit conservation)
- §2 Global Specifications — 2.1 Role-Based Access Control · 2.2 API Response Structure (fixed verbatim) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and Revision Counters · 2.5 The Logical Clock · 2.6 Money, Hours and Rounding Discipline · 2.7 Optimistic Concurrency on Parent Revisions · 2.8 Validation Precedence · 2.9 Nested Paths and Reverse-Reachability Reads · 2.10 Segregation of Duties · 2.11 Cascade Discipline and the Two Policy Axes · 2.12 Interval Conventions and Reference-Data Uniqueness
- §3 Business Logic — 3.1 Carrier Reference Data and the Defense Panel Roster · 3.2 Applicant Intake, Exposure Data and the Risk-Management Credit Basis · 3.3 Exposure Scoring, Referral and the Quoted Premium · 3.4 Binding Coverage and the Bound-Premium Audit · 3.5 Coverage Availability: Suspension, Reinstatement and Expiry · 3.6 Claim Intake, Coverage Bucketing and the Coverage Decision · 3.7 Retention Mechanics · 3.8 Defense Counsel: Panel Selection, Engagement, Billing and Guideline Audits · 3.9 Indemnity Settlement, Limit Erosion, and Closing the File
- §4 Endpoint Definitions — status-code paragraph + 63-row table, exactly 4 columns
- §5 Error Code Catalogue — 71-row table, exactly 2 columns

Contract reports — Field coverage: entities[].fields 135/135, endpoints[].request_body 73/73, query_params 23/23, path_params 13/13. PASS.
Rule coverage: 32/32 validations with priority (numbered strict order in §2.8 plus all 6 validation_priority_notes tie-breaks); 3/3 OCC rejections (expected_*_version + ERR_STALE_APPLICANT_VERSION / ERR_STALE_POLICY_VERSION / ERR_STALE_GROUP_VERSION + HTTP 412); 59/59 transitions across 12 machines; 12/12 calculations in operator-free prose; 32/32 validation conditions matchable to error_id; 32/32 side_effects/applies_to; 162/162 structured field contents; 14/14 sibling-branch symmetry groups. PASS.
Path purity (§3 only): 773 backtick tokens scanned (296 unique), 0 starting with `/`, 0 bare HTTP-method tokens, 0 method+path tokens. PASS.

Coverage confirmation: all 13 entities, 12 state machines (59 transitions incl. both Policy axes and every cyclic loop), 12 calculations, 32 validations with priority ordering, 63 endpoints, 71 error IDs (each also named in §1–§3 prose, not only in the §5 table), and all 7 roles including the two entity-backed ones are described in prose. Every one of the 71 error IDs and all 59 state names appear verbatim.

Notes from the subagent:
- Withheld files were never opened; no other `task_*/` directory was touched; scratch lived only in `/tmp/task_2917_prd/`.
- Fidelity judgement call: the scaffold pins no error ID for engaging defense counsel on a claim whose own status is neither `COVERAGE_ACCEPTED` nor `DEFENSE_OPEN`. Rather than invent an ID, §3.8 states that precondition in prose without naming a code, and names `ERR_POLICY_NOT_IN_FORCE` only for the policy-level gate the scaffold does attribute to it.
- Closing a claim: the scaffold's `COVERAGE_DENIED → CLOSED` transition lists no assignment-closing side effect while the endpoint description does, so §3.9 states the assignment closure at the action level for both source states and notes a denied claim will normally have no assignments.

Orchestrator anti-truncation verification: `wc -l -c` = 480 lines / 105,014 chars; `tail` ends at the final row of the §5 error-code table, a real section boundary — not mid-sentence. Grep for `harder than expert` and `scaffold` in PRD.md returns nothing, confirming neither the difficulty directive nor scaffold-internal vocabulary leaked. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-05T19:40:03.000Z

Subagent summary (verbatim):

Test generation is complete. All 16 test files, both output directories at the task root, nothing written under `workspace/`.

Files written

`test_helpers/` — 1,515 lines: `__init__.py` 16 · `types.py` 152 · `constants.py` 68 · `api_errors.py` 173 · `test_users.py` 76 · `factories.py` 334 · `fixtures.py` 223 · `api_client.py` 368 · `assertions.py` 105

`test_suite/` — 6,621 lines, 100 tests: `conftest.py` 47 · `test_01` 256 (4) · `test_02` 181 (4) · `test_03` 293 (4) · `test_04` 365 (6) · `test_05` 273 (6) · `test_06` 330 (6) · `test_07` 270 (6) · `test_08` 399 (6) · `test_09` 404 (6) · `test_10` 478 (11) · `test_11` 465 (8) · `test_12` 480 (7) · `test_13` 1099 (12) · `test_14` 578 (7) · `test_15` 279 (3) · `test_16` 424 (4)

Coverage
- Queue A (difficulty, §1.8): 48 tests / 24 of 24 instances, every instance carrying >=2 tests.
- Queue B (corner, §1.9): 52 tests / 52 of 52 live instances, one test each. The 23 `EXCLUDED_STUB` entries were not translated (verified: no `Design:` tag names a stub, and every stub's cross-reference resolves to a difficulty instance that is covered).
- Every test docstring ends in exactly one `Design:` line resolving to a real `name:` in the design YAMLs; every `PRD: "..."` quote is a verbatim (whitespace-normalized) substring of `workspace/PRD.md`. All 16 files pass the citation checker "clean" and `python3 -m py_compile`. A cross-module symbol audit confirms no `T.`/`U.`/`E.`/`F.`/`S.`/`api.` reference is undefined.

Instances skipped: none

Design/PRD conflicts resolved PRD-first (assertion narrowed, instance kept)
- Difficulty inst. 3 (`test_02`): `litigation_guideline_version: "LG-2026.1"` -> PRD's integer `1`.
- Difficulty insts. 18, 19 (`test_08`): temporal figures re-derived from the PRD's half-open window rules.
- Corner inst. 2 (`test_10`): list order is `blended_rate_cents` then `created_at`, not `created_at` alone. Corner inst. 7: `updated_at > created_at` dropped — the clock is pinned, so they are equal.
- Corner inst. 15 (`test_11`): audit output figures recomputed from the guideline caps.
- Corner insts. 43, 49, 66 (`test_13`, `test_15`): the design says `billed_amount_cents`; PRD line 302 names the field `billed_fees_cents`. Also, PRD line 298 ("Invoices are created in `SUBMITTED` with every audit output field unpopulated") contradicts the designs' assertion of a populated `billed_amount_cents` on a `SUBMITTED` invoice — asserted nulls at `SUBMITTED` and the real figures after audit instead. The instances' actual claims (`ERR_INVOICE_OUTSIDE_ENGAGEMENT` outranking `ERR_INVOICE_PERIOD_OVERLAP`; `ERR_NOT_ASSIGNED_COUNSEL`) are intact.
- Corner inst. 50 (`test_13`): retention fields asserted on a claim its own trigger leaves in `REPORTED`; PRD line 268 computes retention only on `ACCEPT` — those two sub-assertions omitted.
- Corner inst. 64 (`test_14`): the design's third case (unknown principal `nobody-999`) asserts `ERR_UNAUTHENTICATED`, but PRD lines 17/120 scope 401 strictly to an absent/empty `X-User-ID` (an unrecognised role is `ERR_UNAUTHORIZED` 403). Kept the two header-based 401s plus the "write was not applied" check (`total_count == 0`); dropped the non-derivable claim.
- Corner inst. 65 (`test_15`): the design's "no Applicant named Rogue Holdings LLC exists afterwards" is unverifiable — the PRD exposes no `GET /epli/applicants` list. Dropped that sub-assertion; the clock-unmoved claim is proved instead by an accepted equal re-set (PRD line 96 permits equal, refuses earlier).
- Corner inst. 71 (`test_16`): the design groups three `REPORTED` claims yet asserts `shared_retention_cents` / `per_claim_retention_cents`, which PRD line 268 only populates on `ACCEPT`. Accepted the three claims so every asserted figure (2,500,000 -> 3,750,000, basis flipping to c3) is PRD-derivable; the `ERR_STALE_GROUP_VERSION` claim is unchanged.
- Corner inst. 63 (`test_14`): the design's dispute payload omits the mandatory `dispute_note`, which would report `ERR_INVALID_REQUEST` (shape) ahead of the intended `ERR_INVOICE_NOT_DISPUTABLE` (priority 8); supplied the note so the instance's precedence claim is what actually gets tested.

No server was started, no `pkill` run, `worklog.md` untouched, scratch confined to `/tmp/task_2917_tests/`.

Orchestrator verification: `test_helpers/` (9 files) and `test_suite/` (17 files) are both at the task root; `find workspace -name test_suite -o -name test_helpers` returns nothing, so no stray copies landed under `workspace/`.

## Step 6: Generate implementation — 2026-09-05T19:40:03.000Z

Subagent summary (verbatim):

All three smoke servers are killed (PIDs 648134 / 648765 / 669649 confirmed gone; no broad pkill used), `__pycache__` removed, every module `py_compile`-clean.

Location: `workspace/implementation/`

| Module | Lines |
|---|---|
| `app.py` | 73 |
| `calc.py` | 309 |
| `validate.py` | 323 |
| `store.py` | 159 |
| `serialize.py` | 254 |
| `errors.py` | 95 |
| `envelope.py` | 69 |
| `services/ledger.py` | 353 |
| `routes/underwriting.py` | 541 |
| `routes/claims.py` | 545 |
| `routes/defense.py` | 392 |
| `routes/reference.py` | 282 |
| `routes/common.py` | 52 |
| `routes/__init__.py`, `services/__init__.py` | 0 |
| total Python | 3447 |

Plus `start.sh` (guarded `pip install`, then `exec python3 app.py`, binds `0.0.0.0:${PORT:-10000}`) and `requirements.txt` (`flask>=2.0`).

Endpoints: 63 of 63 from PRD §4 (`grep` of `@bp.<verb>` decorators = 63). Storage is in-memory dicts only — no sqlite, no file I/O, no `/tmp`, zero seeded rows (the only `json.dump` hit is response serialization). Requests are serialized behind a WSGI lock since the domain logic mutates shared dicts.

Verification: three end-to-end smoke rounds on freshly booted servers on random high ports (~150 assertions total), no traceback or 500 in any server log. Round 1 covered the full underwriting->bind->claim->panel->invoice->payment happy path; round 2 covered staling/OCC/groups/pre-suit/suspend-reinstate cascade/dispute/reopen limit/precedence; round 3 covered sublimit carve-outs, `WAGE_HOUR`/`THIRD_PARTY`/`FIRST_PARTY` bucket precedence, exact-fit equality on each limit gate, the four-hop exhaustion cascade (assignment `CLOSED` + `funding_ceased_at`, invoices `REJECTED`/`LIMIT_EXHAUSTED`, firm capacity freed), posture regression on void without resurrecting the cascade, pagination/filter validation and role/ownership gates. Every residual "FAIL" line traced to a wrong hand-computed expectation in the subagent's own scratch scripts (e.g. exposure 72.00 not 62.00, base premium 3,078,000 not 3,330,000, `ERR_CLOCK_NOT_MONOTONIC` is 422 not 409 per §5, `GET /claims/{id}` legitimately admits `PanelCounsel` while `GET /claims` does not, retention outranks budget cap per §2.8 items 25->26, own-state 409 outranks cross-entity 409 per items 8->9) — no implementation change was warranted for any of them.

PRD ambiguities resolved (choice made):
1. `ERR_GROUP_LOCKED` vs `ERR_SEGREGATION_OF_DUTIES` on payment approval — §3.9's narrative puts SoD first; §2.8 puts cross-entity state (item 9) before SoD (item 10) and declares "the order below is the whole of it". Chose the §2.8 table: group-locked wins.
2. Row timestamps vs logical clock — `created_at`/`updated_at` use wall-clock UTC truncated to ms (3 digits everywhere) with a hidden monotonic `_seq` as the final sort tie-break; the logical clock supplies only business instants (`completed_at`, `mediation_offered_at`, `suspended_at`, `funding_ceased_at`).
3. Unnamed state errors — binding a non-`APPROVED` assessment -> `ERR_ASSESSMENT_NOT_DECIDABLE`; assignment creation on a claim outside {`COVERAGE_ACCEPTED`,`DEFENSE_OPEN`} -> `ERR_POLICY_NOT_IN_FORCE` (§3.8 wording); pre-suit accept with the claim outside {`UNDER_REVIEW`,`COVERAGE_ACCEPTED`,`DEFENSE_OPEN`} -> `ERR_RESOLUTION_NOT_ACCEPTABLE`.
4. `offer_expires_at` not strictly after the clock -> 400 `ERR_INVALID_REQUEST` in the shape stage (§3.7 states it as a field constraint).
5. Invoice approval does not run the exhaustion cascade — §2.11/§3.9 attribute hops 3-4 to payment approval alone; invoice approval only recomputes ledgers and posture.
6. Payment approval does not require the policy in force — §3.5's in-force list governs drafting, not release.
7. Ledger/posture fields are computed at serialization time (no stored drift); group `status` is stored and toggled only by payment approve/void.
8. Version bumps: one per row per request; policy bumped on payment creation and on every payment/invoice approve/void; firm bumped on assignment create and close.
9. PATCH applicant stales assessments when an assessment-relevant field is supplied (not only when the value changes); supplying only `separations_since_assessment` never stales.
10. Explicit `null` in a body is treated as absent; required strings must be non-empty; OCC version fields carry no range so a mismatch yields 412, never 400.
11. `per_claim_retention_cents`/`applied_retention_cents` stay null until the coverage ACCEPT branch and are treated as 0 in arithmetic.
12. Entity-backed principal scope: `PolicyholderContact` single reads of another applicant's rows -> `ERR_OWNERSHIP_MISMATCH` after the 404, lists silently filtered; `PanelCounsel` scoping applies only to defense-assignment/defense-invoice rows, not to claims or panel-firm reference rows.

Orchestrator note: Steps 5 and 6 were launched concurrently in a single assistant message, so the implementation generator ran before `test_suite/` existed on disk and could not have read it.

## Step 7: Run tests and iterate — 2026-09-05T20:01:22.000Z

Subagent summary (verbatim):

All 8 rounds green, 100/100. `worklog.md` untouched (still 18024 bytes, 19:40 timestamp).

Iterations run: 2 (sweep -> 3 deterministic failures -> 3 fixes -> clean sweep)

Iteration 1 was 97/100 in all 8 rounds with the identical 3 failures every round — zero flakiness, so no load-induced noise to discount.

Tests deleted: none. All three defects were localized assertions inside otherwise PRD-faithful tests, so STEP 1c (partial coverage) applied: the uncovered assertion was removed and the covered body kept. Test count stayed at 100.

Fixes applied to `test_suite/` (all three were test-artifact bugs; `implementation/` was correct):

1. `test_suite/test_01_premium_variants_and_retention_bases.py:108` — `test_bound_audit_variant_diverges_from_the_quote_it_audits` did `validate_success(...)["data"]`. The runner's `validate_success` already returns `body["data"]`, so this was the known double-unwrap -> `KeyError: 'data'`. Removed the extra `["data"]`. Hand-verified the test's expected arithmetic before touching it, and every figure is exactly right: base 14278501 (CA 262x35696.25->9352418 + TX 138x35696.25->4926083, each share rounded before summing), quote net 17360516, bound-audit net 19844261 at turnover 35.00 with only the pre-inception HOTLINE credit of 0.08, variance +2483745. So this was purely the unwrap, not a masked calculation defect.

2. `test_suite/test_13_validations.py:988` — `test_defense_invoice_approval_waits_for_the_retention_and_a_live_assignment` asserted `approved_by_user_id` on an approved defense invoice. PRD-silence (response-field silence): §2.1 enumerates the recorded-principal fields exhaustively — "as `priced_by_user_id` or `approved_by_user_id` on an exposure assessment, as `audited_by_user_id` on a defense invoice, and as `created_by_user_id` or `approved_by_user_id` on an indemnity payment" — naming only `audited_by_user_id` for an invoice, and §3.8's approval paragraph lists the side effects without any approver stamp. Removed that one key; the surrounding `status`/`allowed_amount_cents`/budget/ledger assertions all stay. The two other `approved_by_user_id` references in the suite are on exposure assessments and are PRD-covered — left alone.

3. `test_suite/test_15_rbac.py:198-200` — `test_panel_counsel_can_only_bill_its_own_assignments` asserted that a non-assigned `PanelCounsel` principal may still read another firm's assignment. This fails unique derivability; PRD admits both readings. §2.1 says the counsel ownership check applies to "any resource that references a `DefensePanelFirm`" and §2.8 item 6 says that check guards "every read performed by an entity-backed principal" (implementation's reading: refuse with `ERR_NOT_ASSIGNED_COUNSEL`); but §2.1's "so" clause narrows the consequence to "may only submit or dispute invoices", and §4 lists `PanelCounsel` among the authorized roles for the assignment read (test's reading: read is open). Removed the cross-firm read assertion only — the test's actual subject, that submit and dispute are both refused with `ERR_NOT_ASSIGNED_COUNSEL`, is verbatim-covered and still asserted, and its audit math (billed 510000, rate-cap excess 60000, allowed 450000) still passes. This was the only cross-firm PanelCounsel read in the suite, so the suite is now silent on the ambiguous point rather than asserting one of two readings.

Fixes applied to `implementation/`: none. No PRD-required check was weakened and no code was touched.

Final per-round results: rounds 1-8 all 100/100 (0 failed, 0 errors, 0 skipped).

Orchestrator verification: independently re-read all eight `workspace/implementation/results.$i.json` (each 30.6 KB, mtime 19:56) — every round reports `passed: 100, failed: 0, total: 100, errors: 0, skipped: 0`, and `sweep.log` contains `SWEEP_DONE`. The sweep artifacts exist and match the subagent's claim.

Step 8 decision: Step 7 applied 3 `test_suite/` fixes, so the skip condition (0 deletions, 0 test_suite fixes, 0 test_helpers fixes, 0 implementation fixes) does NOT hold — Step 8 runs. Note the three fixes are all assertion removals at PRD-silence / non-unique-derivability sites, and zero `implementation/` fixes were made; Step 8 is therefore expected to produce a very small diff (pinning the invoice-approval approver-stamp silence and the PanelCounsel cross-firm read ambiguity, both in the direction the implementation already chose), and a byte-identical PRD_FINALIZED.md would also be a legitimate outcome here.

## Step 8: Finalize PRD — 2026-09-05T20:05:02.000Z

Subagent summary (verbatim):

PRD_FINALIZED.md produced with three targeted edits.

Line counts
- `PRD.md`: 480 lines / 105,014 bytes
- `PRD_FINALIZED.md`: 480 lines / 105,918 bytes
- delta = 0 lines (all three edits are inline insertions/revisions inside existing long paragraphs); +904 bytes = +0.86 %

Changes
- §2.1 (identity semantics, `PanelCounsel` sentence) — insert — pinned that the firm comparison also scopes reads: a single-resource read of a defense assignment or defense invoice belonging to another firm is refused with `ERR_NOT_ASSIGNED_COUNSEL`, the two list endpoints return only the calling firm's rows (with `total_count` post-filter), and no other authorized `PanelCounsel` read is narrowed (claims and the panel roster stay open) — `routes/common.py:23-32`, `routes/defense.py:35,53,194,210`, `routes/claims.py:42-45`, `routes/reference.py:20-22`.
- §2.8 item 6 — revise — "every read performed by an entity-backed principal" -> "exactly those reads by an entity-backed principal that §2.1 narrows", so item 6 no longer over-promises a guard the impl does not apply to counsel claim/roster reads — `routes/claims.py:41-45`, `routes/common.py:23`.
- §3.8 (invoice approval paragraph) — insert — no approver identifier is recorded on an invoice; `audited_by_user_id` is the only stamped principal and approval leaves its last-audit value intact — `routes/defense.py:337-371`, `serialize.py:205-228`.
- Step 7 item 1 (test_01 double-unwrap) — no PRD edit. Verified the test's assertions are verbatim-PRD (quoting vs bound-audit variant per §3.3/§3.4) and the failure was purely `validate_success(...)["data"]`.

Per-edit pre-edit search log

Edit A — §2.1 counsel read scoping
- (a) Subject: what the `PanelCounsel` firm-ownership comparison applies to (writes and reads), and which resources it does not cover.
- (b) Enumerated/read: `routes/common.py` (`scope_counsel_firm`, `own_firm_filter`, `assignment_firm_id`, `invoice_firm_id`); every call site via grep — `routes/defense.py:35` (get assignment), `:53` (list assignments), `:194` (get invoice), `:210` (list invoices), `:243` (submit), `:323` (dispute); non-scoped counsel-authorized reads: `routes/claims.py:41-45` (`CLAIM_ONE_READERS = ALL_STAFF + ("PanelCounsel",)`, no scoping) and `routes/reference.py:20-22` + firm read handlers (no scoping); ordering vs 404 (`store.find` precedes every scope call) and vs own-state (`scope_counsel_firm` precedes the `ERR_INVOICE_NOT_DISPUTABLE`/`ERR_ASSIGNMENT_CLOSED` checks) to keep §2.8 precedence intact; `envelope.list_response` to confirm `total_count` is computed after `own_firm_filter`.
- (c) Adjustment: narrowed the claim from "every read" to exactly defense assignments and defense invoices, and added the explicit carve-out that claim reads and panel-roster reads are not narrowed — the impl leaves both open, so an unqualified "all reads are firm-scoped" would have been a new mismatch. Also stated list behaviour as filtering (not erroring), matching `own_firm_filter`.

Edit B — §2.8 item 6 phrase
- (a) Subject: the set of reads that the cross-aggregate ownership check (item 6) actually guards.
- (b) Enumerated/read: same call-site set as Edit A, plus the `PolicyholderContact` side (`scope_applicant` at `routes/underwriting.py:59,139,242,402`; `own_applicant_filter` at `:157,260,425`) to confirm §2.1's applicant scoping is the other half of "entity-backed" and is unchanged; §4's "entity-backed roles are additionally narrowed ... as described in §2.1" to confirm §2.1 is the right single point of truth.
- (c) Adjustment: made item 6 defer to §2.1 rather than restating a scope, so the two sections cannot be read against each other; deliberately did not enumerate endpoints twice.

Edit C — §3.8 invoice-approval approver stamp
- (a) Subject: principal identifiers written onto a `DefenseInvoice` row across its whole lifecycle.
- (b) Enumerated/read: grep for `approved_by_user_id` (only `routes/underwriting.py:300,374` assessments and `routes/claims.py:465,506` payments — never invoices) and for `audited_by_user_id` (`routes/defense.py:275` init null, `:294` audit sets, `:331` dispute clears, `:345` SoD compare); `routes/defense.py:337-371` approve (status/touch only), `:374-392` void (`void_reason` only), `services/ledger.py:322` exhaustion cascade (`hold_reason`/status only); `serialize.py:205-228` invoice field list (no `approved_by_user_id`).
- (c) Adjustment: phrased as "approval leaves it holding whatever value the last audit wrote" rather than "audit is the only writer", so the sentence stays true for the dispute path that clears the field to null and for void/reject paths that never touch it.

Orchestrator verification: `PRD_FINALIZED.md` exists and is 480 lines / 105,918 bytes; `cmp` against `PRD.md` confirms it DIFFERS (three inline edits, +904 bytes), which is the expected outcome given Step 7 recorded three PRD-silence/ambiguity sites.

## Step 9: Complete PRD — 2026-09-05T20:36:25.000Z

Orchestrator decision: Step 9 was run as THREE sequential file-partitioned passes over one shared `PRD_COMPLETED.md` (pass 1 did the single `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden to copy or overwrite). A single-pass Step 9 on a 480-line / 105 KB PRD against a 3,447-line implementation reliably under-scans and can return a byte-identical file; partitioning by implementation module bounds each pass's reading budget while keeping the whole implementation in scope across the three.

Partition: pass 1 = cross-cutting + reference (`app.py`, `envelope.py`, `errors.py`, `store.py`, `routes/common.py`, `routes/reference.py`, generic `validate.py`, envelope + reference serializations). Pass 2 = underwriting (`routes/underwriting.py`, `calc.py`, Applicant / RiskManagementService / ExposureAssessment / Policy serializations). Pass 3 = claims + defense (`routes/claims.py`, `routes/defense.py`, `services/ledger.py`, `calc.defense_invoice_audit`, Claim / RelatedClaimGroup / PreSuitResolution / IndemnityPayment / DefenseAssignment / DefenseInvoice serializations) plus a final cross-pass consistency read.

### Pass 1 summary (verbatim)

`cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` performed exactly once, first thing. PRD_FINALIZED.md: 480 lines, 105918 bytes. PRD_COMPLETED.md: 480 lines, 111142 bytes (17 lines revised in place, no new lines/sections, all via targeted Edit calls).

Counts: ambiguity-pins 14; mismatch-revisions 2 (§5 transport-level status codes; §3.1 `jurisdiction_codes` "unique" -> duplicates rejected rather than de-duplicated); 1 edit is both (§3.2 duplicate code error class).

Changes:
- §2.1 — revise — ambiguity — whitespace-only `X-User-ID` is unauthenticated; absent/unknown/case- or whitespace-differing `X-User-Role` is `ERR_UNAUTHORIZED` — `validate.py:60-65`
- §2.1 — insert — ambiguity — `PolicyholderContact` service/assessment/policy lists return only own rows with `total_count` counting just those — `routes/common.py:17-20`, `routes/underwriting.py:157,260,425`
- §2.2 — revise — ambiguity — `api_request_id` = `req_` + exactly 20 chars from A-Z/0-9 — `envelope.py:11,14-15`
- §2.2 — revise — ambiguity — `api_request_timestamp` is host-clock, `Z`-suffixed, does not track `current_utc` — `envelope.py:18-22`
- §2.3 — insert — ambiguity — no upper bound on `offset`; offset >= `total_count` gives empty `data`, `has_more` false — `validate.py:290`, `envelope.py:55-63`
- §2.3 — insert — ambiguity — creation-order final tie-break makes every list totally ordered — `routes/common.py:35-39`, `store.py:81`
- §2.4 — revise — ambiguity — `created_at`/`updated_at` are host-wall-clock bookkeeping stamps (not logical clock), read only for ordering/tie-breaks — `store.py:70-92`
- §2.5 — revise — ambiguity — expiry tested before inception (already-past `BOUND` policy goes straight to `EXPIRED`, expired ids only); `PENDING` services never lapse; offers lapse only strictly past `offer_expires_at`; the four id lists hold only transitioned rows, in creation order — `routes/reference.py:242-282`
- §2.6 — insert — ambiguity — percentage/score/hours fields render as JSON numbers, trailing zeros not significant — `envelope.py:25-33`, `serialize.py:9-14`
- §2.7 — insert — ambiguity — requests are serialised one at a time, never interleaved — `app.py:55-68`
- §2.8 item 3 — insert — ambiguity — blank body = `{}`; non-object body 400; explicit `null` = omitted; strict types (bool!=int, `5.0`!=int, non-finite rejected, blank strings rejected, no trimming); ISO-8601 grammar accepted (optional seconds, 1-9 fractional digits, `Z`/+-offset/none = UTC) and normalised to UTC — `validate.py:72-83,93-119,126-140,246-255`
- §2.9 — insert — ambiguity — id/code-shaped filters are never existence-checked (empty page, not 404); undefined query parameters ignored — `validate.py:306-310`, `routes/reference.py:161-167`
- §2.12 — insert — ambiguity — uniqueness and jurisdiction-code lookups are exact, case-sensitive comparisons — `routes/reference.py:63,117-121,193-197`, `store.py:105-109`
- §3.1 — revise — mismatch — repeated `jurisdiction_codes` entry is `ERR_INVALID_REQUEST`, not de-duplicated; array stored/returned in supplied order — `validate.py:192-204`, `serialize.py:174`
- §3.2 — insert — ambiguity/mismatch — `jurisdiction_headcounts` entries reject extra/missing keys, and a duplicate code is `ERR_INVALID_REQUEST` rather than `ERR_HEADCOUNT_ALLOCATION_MISMATCH` — `validate.py:205-232`
- §4 preamble — insert — ambiguity — trailing slash resolves to the same endpoint — `app.py:21`
- §5 preamble — insert — mismatch — undefined path / unaccepted method return `ERR_INVALID_REQUEST` under HTTP 404 / 405 (table's 400 applies to §2-§3 rules) — `app.py:34-46`

Deliberately not pinned by pass 1: `app.py:49-52`'s catch-all `ERR_INVALID_REQUEST` at HTTP 500 (§5 is a 4xx catalogue; documenting a 500 would legitimise a crash path rather than a specified behavior); ordering within same-error-code situations (unobservable in `error_id`); `excluded_panel_firm_ids` shape latitude (handed to pass 3 as §3.8 text).

### Pass 2 summary (verbatim)

No `cp`, no overwrite, no wholesale `Write` — only targeted `Edit` calls. Before first edit: 480 lines / 111,142 bytes. After last edit: 480 lines / 113,811 bytes. All 16 of pass 1's hunks still differ from `PRD_FINALIZED.md`: the diff shows exactly 26 hunks = pass 1's 16 + 10 new (two of pass 2's edits landed inside paragraphs pass 1 had already revised, lines 179 and 195, with their inserts preserved verbatim).

Counts: ambiguity-pins 13; mismatch-revisions 2.

Changes:
- §2.6 — revise — mismatch — "Exactly two quantities ... carried unrounded" was a false universal: the block-billing share is a third. Now names three and points the third at §3.8 — `calc.py:279`
- §2.8 item 9 — revise — mismatch — the rate-plan-`ACTIVE` requirement and item 9's operation list both omitted the price action, which §3.3 requires; now reads "both for a new assessment and for every re-price" and the list includes "assessment pricing" — `routes/underwriting.py:334`
- §2.12 — insert — ambiguity — the two-uppercase-letter format is imposed only at jurisdiction registration; a reference naming a differently shaped code is `ERR_JURISDICTION_NOT_FOUND`, not `ERR_INVALID_REQUEST` — `validate.py:154`, `routes/underwriting.py:30`
- §3.2 — insert — ambiguity — `separations_since_assessment` is "of at least 0" — `routes/underwriting.py:72`
- §3.2 — insert — ambiguity — `jurisdiction_headcounts` is stored and read back in the order supplied and never reordered, whatever iteration order a calculation imposes — `serialize.py:56`, `calc.py:191`
- §3.2 — revise — ambiguity — the allocation check fires on any revision supplying `total_headcount`, `jurisdiction_headcounts` or `primary_jurisdiction_code`; unsupplied members of the trio come from the stored row, and a revision supplying none of the three skips the check — `routes/underwriting.py:115`
- §3.2 — insert — ambiguity — a service is created in `PENDING` with `completed_at` and `revocation_reason` both null — `routes/underwriting.py:193`
- §3.2 — insert — ambiguity — an already-`REFERRED` assessment's `version` is incremented by 1 too, even when `credit_basis_stale` was already true — `services/ledger.py:214`
- §3.2 — insert — ambiguity — the `version` bump is unconditional: a no-op revision, or one with an empty body, still succeeds and still bumps — `routes/underwriting.py:125`
- §3.3 — insert — ambiguity — `applicant_id` resolves before `rate_plan_id`, so a request naming neither reports `ERR_APPLICANT_NOT_FOUND` — `routes/underwriting.py:281`
- §3.3 — insert — ambiguity — a fresh `DRAFT` carries all six components, `indicated_premium_cents`, both snapshots, `priced_by_user_id`, `approved_by_user_id` and `rejection_reason` null, and `credit_basis_stale` false — `routes/underwriting.py:299`
- §3.3 — insert — ambiguity — the pre-price applicant recompute is not a mutation: it neither bumps `version` nor refreshes `updated_at`, so pricing never invalidates a client's `expected_applicant_version` — `routes/underwriting.py:338` (`bump=False`)
- §3.3 — insert — ambiguity — the bound-audit credit basis is subject to the same two-decimal precision and the same 0.15 ceiling as the applicant's own `risk_credit_pct` — `routes/underwriting.py:448`, `calc.py:102`
- §3.4 — insert — ambiguity — a non-`APPROVED` assessment (including one already `BOUND`) is `ERR_ASSESSMENT_NOT_DECIDABLE` (409), decided before the period-overlap test; the PRD never named a code for this case — `routes/underwriting.py:466`
- §3.4 — insert — ambiguity — bind evaluates only the `BOUND -> ACTIVE` inception test, not expiry, so a policy bound wholly in the past comes back `BOUND` and only reaches `EXPIRED` on the next clock advance — `routes/underwriting.py:483`

Verified-and-unchanged: every formula in `calc.py` within pass 2's slice already matched uniquely (eight premium steps incl. the unrounded per-employee rate, code-ascending per-jurisdiction rounding, all four band tables, gross-excludes-credits, credit-F-on-gross, floor-after-credits; exposure-score four terms with rounding-before-cap and the 0/100 clamp; `hazard_load_pct` q3 with the 0.30 cap; `risk_credit_pct` q2 with the 0.15 cap; `blended_rate_cents`; the retention multiplier stack). All 14 role tuples in `routes/underwriting.py` match the §4 table, all check sequences match §2.8, and every key emitted by `serialize.applicant/service/assessment/policy` already appears in the PRD.

### Pass 3 summary (verbatim)

No `cp`/overwrite; every change a targeted `Edit`. `PRD_FINALIZED.md` untouched (105918 bytes). Before first edit: 480 lines / 113,811 bytes. After last edit: 480 lines / 118,121 bytes. `diff PRD_FINALIZED.md PRD_COMPLETED.md` hunk count: 43 (26 from passes 1+2, all still present at their original line sites, plus 17 new sites).

Counts: ambiguity-pins 16; mismatch-revisions 4.

Changes:
- §3.6 — insert — ambiguity — a newly reported claim's `per_claim_retention_cents` and `applied_retention_cents` are null (not 0) until acceptance; `pre_suit_credit_cents` 0, `denial_reason` null — `routes/claims.py:109-126`, `serialize.py:144-146`, `services/ledger.py:38-45`
- §3.6 — insert — ambiguity — the ACCEPT/DENY `denial_reason` payload rules are §2.8 step-3 shape checks, so they precede resolution of the claim in the path — `routes/claims.py:148-159`
- §3.7 — insert — ambiguity — a non-future `offer_expires_at` is `ERR_INVALID_REQUEST` tested with the shape checks (ahead of the claim 404); offers start with `elapsed_days_at_accept`/`incentive_credit_cents` null; no claim-status gate on offering and several offers may coexist on one claim — `routes/claims.py:345-367`
- §3.7 — insert — ambiguity — a claim outside `UNDER_REVIEW`/`COVERAGE_ACCEPTED`/`DEFENSE_OPEN` reports the same `ERR_RESOLUTION_NOT_ACCEPTABLE` — `routes/claims.py:377-381`
- §3.7 — revise — ambiguity — acceptance replaces `pre_suit_credit_cents` rather than accumulating — `routes/claims.py:403`
- §3.7 — insert — ambiguity — acceptance returns the offer, not the claim — `routes/claims.py:407`
- §3.7 — insert — ambiguity — attach returns the group with its re-derived aggregation, not the claim — `routes/claims.py:309`
- §3.7 — insert — ambiguity — a member whose `per_claim_retention_cents` is null counts as 0 in both group derivations; an all-unaccepted group has shared retention 0 and names its earliest member as basis claim — `services/ledger.py:56-73`
- §3.7 — insert — ambiguity — a never-accepted claim reports `applied_retention_cents` null, and both the waterfall and §3.8's invoice retention gate read that null as 0 — `services/ledger.py:38-45,345-353`, `routes/defense.py:353`
- §3.7 — insert — mismatch — the `OPEN`/`LOCKED` lock is re-evaluated only on a member payment approval or void; an attach re-derives the aggregation but never moves the status, so a group taking on an already-paid-up member stays `OPEN` — `routes/claims.py:306-309` vs `514`/`541`, `services/ledger.py:331-339`
- §3.8 — insert — ambiguity — `excluded_panel_firm_ids`: empty array accepted, duplicates permitted, explicit `null` = omission, entries must resolve — `routes/defense.py:102,108,113-114`, `validate.py:183-191,247`
- §3.8 — insert — ambiguity — engagement bumps the assigned firm's `version` by 1 as well as its `open_matter_count` — `routes/defense.py:159`
- §3.8 — insert — ambiguity — a new invoice's `dispute_note`, `audited_by_user_id`, `void_reason` and `hold_reason` are all null — `routes/defense.py:267-278`
- §3.8 step 3 — insert — ambiguity — the block share is the one quotient carried at full precision (makes §2.6's new cross-reference true) — `calc.py:275-281`
- §3.8 — insert — ambiguity — dispute fields are individually optional and merge over stored values; the block-billing constraint is re-checked on the merge, after path resolution but before the counsel-ownership and own-status checks — `routes/defense.py:311-326`
- §3.9 — insert — ambiguity — drafting a payment has no claim-status precondition; `approved_by_user_id`/`void_reason` start null — `routes/claims.py:447-468`
- §3.9 — revise — mismatch — payment approval evaluates the `ERR_GROUP_LOCKED` gate before the four-eyes gate (PRD had SoD first) — `routes/claims.py:479-489`
- §3.9 — revise — mismatch — the third/fourth cascade hops fire only from an indemnity-payment approval; a defense-invoice approval that drives the remainder to 0 advances the posture to `EXHAUSTED` and closes/rejects nothing — `routes/claims.py:518-519` vs `routes/defense.py:366-371`
- §3.9 — insert — ambiguity — voiding a `PENDING_APPROVAL` payment touches no other row's `version`; a voided approved payment keeps its `approved_by_user_id` — `routes/claims.py:532-545`
- §2.8 item 9 — revise — mismatch — a group must be `OPEN` to accept a further member as well as for a payment approval, and group attachment added to the step-9 operation list — `routes/claims.py:293-295`, `484-486`

Hand-offs resolved: (1) §3.8 vs pass 2's new §2.6 sentence — verified consistent (`calc.py:275-281` divides at full precision and rounds once at the end); a five-word clause was added to step 3 so §2.6's "the third is described in §3.8" resolves. (2) `excluded_panel_firm_ids` latitude — impl confirmed and pinned in §3.8's engagement paragraph.

Cross-pass consistency read (§2.1, §2.6, §2.8, §3.2, §3.8): no contradictions between the three passes' inserts. §2.6's three-unrounded-quantities sentence resolves against §3.8 step 3; §2.8 item 3 (shape before path) agrees with the §3.6/§3.7 precedence pins; §2.8 items 9->10 agree with the §3.9 group-before-SoD reordering, and §2.8's "six situations" paragraph (SoD outranking the retention gate on invoice approval) is a different pair and remains correct per `routes/defense.py:345-357`; §3.2 contains nothing about claims or defense. One tension judged harmless and left alone: §2.1 says a `PanelCounsel` "may read any claim" while `GET /epli/claims` (the collection) does not admit that role — §2.1's sentence is scoped to reads the principal is authorized to perform and §4's role column is declared exhaustive, so the PRD still pins `ERR_UNAUTHORIZED` there (`routes/claims.py:17-18`).

### Orchestrator verification

`PRD_COMPLETED.md` is 480 lines / 118,121 bytes versus `PRD_FINALIZED.md` at 105,918 bytes — `cmp` reports DIFFERS and `diff` reports 43 hunks, so the scan demonstrably ran and no pass clobbered an earlier pass's work (a byte-identical PRD_COMPLETED.md would have meant the scan never happened). The file still ends at a real section boundary (last row of the §5 error table, `ERR_DUPLICATE_PANEL_FIRM_NAME | 409`) with all 29 headings intact — no truncation. All three passes were forbidden to read `SCAFFOLD*.yaml` and `worklog.md`.

Step 9 edited only `PRD_COMPLETED.md`; neither `implementation/` nor the test artifacts were touched by any of the three passes, so the clean 8-round sweep recorded in Step 7 (rounds 1-8 each 100/100, `results.1.json`..`results.8.json` retained under `workspace/implementation/`) remains the valid final evidence. No re-sweep was run, which also avoids ~40 minutes of contended CPU on a 32-pipeline host for a no-op verification.

Pipeline complete: Steps 1-9 all finished, `workspace/PRD_COMPLETED.md` written.
