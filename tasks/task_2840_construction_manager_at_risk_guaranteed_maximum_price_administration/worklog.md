# Worklog — task_2840_construction_manager_at_risk_guaranteed_maximum_price_administration

## Step 1: Create task directory — 2026-09-05T04:51:38.102Z

Created `tasks/task_2840_construction_manager_at_risk_guaranteed_maximum_price_administration/` and its `workspace/` subdirectory. Index 2840 was pre-assigned by the orchestrating command (no scan of ./tasks/ was performed, to avoid collision with the ~32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T06:17:00.000Z

All three scaffold artifacts are complete and lint-clean.

## Files

| Path | Lines |
|---|---|
| `.../SCAFFOLD.yaml` | 3385 |
| `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1813 |
| `.../SCAFFOLD_CORNER_DESIGN.yaml` | 4013 |

Top-level keys are correct: `SCAFFOLD.yaml` carries §1.0–§1.7 only (no design keys); each design file has exactly one top-level key.

## Domain designed

10 entities — `CmarProject`, `ProgressiveEstimate`, `GmpProposal`, `QualificationItem`, `WorkPackage`, `SelfPerformBid`, `Subcontract`, `ChangeEvent`, `ContingencyDraw`, `CostReport`.

15 state machines / 73 transitions, deliberately multi-axis: `CmarProject` runs four parallel axes (`gmp_status`, `contingency_posture`, `audit_status`, `closeout_status`), `WorkPackage` two (`procurement_status`, `transparency_status`), `Subcontract` two (`contract_status`, `bond_claim_status`).

Surface: 54 endpoints, 47 validations on one priority ladder, 43 error codes, 12 calculations, 5 roles (`ProgramAdmin`, `ConstructionManager`, `ProcurementOfficer`, `OwnerRepresentative`, `IndependentAuditor`), 2 segregation-of-duties rules, 3 OCC `concurrency_rules`.

## Counts

- §1.8: **9 rule_ids × 2 instances = 18** (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
- §1.9: **9 sections, 72 instances** — 58 with full `test_recipe`s plus 14 `excluded_because` stubs. Per section: entities 11, state_machines 15, calculations 12, validations 9, endpoints 6, errors 8, rbac 4, complexity_layers 6, consistency_model 1.
- Lint: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (989 calls scanned).

## Audits run

- All 43 error codes are asserted by at least one instance's `assert` clause (verified programmatically, not just mentioned in prose).
- Instance names unique across both design files; all 14 stub citations resolve to real §1.8 instance names.
- Payload keys ⊆ §1.5 inputs and roles ∈ §1.5 roles for every call, checked *without* the lint's negative-name exemption — 3 remaining violations, all intentional negatives (system-field input-ignored, computed-field input-ignored, the role-precedence ladder).
- Forbidden concurrency vocabulary: 0 hits in all three files.
- Field/enum tokens cross-checked against `SCAFFOLD.yaml`; residual unknowns are free-text trade divisions and deliberate invalid-enum values (`CD_75`, `NOT_AN_ACTION`).

## Two §1.5 reshapes made during the §1.9 audit

1. Added **validation priority 21** (`ERR_UNAUTHORIZED`, 403) enforcing action-level authority on the two role-shared endpoints — `transparency` DISCLOSED is ProcurementOfficer-only / AUDITED is IndependentAuditor-only; `bond-claim` FILE is CM-only / ACKNOWLEDGE·SETTLE·DENY are Owner-only. §1.7 declared this partition but no §1.4 row made it testable, so either holder could have done both halves. `ERR_UNAUTHORIZED`'s condition text was widened accordingly.
2. Corrected a computed literal: the second-BASE-proposal repricing asserts `gmp_amount == 1266913.92` (base 1120000.00 → provisional fee 44800.00 → insurance 11648.00 → binding fee 45265.92), replacing a wrong figure; re-derived with `Decimal`/ROUND_HALF_UP. Also fixed a `transparency` call that used the wrong role and an `action:` key instead of `target_status:` — the instance name matched the lint's negative-name exemption, so lint had not flagged it.

## Flag for the pipeline

`SCAFFOLD.yaml`'s `scenario:` block begins with the verbatim line `Generate task harder than expert level!` (line 2). This is the known difficulty-directive leak that reaches `PRD.md` through the scenario key — strip that one line after Step 2.

**Orchestrator post-step action (per known-issue guard):** the flagged difficulty-directive line was stripped from `SCAFFOLD.yaml`'s `scenario:` block (plus the now-blank line after it), taking the file from 3385 → 3383 lines. Verified with `grep -rn "harder than expert"` across all three artifacts: zero hits remain, and `yaml.safe_load` still parses `SCAFFOLD.yaml` with its 15 expected top-level keys. The directive therefore cannot reach the doc generator.

## Step 3: Copy shared files — 2026-09-05T06:19:30.374Z

Copied `INSTRUCTION.md` (1424 bytes) from the project root to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T06:36:00.000Z

PRD generation for task_2840 is complete and verified.

**Output:** `.../workspace/PRD.md`

**Final line count: 462 lines.** Last section heading: `## 5. Error Code Catalogue` (line 414). Tail is intact — the file ends on the last row of the two-column error table, `| ERR_CONTINGENCY_INSUFFICIENT | 422 |`, at a real section boundary, not mid-sentence.

**Section list**
- `# CMAR Guaranteed Maximum Price Administration API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control; 2.2 API Response Structure; 2.3 Pagination; 2.4 Resource Identity, Audit Fields and the Logical Clock; 2.5 Money, Ratios and Rounding Discipline; 2.6 The Guaranteed Maximum Price as a Closed Envelope; 2.7 Contingency Posture: A Derived Project-Wide Gate; 2.8 Segregation of Duties on the Operator Identifier; 2.9 Referential Integrity and Path Resolution Order; 2.10 Optimistic Concurrency on Parent Creation; 2.11 Order of Precedence Among Validations
- `## 3. Business Logic & Workflows` — 3.1 Preconstruction: Progressive Estimating and Milestone Reconciliation; 3.2 Establishing the Guaranteed Maximum Price; 3.3 The Qualification Log; 3.4 Trade Buyout: Packages, Sealed Bids and Open-Book Disclosure; 3.5 Subcontracts, Default, and the Surety; 3.6 Change Events and the Cost-Responsibility Fork; 3.7 The Contingency Ledger: Draws, Approval, Posting and Compensation; 3.8 Monthly Cost Reporting, Per-Line Rounding and Buyout Savings; 3.9 Audit Rights, Shared Savings and Settlement
- `## 4. Endpoint Definitions`
- `## 5. Error Code Catalogue`

**Hard contract verification**
- **Contract 1 — Field-Name Coverage: PASS.** Programmatic diff of all 171 scaffold identifiers (every `entities[].fields[].name`, every endpoint `input` token, both `occ_field` names) against backticked tokens in the PRD: 0 missing. Two calculation *variant* labels (`TRADE_LEVEL`, `PROJECT_NET`) surfaced in the first pass; both were added to §3.8 in backticks.
- **Contract 2 — Rule Coverage: PASS.** All 43 error IDs are discussed in §1–§4 prose, not merely listed in §5. All 73 state-machine transitions across 15 state fields are covered (arrow-notation check flagged 12 as "??"; each was manually confirmed present in prose form — e.g. the three `→ SUPERSEDED` estimate transitions, the three proposal ones, `OPENED → NOT_AWARDED`, `AWARDED → CLOSED`, the closeout self-loop and the two `→ FINAL_COMPUTED` entries). All 12 calculations are documented, including both dual variants of `buyout_savings_tracking` and `shared_savings_split`, the 7-term envelope identity, and per-line-before-summation rounding. All global constants appear (0.0500, 50,000.00, 0.1000, 1.15, 72 hours, 25% fee cap, `2026-08-01T00:00:00Z`, the full `MILESTONE_RANK` ladder).
- **Contract 3 — §3 Path Purity: PASS.** Zero backticked tokens in §3 start with `/`, contain `/`, or are a bare/combined HTTP method; zero raw path strings and zero bare HTTP method words appear in §3 prose. Paths are confined to the §4 table.

**Other structural checks:** §2.2 is byte-identical to `skills/prd-bench-doc-generator/section-2.2-response-structure.md` (only difference is the trailing blank separator line before §2.3). §4 is a 4-column table containing exactly 54 rows matching all 54 scaffold endpoints — set-diff both directions is empty. §5 is a 2-column table with all 43 error IDs and no trigger-condition column.

**Constraints honoured:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped or referenced; no sibling `task_*/` directory was read; no `pkill` was used; the file was built entirely with chunked `cat >> PRD.md <<'EOF'` appends (9 chunks) plus one targeted in-place edit for the two variant labels.

**Scaffold ambiguities resolved** (one unambiguous reading each, applied consistently): the `proposed_gmp_rollup` status set was taken as the three non-terminal statuses per the calculations table; work-package solicitation was gated on the transition precondition (`GMP_UNDER_REVIEW` or `EXECUTED`); `REPROCUREMENT → SOLICITING` was documented from validation 64 plus the solicit side effect; a `RECONCILE` against a non-`ALLOWANCE` item resolves to `ERR_ALLOWANCE_UNITS_EXCEEDED` via zero `remaining_units`; the two bond ceiling checks (`claim_amount ≤ bond_amount`, `recovered_amount ≤ bond_claim_amount`) are stated as requirements without inventing error IDs, since the scaffold nominates none.

**Orchestrator truncation-guard verification (per known-issue guard):** independently ran `wc -l` (462), listed all 27 headings, and read `tail -12`. The file terminates on a complete markdown table row of §5's error catalogue — a real section boundary, not a mid-sentence cut. All five top-level sections (§1–§5) are present in order. Also re-grepped PRD.md for the difficulty directive: no leak. No regeneration needed.

## Step 6: Generate implementation — 2026-09-05T07:10:00.000Z

(Steps 5 and 6 were launched concurrently in a single assistant message, per the skill's physical-isolation requirement — the impl generator could not see `test_suite/` because it did not exist at its spawn time. Step 6 returned first; Step 5's entry follows below.)

All three remaining modules are written and the implementation is complete and verified.

## Modules (25 files, 3,886 lines)

Core (`workspace/implementation/`): `app.py` 76, `money.py` 45, `errors.py` 65, `clock.py` 37, `response.py` 66, `db.py` 64, `middleware.py` 66, `validation.py` 268, `lookups.py` 98, `serializers.py` 280, `guards.py` 47, plus `requirements.txt` and `start.sh` (guarded `pip install`, `exec python3 app.py`, honours `PORT`, binds `0.0.0.0`).

Services: `services/derive.py` 143, `services/pricing.py` 65.

Routes: `projects.py` 292, `estimates.py` 253, `proposals.py` 295, `qualification_items.py` 194, `work_packages.py` 234, `bids.py` 171, `subcontracts.py` 410, `change_events.py` 318, `draws.py` 177, `cost_reports.py` 222.

Written this session: `routes/draws.py` (5 draw endpoints), `routes/cost_reports.py` (6 cost-report endpoints), `app.py` (blueprint registration, `ApiError`/404/405/HTTPException/catch-all handlers emitting the PRD envelope, no seeding).

## Verification
- `ast.parse` over all 25 modules: clean.
- Endpoint diff against SCAFFOLD.yaml by (method, path): **54 spec / 54 implemented, 0 missing, 0 extra**.
- In-memory only; nothing written to disk beyond `__pycache__`.

## Smoke-test evidence (booted with `bash start.sh`, PORT=18240 then 18241; killed by exact listener PID found via `ss`, no pattern kills)
- Envelope: success `{meta{api_request_id,api_request_timestamp[,limit,offset,total_count,has_more]}, response_type, data}`; errors carry only the two meta fields plus `data{error_id,message}`.
- Auth/shape: no headers → 401 `ERR_UNAUTHENTICATED`; `X-User-Role: Wizard` → 401; CM on `POST /projects` → 403; `limit=0` → 400; malformed JSON → 400; `cm_fee_pct 0.2` → 400; unknown route → 404 `ERR_RESOURCE_NOT_FOUND`; `DELETE /projects` → 405.
- Happy path: project → estimate (submit/reconcile) → BASE proposal → EXECUTE. GMP build-up reproduced exactly: fee 420,000 → insurance 109,200 → cm fee 424,368 → **gmp 11,533,568**.
- Cost reports: pinned worked example reproduced exactly — three lines → `reported 1411.07`, `undisputed 1318.17`, `disputed 92.90`; overlapping period → 409 `ERR_COST_PERIOD_OVERLAP`; adjacent period → 201; DISPUTE→RECONCILE ladder; re-reconcile → 409 `ERR_COST_REPORT_STATE_INVALID`.
- Contingency: 95,000 draw of a 100,000 pot → post before approval → 422 `ERR_OWNER_APPROVAL_REQUIRED`; approve → post → posture `CONSTRAINED` and the OPEN report auto-held with `CONSTRUCTION_CONTINGENCY_CONSTRAINED`; release while constrained → 409 `ERR_POSTURE_NOT_RECOVERED`; void restores pot to 100,000 and posture to OPEN while the report **stays held**; manual release then succeeds; second void → 409 `ERR_DRAW_STATE_INVALID`.
- Procurement/termination: breakdown mismatch → 422; open before disclosure → 422; officer attempting `AUDITED` → 403; open before close → 409 `ERR_SOLICITATION_STILL_OPEN`; award → buyout 50,000; stale wp version → 412; terminate-for-default → replacement 230,000, premium 30,000 posted, package → REPROCUREMENT with `awarded_amount 280,000`, `reserve 230,000`, buyout re-derived to 20,000; bond FILE (CM) / ACKNOWLEDGE by CM → 403 / owner ACKNOWLEDGE + SETTLE 150,000 → credit capped at the 30,000 draw.
- Closeout: `PRE_AUDIT_PROVISIONAL` before any RECONCILED report → 422 `ERR_NO_RECONCILED_COST_REPORT`; pool 870,000 with cm share capped at 10,104; `POST_AUDIT_FINAL` before CLOSE → 422 `ERR_AUDIT_NOT_CLOSED`; after audit CLOSE with a −5,000 adjustment → pool 805,000 / cm 10,104 / owner 794,896; execute → `SETTLEMENT_EXECUTED` + posture FROZEN; post-settlement cost report → 409 `ERR_CLOSEOUT_ALREADY_SETTLED`.
- Allowances: unit rate 150.0000; 201 of 200 units → 422 `ERR_ALLOWANCE_UNITS_EXCEEDED`; unauthorized over-rate → 422 `ERR_ALLOWANCE_OVERRUN_UNAUTHORIZED`; REVERSE then REVERSE again → 422 `ERR_ALLOWANCE_REVERSAL_INVALID` (seq not decremented). SCOPE_CHANGE classification minted an AMENDMENT, bumped `proposed_gmp_amount` to 1,325,816 with `pending_amendment_count 1`, and flipped the RECONCILED estimate to `reconciliation_stale: true`; amendment EXECUTE folded the delta into `gmp_amount`.

Two judgment calls worth flagging for the test-fix step: `ERR_CLOSEOUT_ALREADY_SETTLED` is checked before the gmp gate on the four operations PRD §2.11's note enumerates (otherwise it is unreachable, since settlement also drives `gmp_status` to CLOSED), and `reconcile` preserves an existing `reconciliation_note` when the payload omits it.

## Step 5: Generate unit tests — 2026-09-05T08:50:00.000Z

Generation complete and verified. Final state:

## Files written

**`.../test_helpers/`** (9 modules, 2,519 lines)

| file | lines |
|---|---|
| `__init__.py` (barrel) | 115 |
| `api_client.py` | 331 |
| `api_errors.py` | 110 |
| `assertions.py` | 365 |
| `constants.py` | 166 |
| `factories.py` | 578 |
| `fixtures.py` | 757 |
| `test_users.py` | 68 |
| `types.py` | 29 |

**`.../test_suite/`** (17 files, 8,154 lines, **101 tests**)

Queue A (difficulty): `conftest.py` 23 · `test_01_gmp_pricing_and_estimating.py` 263/5 · `test_02_shared_savings_and_closeout.py` 357/5 · `test_03_buyout_savings_and_award.py` 475/7 · `test_04_cost_reporting_periods.py` 333/5 · `test_05_change_event_classification.py` 523/5 · `test_06_subcontract_default_and_surety.py` 607/6 · `test_07_contingency_draws.py` 417/7 · `test_08_allowance_ledger.py` 253/3 — **43 tests**

Queue B (corner): `test_09_project_registry_and_reads.py` 579/11 (entities) · `test_10_lifecycle_state_machines.py` 800/11 (state_machines) · `test_11_calculation_variants.py` 633/7 (calculations) · `test_12_validation_gates.py` 527/7 (validations) · `test_13_endpoint_behaviour.py` 495/5 (endpoints) · `test_14_error_codes.py` 771/8 (errors) · `test_15_role_access.py` 523/4 (rbac) · `test_16_concurrency_and_layering.py` 575/5 (complexity_layers ×4 + consistency_model ×1) — **58 tests**

## Coverage

- **Queue A: 18/18 difficulty instances, 43 tests** — every instance has ≥2 tests (verified: 43 tags, 18 unique).
- **Queue B: 58/58 non-stub corner instances, 58 tests** — exactly one test per instance (58 tags, 58 unique). The 14 `excluded_because:` stubs were correctly **not** translated.
- **Instances SKIPPED by the PRD-first filter: none.** Every non-stub instance had verbatim PRD coverage and a uniquely-derivable outcome. No `pytest.mark.skip`/`xfail` anywhere, no placeholders.

## Verification passes (all green)

- `pytest --collect-only`: **101 tests collected, 0 errors**.
- `pyflakes` over all 26 files: **clean** (fixed the last defect — `to_decimal` was missing from test_16's barrel import).
- PRD-citation pass: **424 `PRD:` citations, 0 non-verbatim** (each checked as a literal substring of `workspace/PRD.md`).
- Design-tag pass: **101 tags, exactly one per test**, all resolving to real non-stub instances; zero pointing at stubs or missing names.
- No occurrence of the word "scaffold" in any emitted file.
- Output location correct: both dirs at the task root; **no stray copies under `workspace/`**.

## Recipe adaptations (PRD wins over the design recipe in each case)

1. **Subcontract stale-version corner**: recipe captured the package token before filing a bid but asserted `wpv2 == wpv1 + 1`; §3.4 makes a bid bump the version too. Stale token now captured after the bid, preserving the recipe's "increment contributed by the award" claim.
2. **Cost-report recompute corner**: recipe asserted `version == 3` after three appends; §2.4 starts version at 1 and bumps per mutation, so 4 is asserted.
3. **RBAC shared-endpoint partition**: recipe disclosed a `BUDGETED` package with no bids; §3.4 requires `bid_count` ≥ 1, so the package is solicited and a self-perform bid filed first.
4. **Endpoint listing corner**: dropped the recipe's `?milestone_code=SD` filter (the §4 row names `milestone`, the field is `milestone_code` — the parameter name isn't uniquely derivable); isolated by `status=RECONCILED` instead.
5. **Bond-claim corners (two)**: recipes file a claim on an ACTIVE / `DEFAULT_NOTICED` subcontract; the PRD requires `TERMINATED_FOR_DEFAULT`, so the premature FILE is asserted as 409 `ERR_BOND_CLAIM_STATE_INVALID`. Claim amount reduced to 240,000.00 (a claim may not exceed `bond_amount`); all downstream published figures unchanged.
6. **Bid-opener SoD corner**: DISCLOSED set after the bid exists, not before.
7. **Status-code corrections** where recipes disagreed with §4/§5: `ERR_SOLICITATION_STILL_OPEN` 409 (recipe 422), `ERR_INVALID_REQUEST` 400 (recipe 422), `ERR_AUDIT_NOT_CLOSED` 422 (recipe 409). `POST /cost-reports/{id}/lines` pinned to 201 per SCAFFOLD's declared code (test_13 was corrected from 200, which would have contradicted test_09).
8. **Open-book breakdown**: the design yamls attach a breakdown to `THIRD_PARTY` bids, which the PRD only requires for self-perform; null-breakdown third-party bids used throughout.
9. **User-id mapping**: `as_user_id: "owner-rep-1"` resolved to `user_id_of("owner_rep")` (= `owner-1`).

**Orchestrator layout verification (per known-issue guard):** confirmed independently that `test_helpers/` and `test_suite/` sit at the task root, that `find workspace -maxdepth 2` shows no stray copies of either directory under `workspace/`, and that 17 files in `test_suite/` carry 101 `Design:` tags in total. No relocation was needed.

## Step 7: Run tests and iterate — 2026-09-05T08:56:00.000Z

All clean. Final state verified: 101 tests all present (zero deletions), no skip/xfail, storage in-memory only, worklog untouched.

## Summary

**Iterations run:** 3 full 8-round parallel sweeps (baseline 94/101 → 100/101 → **101/101 in all 8 rounds**).

Failures were perfectly deterministic across all 8 rounds in every sweep — no flakiness or load-induced noise appeared at any point.

**Tests deleted:** none. Every failing test traced to a rule stated verbatim in PRD.

**Fixes applied to `test_suite/`** (all STEP 2 test-vs-PRD consistency bugs):

- `test_14_error_codes.py` — **five call sites had `payload` and `headers` swapped.** `submit_change_event`, `post_draw`, `open_bid`, `submit_gmp_proposal` and `release_hold` take `(id, headers, payload=None)`, so the payload dict was arriving as the header dict and the server correctly answered `ERR_UNAUTHENTICATED`. This single mistake accounted for 4 of the 7 original failures. The rest of the suite already used the correct order.
- `test_14_error_codes.py::test_a_bid_from_the_neighbouring_package_cannot_be_laundered_into_this_one` — the setup named an `OPENED` (not `AWARDED`) cross-package bid, so PRD §2.11's bid-status gate (level 8) legitimately pre-empted the sibling rule (level 11) with `ERR_BID_STATE_INVALID`. Setup now awards the neighbouring package first so the bid reaches `AWARDED`, isolating the `ERR_WORK_PACKAGE_PROJECT_MISMATCH` rule the test cites. Implementation was correct.
- `test_03_buyout_savings_and_award.py::_self_perform_bid_awaiting_disclosure` — the helper returned a package snapshot read *before* the bid was submitted, then asserted `bid_count == 1` on it. Now re-reads the package after the bid bumps its `bid_count`/`version`.
- `test_13_endpoint_behaviour.py::test_a_cost_line_points_at_a_package_and_an_allowance_without_spending_either` — removed the assertion that the appended line echoes `qualification_item_id` (STEP 1c partial-coverage split; the surrounding covered assertions were kept). PRD's sentence enumerating what the line object exposes — "`line_seq` … together with `work_package_id`, `quantity`, `unit_rate`, `markup_pct`, the computed `line_amount` and `disputed`" — omits that field, so a faithful reader may legitimately keep it out of the serializer (**computed-field/response-field silence**). The link is still proven by the named allowance being left unspent.

**Fixes applied to `implementation/`:**

- `routes/cost_reports.py::append_line` — an unresolvable `work_package_id` on a cost line returned `ERR_WORK_PACKAGE_NOT_FOUND`; PRD §2.9 explicitly lists "or a cost line's `work_package_id`" among the body identifiers yielding `ERR_RESOURCE_NOT_FOUND`, carving it out of the general work-package rule. Switched to the generic resource lookup. (This was a genuine defect that had been masked behind the earlier assertion in the same test.)

**No changes to `test_helpers/`** — the fixtures, factories, header builders and assertion library were already faithful to PRD (money as JSON numbers, full ISO-8601 instants, tolerant timestamp parsing, correct four-step build-up constants).

**Orchestrator verification of the sweep artifacts (per known-issue guard):** independently parsed all eight `workspace/implementation/results.{1..8}.json` (all written 08:54, ~33.7 KB each): every round reports `passed 101 / failed 0 / errors 0 / total 101`. Also re-confirmed 101 `def test_` functions across `test_suite/` and zero `pytest.mark.skip` / `pytest.mark.xfail` occurrences in either test directory. Step 7's green claim is therefore backed by real artifacts, not asserted. Since Step 7 applied one `implementation/` fix plus four `test_suite/` fixes, Step 8's skip condition does not apply — Step 8 will run.

## Step 8: Finalize PRD — 2026-09-05T09:01:00.000Z

Edits complete. No implementation or test files were touched.

## PRD.md vs PRD_FINALIZED.md
- 462 → 464 lines (+2 lines, **+0.43%**); 4 lines revised in place, 2 lines inserted (one new paragraph + blank).

## Changes
- **§2.11 item 8** — revise — added a parenthetical pointing `ERR_CLOSEOUT_ALREADY_SETTLED` at the ordering carve-out now stated in the section's closing note — `routes/projects.py:214-216`, `routes/cost_reports.py:51-52`, `routes/change_events.py:250-252`
- **§2.11 closing note** — insert — new paragraph pinning that on operations carrying both checks the settled-closeout rule is evaluated *ahead of* the project's `gmp_status` gate (settlement execution, opening a cost report), that on classifying a change event it also precedes the change-event status gate, and that appending a cost line has no `gmp_status` gate and still applies its report status gate first — `routes/projects.py:214-216`, `routes/cost_reports.py:51-52`, `routes/cost_reports.py:105-110`, `routes/change_events.py:250-252`
- **§3.1 (estimate reconcile)** — revise — omitted/null `reconciliation_note` leaves the existing note in place rather than clearing it — `routes/estimates.py:207-208`
- **§3.8 (cost line object)** — revise — the appended line object exposes exactly seven fields and no others; `cost_code` and `qualification_item_id` are recorded but not echoed back — `implementation/serializers.py:197-205`, `routes/cost_reports.py:128-138`
- **§3.8 (cost report reconcile)** — revise — omitted/null `reconciliation_note` leaves the existing note in place — `routes/cost_reports.py:177-178`

## Per-edit pre-edit search log

**Edit 1 — §2.11 item 8 parenthetical + closing-note paragraph**
- (a) Subject: the internal ordering of step-8 state preconditions, specifically `ERR_CLOSEOUT_ALREADY_SETTLED` vs the `gmp_status` gate and per-entity status gates.
- (b) Enumerated: `guards.py` (all five guard helpers) and every call site via grep for `require_not_settled|require_gmp_executed|require_gmp_not_executed|require_not_frozen|require_posture_recovered` — `routes/draws.py:48,78-79,126`; `routes/change_events.py:120,250-251`; `routes/cost_reports.py:51-52,110,196`; `routes/projects.py:160,215-216`; `routes/subcontracts.py:92,223`; `routes/proposals.py:73,227-229`; `routes/work_packages.py:157`. Read `routes/projects.py` (shared-savings), `routes/change_events.py` (classify), `routes/cost_reports.py` (create + append), `routes/draws.py` (post/void) in full.
- (c) Adjustment made: my first draft called this "the one exception" to step 8's internal order. The search found `post_draw` (`draws.py:72→78→79`) checks the draw status gate, then `ERR_CONTINGENCY_FROZEN`, then the `gmp_status` gate — a second deviation that is **not** in Step 7 scope. I dropped the uniqueness claim and scoped the paragraph strictly to `ERR_CLOSEOUT_ALREADY_SETTLED`. I also found `append_line` checks the report status gate *before* the closeout rule (matching the unmodified step-8 order) and has no `gmp_status` gate at all, so I added the explicit carve-out sentence for it rather than letting the paragraph read as covering all four enumerated operations uniformly. Also confirmed `void_draw` carries no closeout check whatsoever, so the paragraph's "operations that do carry it" phrasing stays true.

**Edit 2 — §3.1 estimate reconcile note preservation**
- (a) Subject: what happens to an already-stored optional note when the payload omits it, on `/estimates/{id}/reconcile`.
- (b) Enumerated: `routes/estimates.py` `reconcile_estimate:198-208`, `submit_estimate:156,174-187` (same preserve-on-omit for `justification_note`), `create_estimate:84-86,127`; `validation.py` `get_str:62-74` and `present:28-29` (explicit JSON `null` is treated as absent, and `min_len=0` means an explicitly supplied empty string *does* overwrite).
- (c) Adjustment made: worded the trigger as "omits … altogether, or sends it as null" rather than "supplies no note", because `present()` collapses null with absent while an explicit `""` overwrites. Kept the scope to the reconcile decision so the sentence makes no claim about `justification_note` on submit.

**Edit 3 — §3.8 cost line object field set**
- (a) Subject: the field set of the embedded cost-report line object.
- (b) Enumerated: `serializers.py:197-205` (`LINE_FIELDS`) and `serializers.py:277-280` (`cost_report`), plus every render path via grep for `LINE_FIELDS|"lines"|cost_report(` — `routes/cost_reports.py:78,142,181,200,219,226` all funnel through `serializers.cost_report`, so there is exactly one line projection in the system; `routes/cost_reports.py:128-138` (line construction, which does store `cost_code` and `qualification_item_id`); `services/derive.py:126-140` (`recompute_report_totals`, reads only `line_amount`/`disputed`); `test_suite/test_13_endpoint_behaviour.py:335-386` for the Step 7 site.
- (c) Adjustment made: rather than saying the two fields are "not stored", I wrote that they are "recorded against the line but are not echoed back", which matches `routes/cost_reports.py:128-138`. Added the trailing clause about the named allowance ledger being left untouched so the exhaustive-seven-field claim does not read as denying the link exists (`qualification_item_id` is still validated for cross-project at `routes/cost_reports.py:117-123`).

**Edit 4 — §3.8 cost report reconcile note preservation**
- (a) Subject: `reconciliation_note` write semantics on `/cost-reports/{id}/reconcile`.
- (b) Enumerated: `routes/cost_reports.py:150` (parse) and `177-178` (conditional write); `create_cost_report:75` (initialised to `None`); `release_hold:188` (`release_note` parsed but never persisted, so no note field is touched there); comparable optional-note paths confirmed for consistency — `routes/change_events.py:172-173` (`review_note`), `routes/proposals.py:231-232` (`owner_decision_note`), `routes/draws.py:45,68` (approval/post notes not persisted), `routes/draws.py:118,131` (`void_reason` required, always written).
- (c) Adjustment made: same null/absent-vs-empty-string distinction as Edit 2. Deliberately scoped the clause to `reconciliation_note` on this endpoint and did not generalise to "every optional note field", even though the whole implementation follows the same pattern — generalising would have reached `void_reason` (mandatory, always written) and the several notes that are parsed but never persisted at all.

**Orchestrator note:** verified `PRD_FINALIZED.md` exists and is NOT byte-identical to `PRD.md` (462 → 464 lines), so the finalizer genuinely ran. Step 9 will start from `PRD_FINALIZED.md`, and — per the known partial-scan failure mode — will be run as three sequential module-partitioned passes over one shared `PRD_COMPLETED.md` rather than as a single monolithic scan, with pass 1 owning the `cp` and passes 2–3 forbidden from re-copying.

## Step 9: Complete PRD — 2026-09-05T09:38:00.000Z

Per the known partial-scan failure mode (a monolithic scan degenerates into a no-op that leaves `PRD_COMPLETED.md` byte-identical to its source), Step 9 was run as **three sequential module-partitioned passes** over one shared `PRD_COMPLETED.md`. Pass 1 owned the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from re-copying and edited in place. Each pass was handed the silences its predecessor spotted outside its own partition. Totals across the three passes: **97 changes — 71 ambiguity-pins, 26 mismatch-revisions** — taking the PRD from 464 → 468 lines and 100,032 → 123,550 chars (**+23,518 chars, +23.5%**).

### Pass 1 of 3 — cross-cutting core + `projects.py` / `estimates.py` / `proposals.py` / `qualification_items.py`

Ran `cp PRD_FINALIZED.md PRD_COMPLETED.md` first (owns the copy). Source 464 lines / 100,032 chars → 468 lines / 111,515 chars (+11,424 chars, +4 lines: two new paragraphs inside existing §2.3 and §2.9; no new sections, all 54 endpoint rows intact). **31 ambiguity-pins, 10 mismatch-revisions** over 33 Edit calls.

Cross-cutting core: §2.1 blank/whitespace headers → `ERR_UNAUTHENTICATED`, values trimmed before role match and operator comparison (`middleware.py:29-37`) · §2.2 `api_request_id` = `req_` + 20 chars `A-Z0-9` (`response.py:10,19`) · §2.2 `api_request_timestamp` from real wall-clock, not the logical clock (`response.py:25`) · §2.3 out-of-band `limit`/negative `offset`/non-integer → 400, empty string → default, past-the-end offset → empty array (`validation.py:229-250`) · §2.3 ordering ties broken by insertion order (`db.py:60`) · §2.3 **new paragraph** on filter semantics — empty ignored, bad enum → 400, identifier filters opaque, unknown params ignored, conjunctive, filter-before-paginate (`validation.py:253-268`) · §2.3 `has_more` = `offset + len(page) < total_count`, echoed `limit`/`offset` are effective values (`response.py:50-57`) · §2.4 clock may run backwards, response `data` is `{}`, `created_at`/`updated_at` real wall-clock with only six named business instants on the logical clock (`clock.py:22`, `db.py:39,54`, `routes/projects.py:44-50`) · §2.5 numerics accepted as JSON number *or* decimal string but never booleans, emitted as plain JSON numbers with trailing zeros lost (`validation.py:39-59`, `money.py:41-45`) · §2.7 hold cascade fires only on `OPEN→CONSTRAINED`, never on a re-derivation already at `CONSTRAINED` (`services/derive.py:37-39`) · §2.9 **new paragraph** — route resolution precedes auth, unknown path → `ERR_RESOURCE_NOT_FOUND` 404, wrong method → HTTP 405 carrying `ERR_INVALID_REQUEST` (the sole non-400 use of that id), trailing slash tolerated (`app.py:40,48-56`) · §2.11 step 4 **mismatch** — empty/absent body = `{}`, non-JSON/non-object → 400, explicit null == absent, tolerant datetime→UTC coercion, and the "money non-negative / ≤2dp" universal carved out for `adjustment_amount` and a cost line's `quantity` (`validation.py:13-29,183-219`) · §2.11 step 4 which 5 free-text notes persist vs which 14 are shape-checked then discarded.

§3.1: filing an estimate has no `gmp_status` precondition (`estimates.py:71-99`) · variance tie-break falls through to insertion order (`:61-63`) · submit overwrites the three variance fields, excludes its own row from the basis set, retains stored `justification_note` on omit/null, gates on whichever note is in force (`:167-187`) · `RETURN` leaves `reconciliation_stale` as-is; neither decision touches the project (`:209-215`).

§3.2: **mismatch** — `cover_note` not persisted, base-submit project write is conditional (already `GMP_UNDER_REVIEW` → neither `gmp_status` nor `version` moves), no `gmp_status` precondition on submit, amendment-submit failure is `ERR_CHANGE_EVENT_STATE_INVALID` (`proposals.py:137,147-170`) · `owner_decision_note` retained on omit/null (`:231-232`) · **mismatch** — base `RETURN` writes the project only at `GMP_UNDER_REVIEW`; amendment `RETURN` re-runs the rollup but never touches the project (`:242-250`) · `REJECT` on a base proposal → `ERR_PROPOSAL_STATE_INVALID` (`:220-224`) · **mismatch** — base `EXECUTE` gate is one-sided (`not EXECUTED/CLOSED`) (`:225-229`, `guards.py:13-18`) · **mismatch** — rollup triggers are exactly five (amendment mint/return/reject/execute + base execute); amendments never superseded; base create/return do not roll up (`derive.py:90`).

§3.3: adding an item bumps no parent `version` (`qualification_items.py:89-90`) · null counts as absent for the ALLOWANCE-only rule (`:53-57`) · non-allowance rows carry the three allowance fields null and short-circuit to `OPEN` (`:58-62,93-96`) · the ledger has no parent-proposal status gate and writes nothing upward (`:112-127`) · **mismatch** — reversal precondition restated as "never booked" (the blanket "a non-allowance item cannot be reversed" was false after a zero-unit booking) (`:150-156`) · the booking stack is internal, exposed through no response field.

§3.6 (derive cascade): only rows whose flag was still false are rewritten, each bumping its own `version` (`derive.py:107-120`).

§3.9: audit-request bumps project `version`, status gate precedes the reconciled-report check (`projects.py:161-172`) · on `CLOSE`, `adjustment_amount` is ignored and not even shape-validated, no `gmp_status` gate, `POST_ADJUSTMENT` leaves `audit_status` alone (`:180-199`) · `basis` and `execute` both mandatory, `execute` ignored under `PRE_AUDIT_PROVISIONAL` (`:209-213`) · provisional at `FINAL_COMPUTED` refreshes figures without moving the axis; provisional on a settled project → `ERR_GMP_NOT_EXECUTED` (`:213-216,270-271`) · final-with-`execute`-false also re-runnable from `FINAL_COMPUTED` (`:276-277`) · settlement from `NOT_STARTED`/`PROVISIONAL_COMPUTED` also yields `ERR_CLOSEOUT_ALREADY_SETTLED`, posture written directly to `FROZEN` without the §2.7 cascade, each closed package bumps `version` (`:239-244,279-289`).

§4: `/projects` has no `name`/`owner_org` filter · **mismatch** ×4 — `/estimates` filter list completed (`milestone_code` + `milestone` alias, `prior_estimate_id`, `variance_basis_estimate_id`, `superseded_by_estimate_id`), `POST /gmp-proposals` is base-only with `proposal_type` not a payload field, `/gmp-proposals` filters completed, `/qualification-items` filterable by `status`.

### Pass 2 of 3 — `work_packages.py` / `bids.py` / `subcontracts.py`

No `cp` run; 22 targeted in-paragraph Edit calls, 468 → 468 lines. **27 ambiguity-pins, 8 mismatch-revisions.** Pass 1's 41 edits left intact.

§3.4: `self_perform_intent` is advisory and gates nothing — a `CM_SELF_PERFORM` bid may be filed against a package whose flag is false (`work_packages.py:51-53`, `bids.py:59`) · package create carries no `gmp_status`/posture/closeout gate and does not move project `version` (`:44-71`) · reopening a `REPROCUREMENT` market leaves `awarded_bid_id`/`awarded_amount`/`replacement_reserve_amount` untouched and does not recompute buyout savings even though the package leaves the roll-up set (`:97-100`) · exactly the five named breakdown keys are read, extras silently ignored, stored breakdown rebuilt from the five (`bids.py:35-45`) · bid create writes only the package row, `SOLICITING` is the whole gate (`:72-104`) · `open_book_cost_breakdown` key always present, null for `THIRD_PARTY` in every status (`serializers.py:249-262`) · a package with no bids draws `ERR_PACKAGE_STATE_INVALID` 409, not a shape error (`work_packages.py:126-130`) · `AUDITED` imposes no bid-count requirement (`:131-136`) · neither transparency step carries a project gate or writes any row but the package · bid open evaluates its four guards in §2.11 order, not narration order (`bids.py:116-143`) · **mismatch** — award applies no clock check, so the requirement that the clock have reached `solicitation_closes_at` was deleted and `ERR_SOLICITATION_STILL_OPEN` is unreachable there (`work_packages.py:147-197`) · the `gmp_status` gate precedes the package and bid status gates (`:157-168`) · every bid the award rewrote increments its own `version` (`:182-192`) · an earlier cycle's winner keeps `AWARDED`, so a package can show more than one `AWARDED` bid (`:184-192`).

§3.5: a `bond_amount` supplied with `bond_required` false is shape-checked then discarded and stored 0.00, explicitly contrasted with §3.3's must-be-absent allowance fields (`subcontracts.py:77-79`) · no `procurement_status` gate on the package — the bid's `AWARDED` status is the only buyout evidence — and one bid may back more than one subcontract (`:81-103`) · create recomputes both buyout figures but does not write the project row, so project `version`/`updated_at` do not move (`:140-142`) · `payment_amount` need only be ≥ 0.00 and is uncapped, so `paid_to_date` may pass `contract_amount` and `unpaid_committed_amount` may go negative (`:150,158-161`) · progress payment writes only the subcontract row, no `gmp_status` gate · a `COMPLETE` with short `paid_to_date` draws `ERR_SUBCONTRACT_STATE_INVALID`, not a fiscal identifier (`:248-252`) · `NOTICE_DEFAULT`/`CURE`/`COMPLETE` carry no `gmp_status` gate and write no row but the subcontract (`:222-254`) · cascade step 2 leaves `procurement_status` alone if the package is not at `AWARDED` while the rest of step 2 still applies (`:175-178`) · the cascade draw is minted with `approved_by_user_id` null and never passes through `REQUESTED`/`OWNER_APPROVED` (`:182-195`) · no §3.7 posting gate applies, so a premium exceeding the pot drives `construction_contingency_remaining` negative rather than raising `ERR_CONTINGENCY_INSUFFICIENT` (`:198-203`) · **mismatch** — cascade step 5's hold fires only on an actual `OPEN → CONSTRAINED` transition (`derive.py:37`) · `claim_amount` must be > 0 at 2dp (`:300`) · a claim over the bond face is rejected with `ERR_BOND_CLAIM_STATE_INVALID` 409, not as a shape error (`:330-335`) · the bond-claim endpoint carries no `gmp_status`/closeout/posture gate — it works on a closed, frozen project — and `FILE`/`ACKNOWLEDGE`/`DENY` write only the subcontract row (`:287-377`) · **mismatch** — `recovered_amount` is never rejected for exceeding `bond_claim_amount`; it is clamped (`:302,360`) · the project row is written and its `version` moves even when the credit is 0.00 (`:364-376`).

§4 **mismatch** ×5: `POST /work-packages/{id}/transparency` applies to any package with `bid_count` ≥ 1 of either `bidder_type` · `GET /work-packages` filters are `project_id`/`awarded_bid_id`/`procurement_status`/`transparency_status`/`trade_division` · `GET /self-perform-bids` also filters `bidder_type` · `GET /subcontracts` also filters `awarded_bid_id` and `bond_claim_status` · `POST /subcontracts` is "from an awarded bid", package `procurement_status` ungated.

Pass-1 hand-offs: all four confirmed against the impl and pinned (hold cascade transition-only; project `version` static on subcontract create — deliberately *not* claiming the recompute is a value no-op, since `solicit` can move a package out of the roll-up set without recomputing; `bond_amount` dropped when not required; breakdown extras ignored).

### Pass 3 of 3 — `change_events.py` / `draws.py` / `cost_reports.py`

No `cp` run; 18 targeted Edit calls, 21 distinct changes, 468 → 468 lines. **13 ambiguity-pins, 8 mismatch-revisions.**

§3.6: logging carries no project-level gate (first gate arrives at submit) and does not move project `version` (`change_events.py:56-110`) · the `ALLOWANCE_OVERRUN` → item_type `ALLOWANCE` requirement is checked *after* the status gate, reported as `ERR_CHANGE_EVENT_STATE_INVALID` 409, and fails equally when `qualification_item_id` is null (`:121-135`) · submit writes only the event row (`:136-139`) · **mismatch** — `review_note` is recorded on all three review actions, not `BEGIN_REVIEW` alone, and omission/null retains the stored note (`:172-173`) · review reads no project row at all, so it works on a closed-out frozen project (`:142-148`) · the project row is touched exactly once on every classification branch and the response `data` is the change event, never the minted proposal/draw (`:264-278`) · for `CONTINGENCY_USE_CONSTRUCTION` the §3.7 approval rule reduces to threshold + posture, since the minted draw's `origin` is always `CHANGE_EVENT_CLASSIFICATION` (`:212,223-228`).

§3.7: the `gmp_status` gate is the whole project-level check and precedes the draw status gate; a denial leaves `approved_by_user_id` null; neither decision writes the project row (`draws.py:46-61`) · **mismatch** — post's real order is draw-status → frozen → `gmp_status`, departing from §2.11 step 8, so a post on a settled project reports `ERR_CONTINGENCY_FROZEN`, not `ERR_GMP_NOT_EXECUTED` (`:72-79`) · the sufficiency test is endpoint-local, applies from both `REQUESTED` and `OWNER_APPROVED`, and is **not** a universal property of reaching `POSTED` (`:94-100`) · **mismatch** — the hold fires only on an actual `OPEN → CONSTRAINED` transition (`derive.py:32-39`) · **mismatch** — void has no separate `closeout_status` check (the `FROZEN` test is the whole settlement block) and no `gmp_status` gate, and `posted_at` survives the void (`:114-139`).

§3.8: opening writes only the report row (`cost_reports.py:62-78`) · `cost_code` 1–60 chars, `quantity` signed with no decimal-place limit, `markup_pct` may be negative, `unit_rate` non-negative ≤4dp, `disputed` defaults false, `line_amount`/subtotals may be negative (`validation.py:153-189`, `cost_reports.py:85-91`) · append answers **HTTP 201** with the whole updated report (subtotals + full `lines`), not the line alone (`:140-142`) · **mismatch** — the reconcile snapshot copies `buyout_savings_trade_level` exactly as it stands with no recompute at decision time, so it inherits any staleness left by a market reopening (`:179`) · neither reconcile decision carries a project-level gate or writes the project row (`:145-181`) · release has no `gmp_status`/closeout gate and no project write (`:184-200`) · **mismatch** — the buyout-recompute trigger list was 3 items and omitted settlement; now exactly four (award, subcontract execution, termination cascade, settlement) with explicit exclusion of package create and market reopen (`derive.py:58`).

§4 **mismatch** ×2: the header's "every action endpoint returns 200" was false — the cost-line append returns 201 · `GET /change-events` filter list omitted `qualification_item_id` and `source_subcontract_id`.

Pass-2/1 hand-offs: signed no-dp-limit cost-line fields **pinned**; the `work_package_id`-on-a-cost-line carve-out **verified already consistent** (`cost_reports.py:100` calls `lookups.resource`, not `lookups.work_package`) so no change was needed; stale buyout snapshot **revised** to claim no freshness; frozen-project money movement **verified non-conflicting** (§3.7's prose is endpoint-scoped, so pass 2's §3.5 settle-credit pin stands); `ERR_CONTINGENCY_INSUFFICIENT` **given an explicit non-universality disclaimer** cross-referencing §3.5's bypass; §3.7's hold-cascade restatement **revised** to transition-driven.

Pass 3's structural sanity check: all five top-level sections present and in order (§1 L3, §2 L11, §3 L188, §4 L359, §5 L420) with 20 `###` subsections; §4 endpoint table 54 well-formed 4-column rows, zero malformed; §5 error table 43 well-formed rows; file ends cleanly on the last error-table row. Pass 3 left §2.11's step-8 ordering (pass 1 territory) untouched and instead documented the draw-post deviation locally in §3.7, resolving the conflict without reverting pass 1's work.

**Orchestrator verification:** `PRD_COMPLETED.md` is 468 lines / 123,550 chars and is **not** byte-identical to `PRD_FINALIZED.md` (464 lines / 100,032 chars) — the scan genuinely ran, unlike the known no-op failure mode. Re-confirmed independently: five `## ` top-level sections in order, tail ends on a complete §5 table row, and no difficulty-directive leak. Final artifact sweep found exactly one `worklog.md` (at the task root — no cwd-drift strays under `workspace/`), all eight passing `results.{1..8}.json` still in place, and `workspace/sweep.log` retained from the final green sweep.

**PIPELINE COMPLETE — Step 9 has written `workspace/PRD_COMPLETED.md`.**
