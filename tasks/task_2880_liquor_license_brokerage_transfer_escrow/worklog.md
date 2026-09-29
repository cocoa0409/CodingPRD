# Worklog — task_2880_liquor_license_brokerage_transfer_escrow

## Step 1: Create task directory — 2026-09-05T10:50:09.978Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2880_liquor_license_brokerage_transfer_escrow` and `.../workspace`. Index 2880 was pre-assigned by the orchestrating prompt (no auto-allocation scan performed, to avoid collision with the ~32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T13:11:00.000Z

Subagent summary (verbatim):

Final linter output, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2880_liquor_license_brokerage_transfer_escrow/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2880_liquor_license_brokerage_transfer_escrow/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2880_liquor_license_brokerage_transfer_escrow/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    57
  §1.1 entities declared:     13
  §1.8 instances scanned:     21
  §1.9 instances scanned:     55
  Calls scanned (§1.8+§1.9):  1097

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2880_liquor_license_brokerage_transfer_escrow/`):

```
-rw-rw-r-- 135221  SCAFFOLD.yaml                    2668 lines
-rw-rw-r-- 132725  SCAFFOLD_DIFFICULTY_DESIGN.yaml  2226 lines
-rw-rw-r-- 258226  SCAFFOLD_CORNER_DESIGN.yaml      4436 lines
```

## Summary for the worklog

**SCAFFOLD.yaml** (§1.0–§1.7 only; contains neither design key, verified by parse): `api_prefix: ""`, 13 entities (County, License, Listing, Buyer, Premises, PurchaseAgreement, DualAgencyDisclosure, EscrowAccount, EscrowLedgerEntry, TransferApplication, Posting, Protest, SafekeepingFiling), 7 state machines, 2 OCC `concurrency_rules` (Listing, License), 10 calculations, 32 ordered validations, 55 errors, 57 endpoints, 6 roles + mandatory `identity:` (broker, buyer, seller, regulator_analyst, escrow_officer, admin). Logical clock at the default `2026-08-01T00:00:00Z`.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 9 rules / 21 instances:
- `dual_variant_calc` (2), `combinatorial_formula` (3), `non_linear_state_machine` (2), `transitive_cascade` (2), `priority_pair_validation_conflict` (2), `boundary_precision_check` (4), `cross_entity_state_dependency` (2), `resource_temporal_overlap` (2), `compensating_invariant` (2 — escrow cash conservation across release, county escrow-occupancy conservation across refund).

**SCAFFOLD_CORNER_DESIGN.yaml** — all 9 breadth sections, 78 instances (55 full `test_recipe` + 23 `excluded_because` stubs citing §1.8 instances by name):
entities 12 · state_machines 11 (7+4) · calculations 9 (3+6) · validations 11 (8+3) · endpoints 6 (4+2) · errors 15 (12+3) · rbac 7 (6+1) · cross-cutting complexity layers 5 (2+3) · consistency model 2 (1+1).

Self-consistency checks passed: all 55 §1.6 error ids are exercised across the two design files; zero duplicate instance names across their union; every `excluded_because.difficulty_instance` resolves; no dangling `calculations.*` or `entities.*.fields.*` references in either file. Notable fixes made along the way: removed the unreachable `ERR_INVALID_FILING_STATE` (SafekeepingFiling has one non-terminal state, so GRANTED/DENIED fall to `ERR_ALREADY_TERMINAL`) from both §1.6 and validation priority 32; corrected an assert that had License staying `IN_ESCROW` after an APPROVED decision (it becomes `TRANSFERRED`, agreement `CLOSED`); avoided a latent `ERR_LICENSE_CONTRACT_OVERLAP` collision in the OCC instance by making the competing closing windows half-open adjacent.

Orchestrator note: the scaffold generator copied the difficulty directive line ("Generate task harder than expert level!") verbatim into SCAFFOLD.yaml's `scenario:` key. The orchestrator stripped that single line from SCAFFOLD.yaml after this step so it cannot reach PRD.md; the scenario text itself is untouched. Neither design yaml contained the line.

## Step 3: Copy shared files — 2026-09-05T13:12:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (bash-only step, no subagent).

## Step 4: Generate PRD — 2026-09-05T13:30:00.000Z

Subagent summary (verbatim):

PRD generation complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2880_liquor_license_brokerage_transfer_escrow/workspace/PRD.md` — 471 lines, 13,153 words. Ends at the last row of the §5 table (`ERR_ESCROW_INSUFFICIENT_FOR_DISBURSEMENT | 422`); no audit footer, not mid-sentence.

**Sections emitted**
- §1 Introduction (3 paragraphs, quota-scarcity framing)
- §2 Global Specifications, 10 subsections: 2.1 Parties/Headers/RBAC; 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`, verified `True`); 2.3 Pagination; 2.4 Logical Clock & Statutory Date Arithmetic; 2.5 Common Properties & Version Semantics; 2.6 Money, Basis Points, Rounding; 2.7 Optimistic Concurrency; 2.8 Cascade Discipline & Conserved Quantities; 2.9 Identifier Resolution & Order of Refusal (32-step refusal ladder); 2.10 County Quota Position
- §3 Business Logic, 9 subsections (3.1 reference inventory → 3.9 safekeeping/nonuse extension)
- §4 Endpoint Definitions: 1 intro paragraph + 57-row, 4-column table
- §5 Error Code Catalogue: 55-row, 2-column table
- 116 table rows total = 57 + 55 + 4 header/separator

**Hard Contract reports**
- **Contract 1 — Field-Name Coverage: PASS.** entity fields 121/121 (0 missing); request-body fields 83/83; query params 21/21; path params 13/13.
- **Contract 2 — Rule Coverage: PASS.** 2/2 concurrency rules (each with write endpoint, `expected_*_version` field, error id, 412); 32/32 validation priorities as the ordered §2.9 ladder with `applies_to` scopes; 36/36 state transitions as state pairs with preconditions and side effects; 10/10 calculations in prose with every constant embedded; 55/55 error IDs reachable from §2/§3; sibling-branch symmetry confirmed for RELEASE/REFUND/FORFEIT, APPROVED/DENIED, PRE_CHECK/FINAL_REVIEW, COMPARABLE_SALES/INCOME_MULTIPLE, INITIAL/EXTENSION, GRANT/DENY.
- **Contract 3 — §3 Path Purity: PASS.** 830 backtick tokens scanned in §3; 0 begin with `/`, 0 bare HTTP methods, 0 method+path combinations. Path variables are introduced only in §2.9 and the §4 intro.

**Coverage check:** all 57 scaffold §1.5 endpoints appear in §4 (0 missing); all 55 errors appear in §5 and are reachable from prose. No fuzzy/hedging words remain.

**Three scaffold tensions resolved toward the normative rule tables** (worth flagging for downstream steps):
1. Buyer qualification requires status ∈ {`QUALIFIED`, `PROVISIONALLY_QUALIFIED`} **and** `qualification_mode` == `FINAL_REVIEW`; a `PRE_CHECK`-derived qualification satisfies neither execution nor filing.
2. Release is **not** contingency-gated (validation priority 74 and the `HELD → RELEASED` preconditions govern over the error-catalog condition string); only execute, resubmit and FORFEIT are.
3. `requested_months` is **clamped** (cap 12 INITIAL / 6 EXTENSION) rather than rejected; `ERR_SAFEKEEPING_EXTENSION_LIMIT` is scoped to a petition for a fourth window.

Also noted: `GET /escrow-ledger-entries/{entry_id}` has no not-found code in the catalog, so §2.9 states it is answered with HTTP 404 without inventing an error id.

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened or grepped, and no sibling task directory was read. Scratch files live under `/tmp/task_2880_prd/`.

Orchestrator truncation check: `tail -12 PRD.md` ends on the final §5 error row, a real section boundary — not truncated. Grep for the difficulty directive and the word "scaffold" in PRD.md returned 0 hits.

## Step 6: Generate implementation — 2026-09-05T14:11:00.000Z

(Steps 5 and 6 ran concurrently; Step 6 finished first, so its entry is recorded first. Orchestrator note: the two Agent calls went out in back-to-back messages rather than a single message. To preserve the physical isolation the skill relies on, the Step 6 prompt carried an explicit absolute prohibition on reading `test_helpers/`, `test_suite/`, and both design yamls; the subagent confirmed on exit that no test artifacts were read.)

Subagent summary (verbatim):

Implementation complete and verified.

## Deliverable
`/home/ubuntu/github/CodingPRD/tasks/task_2880_liquor_license_brokerage_transfer_escrow/workspace/implementation/` — Python 3 + Flask, in-memory dicts only (no SQLite/JSON/`/tmp` persistence, nothing seeded at startup; a fresh boot returns `total_count: 0` on all nine list endpoints).

| file | lines | role |
| --- | --- | --- |
| `start.sh` (exec bit set) | 10 | `cd $(dirname $0)`, guarded `pip install` (only when flask missing), `exec python3 app.py`, `PORT` env with 10000 default, binds `0.0.0.0` |
| `app.py` | 82 | app factory, 7 blueprints, request serialization lock, ApiError/HTTPException/500 handlers |
| `errors.py` | 80 | full PRD §5 catalog + status map |
| `store.py` | 134 | in-memory `Store`, logical clock (starts `2026-08-01T00:00:00Z`), id/iso/day/month arithmetic, record helpers |
| `envelope.py` | 93 | PRD §2.2 envelope, `req_` + 20 uppercase alnum ids, pagination + filters |
| `validation.py` | 149 | body/field coercion and `ERR_INVALID_REQUEST` shape gate |
| `authz.py` | 113 | 3-step auth, role sets, ownership, 12 `*_or_404` fetchers |
| `calc.py` | 281 | all PRD §3 formulas (`Decimal` + ROUND_HALF_UP, integer cents/bps) |
| `domain.py` | 183 | county recompute, ledger replay, approval/denial/compensating cascades |
| `routes_reference.py` | 273 | counties, parties, brokerages, licenses, `_clock/set_current_utc` |
| `routes_premises.py` | 107 | premises + zoning/landlord verifications |
| `routes_listings.py` | 157 | listings, valuation-preview, activate, withdraw |
| `routes_agreements.py` | 333 | agreements, deposit, execute, terminate, settlement, ledger |
| `routes_disclosures.py` | 99 | dual-agency disclosures + acknowledgement |
| `routes_applications.py` | 362 | transfer applications, deficiency loop, posting, decision, protests |
| `routes_safekeeping.py` | 137 | safekeeping/extension filings + decide |
| `requirements.txt` | 1 | `flask` |

Total 2594 lines; all modules byte-compile.

## Endpoints
**57 registered routes, an exact one-to-one match with the 57 rows of the PRD §4 table** (verified by enumerating `url_map`). No extra routes.

## Smoke-test result (three scenario suites, all green)
Booted via `PORT=18833 bash start.sh` on a fresh process (ready in <2 s), then killed by exact PID only (`kill 2821388`, plus `2811604`/`2817348`/`2822960` from earlier boots) — no broad pkill. Server log shows zero tracebacks.

- **Suite 1 (happy path + envelope):** create/read/404/401/400/403 envelopes match §2.2; full chain county -> parties -> license -> premises (suitability `CONDITIONAL/CUP_OUTSTANDING` -> suitable after CUP+consent) -> qualification 100/QUALIFIED -> listing valuation-preview (comp floor 4 500 000, income multiple 18 000 000, divergence) -> activate (freeze) -> OCC 412 replay -> agreement (`required_deposit_cents` 1 300 000 = 1000+300 bps on 10 000 000) -> deposit mismatch 422 -> HELD -> dual-agency disclosure both acks -> execute (license IN_ESCROW, listing UNDER_CONTRACT, `escrow_committed_count` 1) -> application (fee 173 250) -> accept-review -> post-notice -> 409 posting-not-elapsed -> 403 segregation-of-duties -> APPROVED cascade (license TRANSFERRED, listing SOLD, agreement CLOSED) -> RELEASE (150 000 / 600 000 / 550 000, balance 0, ledger walks 1 300 000 -> 0 in pinned order) -> pagination meta.
- **Suite 2:** nonuse-not-reached 422, stale-license 412, extension-without-window, INITIAL grant (12 months, 20 000c), chained extensions (40 000c / 80 000c, windows chained not overlapped, month-clamping), pending-filing and extension-limit refusals; deficiency loop with recomputed fees 204 750 (round 1) and 243 000 (round 2), `DEFICIENT -> SUBMITTED` per scaffold, limit exceeded on round 3; second-protest refusal; unanswered-protest-requires-denial; response-window-closed; DENIED -> protest SUSTAINED -> REFUND (compensating cascade: agreement TERMINATED, license ACTIVE, listing ACTIVE, `escrow_committed_count` back to 0, quota count flat) -> already-settled 409; responded protest -> APPROVED -> protest OVERRULED (hop 5) -> RELEASE with ledger sum 0; FORFEIT path (contingency-still-open 409 first, then FORFEIT_SELLER row, cascade).
- **Suite 3:** `ERR_LICENSE_CONTRACT_OVERLAP` on overlapping closing windows, `ERR_LISTING_HAS_OPEN_OFFERS` on withdraw, `ERR_POSTING_WINDOW_CONFLICT` across two applications on the same premises inside the 30-day quiet buffer, `ERR_INVALID_AGREEMENT_STATE` on terminating an EXECUTED agreement.

Every failure seen during smoke-testing traced to my throwaway test script (wrong expected fee, wrong field names `deficiency_note`/`termination_reason`, an invalid `grounds` value, absolute vs. relative clock targets) — each was checked against PRD/SCAFFOLD and the implementation was right in all cases; no implementation change was needed beyond two fixes made earlier (a `date` branch in `store.public` so `last_active_date` serialises as `YYYY-MM-DD`, and a public `default_message()` in `errors.py`).

Scratch stayed under `/tmp/task_2880_impl/`; `worklog.md` untouched; no test artifacts were read.

## Step 5: Generate unit tests — 2026-09-05T14:37:00.000Z

Subagent summary (verbatim):

Both remaining Stage-2 files are written and the full suite passes every audit.

## Deliverables

**Stage 1 — `/home/ubuntu/github/CodingPRD/tasks/task_2880_liquor_license_brokerage_transfer_escrow/test_helpers/`** (9 files, 2501 lines): `types.py` 447, `api_client.py` 284, `api_errors.py` 124, `constants.py` 130, `test_users.py` 72, `factories.py` 266, `assertions.py` 366, `fixtures.py` 772, `__init__.py` 40.

**Stage 2 — `.../test_suite/`** (18 files, 5376 lines, 98 tests):

| file | lines | tests |
|---|---|---|
| conftest.py | 67 | – |
| test_01_valuation_and_qualification_variants.py | 298 | 7 |
| test_02_deposit_fee_and_commission_arithmetic.py | 354 | 6 |
| test_03_application_cycle_and_parallel_status.py | 223 | 4 |
| test_04_closing_and_compensating_cascades.py | 240 | 4 |
| test_05_order_of_refusal_conflicts.py | 95 | 2 |
| test_06_boundaries_and_thresholds.py | 391 | 8 |
| test_07_cross_entity_state_dependencies.py | 227 | 4 |
| test_08_temporal_windows_and_overlaps.py | 225 | 4 |
| test_09_conserved_quantities.py | 255 | 4 |
| test_10_reference_inventory_and_common_fields.py | 495 | 12 |
| test_11_listing_and_application_state_machines.py | 323 | 7 |
| test_12_quota_valuation_and_safekeeping_calculations.py | 241 | 3 |
| test_13_regulatory_gates.py | 491 | 8 |
| test_14_endpoint_behaviour.py | 246 | 4 |
| test_15_error_catalogue.py | 629 | 12 |
| test_16_access_control.py | 345 | 6 |
| test_17_concurrency_and_cascade_visibility.py | 231 | 3 |

Files 01–09 are queue A (43 tests); 10–17 are queue B (55 tests).

## Instance coverage

- **Queue A (Difficulty)** — 21 instances, **20 translated**, each with >=2 tests. **1 skipped:** `priority_pair_validation_conflict/application_referential_beats_fiscal_fee` — its setup requires an EXECUTED agreement whose selling licensee is `DELINQUENT`, but PRD §3.3 refuses listing activation unless `tax_clearance_status` is `CLEARED` and no endpoint mutates that field, so the asserted precedence is unreachable. No placeholder, no xfail.
- **Queue B (Corner)** — 55 non-stub instances, **all 55 translated** (entities 12, state_machines 7, calculations 3, validations 8, endpoints 4, errors 12, rbac 6, cross-cutting 2, consistency 1). The 23 `excluded_because:` stubs were not translated and a machine check confirms none of them is tagged.

## Verification run

A checker (`/tmp/task_2880_tests/verify.py`) passes clean over all 18 suite files: exactly one `Design:` line per test and it is the final docstring line; every tag resolves to a real instance name in the two design yamls; every `PRD: "…"` quote matches `workspace/PRD.md` verbatim under whitespace normalisation; no `skip`/`skipif`/`xfail`; no occurrence of the word "scaffold". `python3 -m pyflakes` is clean on every suite file (only the expected star-re-export notices on `test_helpers/__init__.py`), and `compileall` succeeds.

Two pre-existing citation defects were found and fixed by this pass: `test_01` truncated the valuation-preview sentence before its em-dash clause and dropped the markdown bold from "**The comparable-sales variant**"; `test_06` dropped the bold from "**The income-multiple variant**". Both now match the PRD byte-for-byte.

## Notes for the orchestrator

- Design/PRD conflicts resolved in favour of the PRD and documented in the affected docstrings: county `protest_window_days` default is 30 (design yaml says 15 — the instance that pins a 2026-08-16 protest deadline now passes `county_overrides={"protest_window_days": 15}` explicitly); `suitability_reason_code` on a computed-field check is `"NONE"`, not null.
- One deliberate strengthening in `test_14`: the two licences in the list round-trip are created at different logical instants so `created_at ASC` ordering is uniquely PRD-derived.
- `worklog.md` was not touched; nothing was read or written under `workspace/implementation/`; no test dirs exist under `workspace/`; `__pycache__` removed.

## Step 7: Run tests and iterate — 2026-09-05T15:08:00.000Z

Subagent summary (verbatim):

Clean 8-round sweep achieved.

## Summary

**Iterations run:** 2 (sweep → 4 deterministic failures → 3 test fixes → sweep → all green).

**Iteration 1 result:** 94/98 in all 8 rounds; the same 4 tests failed in all 8 rounds (deterministic, not load-induced).

**Tests deleted:** none. All 4 failures were verbatim PRD-covered rules whose *tests* set up preconditions inconsistent with the PRD. No assertion was weakened, no skip/xfail added.

**Fixes applied to `test_suite/` (test bugs, STEP 2):**

1. `/home/ubuntu/github/CodingPRD/tasks/task_2880_liquor_license_brokerage_transfer_escrow/test_suite/test_07_cross_entity_state_dependencies.py` — `_unverified_premises_under_review()` passed `review_mode="PRE_CHECK"`, but PRD §3.2 says *"Both agreement execution and transfer-application filing require a buyer whose stored `qualification_status` is `QUALIFIED` or `PROVISIONALLY_QUALIFIED` and whose stored `qualification_mode` is `FINAL_REVIEW`; … one whose latest review was only a `PRE_CHECK` … [is] refused with `ERR_BUYER_NOT_QUALIFIED`."* The fixture's own setup chain therefore could never reach `application_under_review`. Dropped the override so the default `FINAL_REVIEW` applies — with the permit at `REQUIRED_NOT_FILED` the score is 100−15 = 85 → `QUALIFIED`, which still leaves the premises `CONDITIONAL`/`CUP_OUTSTANDING`, exactly the state both tests assert. (Fixed 2 failing tests.)

2. `test_suite/test_06_boundaries_and_thresholds.py` — `test_terminating_the_sole_draft_offer_frees_the_listing_for_withdrawal` drafted its second competing offer at `closing_window_start="2026-10-01"`, which intersects the first agreement's reserved half-open window `[2026-09-01, 2026-12-30)`; PRD §3.4 mandates `ERR_LICENSE_CONTRACT_OVERLAP` for exactly that. Moved the second window to `2026-12-30T00:00:00Z`, which per PRD *"two windows that merely touch — one ending at the exact instant the next begins — do not intersect and are both accepted"* is the legitimate way to hold two concurrent draft offers.

3. `test_suite/test_10_reference_inventory_and_common_fields.py` — `test_suitability_and_quota_availability_are_derived_never_supplied` expected `SUITABLE`/`NONE` after a corrected survey, but never recorded landlord consent, so the PRD's rule 8 (*"Landlord consent is still `PENDING` — `CONDITIONAL` with reason `LANDLORD_PENDING`"*) correctly fired first. Added a `record_landlord_consent(..., "GRANTED")` step (with an intermediate assertion that the verdict is still `UNSUITABLE`/`SCHOOL_DISTANCE`, since only the distance correction can clear rule 1) so rule 9 genuinely applies; bumped the expected `version` from 2 to 3 to account for the extra recompute.

**Fixes applied to `test_helpers/`:** none needed (only the `record_landlord_consent` import was added to test_10; the helper already existed and was already exported via the barrel).

**Fixes applied to `implementation/`:** **none.** All four failures traced to test-side preconditions; the implementation was PRD-faithful on every one of them (FINAL_REVIEW gate, half-open window overlap check, and the nine-rule suitability ladder ordering).

**Final sweep evidence** (listing pasted above, all 8 files timestamped 15:03):

| file | passed / total |
|---|---|
| results.1.json | 98 / 98 |
| results.2.json | 98 / 98 |
| results.3.json | 98 / 98 |
| results.4.json | 98 / 98 |
| results.5.json | 98 / 98 |
| results.6.json | 98 / 98 |
| results.7.json | 98 / 98 |
| results.8.json | 98 / 98 |

Zero failures, zero errors, zero skips in every round. `worklog.md` was not touched.

Orchestrator independent verification: re-parsed all 8 `results.$i.json` directly — every round reports `passed=98 total=98 failed=0 errors=0 skipped=0`. `grep -rn "xfail\|pytest.mark.skip" test_suite/` returns nothing, and `test_suite/` still holds 98 `def test_` functions, consistent with the "0 deletions" claim.

Step 8 skip decision: NOT skipped. Step 7 ran 2 iterations with 3 `test_suite/` fixes, so the baseline sweep was not clean and the skip condition (0 deletions AND 0 test_suite AND 0 test_helpers AND 0 implementation fixes) does not hold. Note for Step 8's reader: since Step 7 applied **zero** `implementation/` fixes, a byte-identical `PRD_FINALIZED.md` is a legitimate outcome here — the three fixes were test-side precondition repairs against PRD rules the PRD already stated verbatim, so there may be no PRD silence to pin.

## Step 8: Finalize PRD — 2026-09-05T15:10:00.000Z

Subagent summary (verbatim):

## Result: `PRD_FINALIZED.md` is byte-identical to `PRD.md`

- `PRD.md`: 471 lines. `PRD_FINALIZED.md`: 471 lines. Delta: **0 lines, 0.0%**. `diff -q` reports IDENTICAL.
- **Changes: none.** All three Step 7 items are pure test-side fixture bugs against rules the PRD already states verbatim, and the implementation matches those PRD sentences literally. No PRD silence and no PRD/impl mismatch was found at any of the three sites.

### Per-item verification log (mandatory (a)/(b)/(c) for each candidate edit; all three resolved to "no edit")

**Item 1 — `review_mode="PRE_CHECK"` fixture override (test_07)**
- (a) Subject: the buyer-qualification gate (`qualification_status` x `qualification_mode`) and where `qualification_mode` is written/read.
- (b) Enumerated impl paths: `implementation/calc.py:189-191` (`buyer_is_qualified` — requires status in `QUALIFIED`/`PROVISIONALLY_QUALIFIED` **and** mode `== "FINAL_REVIEW"`); both callsites `implementation/routes_agreements.py:226` (execution) and `implementation/routes_applications.py:32` (filing) — the only two, matching PRD §2.9 step 14; writer `implementation/routes_reference.py:139-158` (`review_mode` is a **required** enum field, no default — matches PRD "supplying a `review_mode`"; initial `qualification_mode: None` at `routes_reference.py:126`); scoring `implementation/calc.py:161-186` (premises component applied only under `FINAL_REVIEW`, four common deductions, clamp 0..100, DISQUALIFIED override before banding).
- (c) No wording adjustment needed — PRD §3.2 final paragraph and §3.2 score paragraphs already describe exactly this. No edit.

**Item 2 — competing draft offer window moved to the touching instant (test_06)**
- (a) Subject: the half-open license-window reservation / `ERR_LICENSE_CONTRACT_OVERLAP`, plus the withdrawal path the test exercises.
- (b) Enumerated impl paths: `implementation/routes_agreements.py:58-67` — `deadline = add_days(start, contingency_days)`, intersection test `start < other["contingency_deadline_at"] and other["closing_window_start"] < deadline`, scanned over same-`license_id` agreements in `DRAFT` or `EXECUTED` only (strict `<` on both sides => touching windows accepted, exactly PRD §3.4); `implementation/routes_agreements.py:96` (`open_offer_count` +1 on draft); `implementation/routes_agreements.py:241-263` (terminate -> `domain.recompute_open_offers` + `bump(listing)`); `implementation/domain.py:76-83` (recompute counts only `DRAFT` agreements on that listing); `implementation/routes_listings.py:152` (`ERR_LISTING_HAS_OPEN_OFFERS` when count > 0); day arithmetic preserving time-of-day per PRD §2.4.
- (c) No wording adjustment needed. No edit.

**Item 3 — missing `record_landlord_consent` step and version 2->3 (test_10)**
- (a) Subject: the nine-rule suitability ladder ordering, the two standing-field writers, and premises `version` accounting.
- (b) Enumerated impl paths: `implementation/calc.py:194-212` (`premises_suitability` — the nine rules in PRD's exact order: school, church, CUP_DENIED, zoning, LANDLORD_REFUSED, CUP outstanding/pending, undue concentration, landlord PENDING, else `SUITABLE`/`NONE`; `<` comparisons => inclusive minimum); `calc.py:215-219` (`apply_suitability`) and all three of its callers — `implementation/routes_premises.py:46` (registration, no `bump`, so `version` stays 1), `:88-89` (zoning verification: CUP overwrite + optional survey corrections, then `bump`), `:105-106` (landlord consent: status overwrite + optional `consent_document_ref`, then `bump`) — matching PRD §3.2 "recomputed on registration, on zoning verification and on the recording of landlord consent" and "no other operation writes either standing field"; `calc.py:222-224` (`distances_ok`, the separate `ERR_DISTANCE_RESTRICTION_VIOLATION` path, left untouched); grep for `suitab` across `implementation/` confirms no other writer.
- (c) No wording adjustment needed — the 1->2->3 version progression follows directly from PRD §2.5 plus the two unconditional `bump` calls. No edit.

### Note
Per the HARD SCOPE rule I deliberately did **not** patch two things I noticed off the Step 7 sites: the qualification-review buyer/premises mismatch answering `ERR_PREMISES_NOT_FOUND` (`routes_reference.py:148-150`, PRD names the constraint but not the code) and the absence of an ownership check on `POST /premises/{id}/landlord-consent` (consistent with PRD §2.9's explicit list of twelve ownership-guarded operations, which omits it). Neither traces to a `<step_7_diff>` item, so both are Step 9's business, not Step 8's.

Orchestrator verification: `wc -c` on both files gives 93825 bytes each and `diff -q` reports no difference — a byte-identical `PRD_FINALIZED.md` is the correct outcome when Step 7 applied zero `implementation/` fixes, so this is accepted rather than re-run. The two off-site observations above are carried forward into the Step 9 prompt so the full scan does not miss them.

Step 9 plan: run as THREE sequential passes partitioned by implementation module over one shared `PRD_COMPLETED.md` (pass 1 performs the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 must not re-copy, or they would discard the previous pass's edits). A single-agent whole-repo scan has historically returned a byte-identical PRD_COMPLETED.md, which would mean the scan never really ran.

## Step 9: Complete PRD — 2026-09-05T15:47:00.000Z

Run as THREE sequential passes partitioned by implementation module over one shared `PRD_COMPLETED.md`. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden to re-copy and were given the expected line/char counts as a tripwire so a lost predecessor pass would halt them instead of silently discarding work. Partition: pass 1 = `app.py`, `envelope.py`, `errors.py`, `validation.py`, `authz.py`, `store.py`, `routes_reference.py`, `routes_premises.py`, `routes_listings.py`; pass 2 = `calc.py`, `domain.py`, `routes_agreements.py`, `routes_disclosures.py`; pass 3 = `routes_applications.py`, `routes_safekeeping.py` plus the whole-file consistency check.

Net result: `PRD_FINALIZED.md` 471 lines / 93,825 chars -> `PRD_COMPLETED.md` 478 lines / 121,324 chars (+7 lines, +27,499 chars, +29.3%). 76 edits total: 59 ambiguity-pins, 17 mismatch-revisions.

### Pass 1 summary (verbatim)

Pass 1 complete.

## Counts

- **Source** `PRD_FINALIZED.md`: 471 lines, 93,825 chars
- **Output** `PRD_COMPLETED.md`: **478 lines, 106,232 chars** (+7 lines, **+12,407 chars**), 22 diff hunks
- **23 ambiguity-pins, 4 mismatch-revisions** across 27 targeted edits. No sections added; only two new paragraphs (a closing paragraph in §2.9 and a closing note in §5), everything else in-paragraph.

## Changes

- §2.1 Broker bullet — insert — ambiguity — listing *creation* is not ownership-guarded; a Broker may create a DRAFT listing naming any `brokerage_id` — `routes_listings.py:28-51`
- §2.1 Buyer bullet — **revise** — **mismatch** — PRD claimed ownership compares `X-User-ID` to "the `buyer_id` … of the premises being acted on"; no endpoint does this. Now states premises-side operations are deliberately unguarded — `routes_premises.py:19-20,93-95`, `authz.py:45-47`
- §2.1 headers — insert — ambiguity — whitespace-only header = empty (401); both values stripped before role match and ownership compare; role match is exact/case-sensitive — `authz.py:20-33`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from A–Z0–9 — `envelope.py:11-15`
- §2.2 — insert — ambiguity — `api_request_timestamp` is the **host wall clock**, not the logical clock — `envelope.py:18-21`
- §2.2 — **revise** — **mismatch** — error envelope described only "4xx"; also used for the 5xx fault envelope — `app.py:69-71`
- §2.3 — insert — ambiguity — non-integer / out-of-range `limit`, negative `offset` -> `ERR_INVALID_REQUEST` (not clamped); empty string = omitted; offset past `total_count` -> empty page, `has_more` false — `envelope.py:53-77`
- §2.3 — insert — ambiguity — **all orderings tie-break on the server's creation sequence** (critical: the frozen logical clock makes `created_at` ties the norm); ledger adds it as final tie-break — `store.py:96,128-134`
- §2.4 — insert — ambiguity — clock response is `{current_utc}` alone, no id/version; may be set **backwards**; `to_iso8601` required — `routes_reference.py:268-273`, `store.py:46-48`
- §2.4 — insert — ambiguity — instant grammar: mandatory `Z` or `+-HH:MM` (normalised to UTC), `T`/`t`, 1–9 fractional digits in, always 3 out — `validation.py:10-55`, `store.py:55-63`
- §2.5 — insert — ambiguity — `id` is lowercase hyphenated UUIDv4; `created_at` from the logical clock; a client-sent `id` is ignored — `store.py:51-52,86-97`
- §2.9 ¶1 — insert — ambiguity — unresolved `entry_id` -> **`ERR_ENTRY_NOT_FOUND`**; unrouted path -> `ERR_NOT_FOUND` 404; undeclared method -> `ERR_INVALID_REQUEST` with **HTTP 405**; trailing slash insignificant; neither transport refusal requires headers — `app.py:54-67`, `authz.py:112`
- §2.9 check 4 — insert — ambiguity — six pins: body must be a JSON object (absent body allowed only for listing activate/withdraw); Content-Type ignored; fields checked in **declared order**, first fault wins; explicit `null` = omitted; whitespace-only string refused but values stored untrimmed; no scalar coercion; extra fields ignored — `validation.py:22-149`
- §2.9 (new closing ¶) — insert — ambiguity — the three uniqueness rules report `ERR_INVALID_REQUEST` (400) and sit **after** check 6 and **before** check 19 — `routes_reference.py:46-48,172-174,207-212`
- §3.1 — insert — ambiguity — store boots empty, nothing seeded — `store.py:15-38`
- §3.1 — insert — ambiguity — `county_code` collision -> `ERR_INVALID_REQUEST` — `routes_reference.py:46-48`
- §3.1 — insert — ambiguity — an explicit **empty** `permitted_zoning_codes` array is accepted and permits nothing (only omission/`null` triggers the default) — `routes_reference.py:37,49-51`
- §3.1 — insert — ambiguity — a freshly registered county reports `version` 1; the opening quota computation is not a mutation — `routes_reference.py:69-71`
- §3.1 — insert — ambiguity — `state_broker_license_no` collision -> `ERR_INVALID_REQUEST` — `routes_reference.py:172-174`
- §3.1 — insert — ambiguity — `license_number` collision -> `ERR_INVALID_REQUEST`, after FKs and before quota — `routes_reference.py:207-212`
- §3.1 — insert — ambiguity — filter semantics: exact string equality, conjunctive, empty-string ignored, unknown param ignored, non-matching value -> empty page (never validated against its enum) — `envelope.py:80-93`
- §3.1 — insert — ambiguity — `GET /licenses/{id}/safekeeping-filings` accepts only `status` + `limit`/`offset` — `routes_reference.py:255-264`
- §3.2 — insert — ambiguity — **[Step 8 finding 1]** a `premises_id` belonging to another buyer -> `ERR_PREMISES_NOT_FOUND` (404) — `routes_reference.py:147-150`
- §3.2 — insert — ambiguity — one stored qualification result, no history, no state precondition; each run overwrites all four fields, so a `PRE_CHECK` after a `FINAL_REVIEW` withdraws eligibility — `routes_reference.py:139-158`
- §3.2 — insert — ambiguity — zoning-verification's four survey fields are a partial update (omitted or `null` = untouched, unclearable); `consent_document_ref` likewise; both operations carry no state precondition and no ownership check — `routes_premises.py:71-107`
- §3.3 — **revise** — **mismatch** — the "four preconditions" narrative order is not the refusal order; §2.9 governs (collision beats pending filing; tax clearance beats pending filing) — `routes_listings.py:103-127`
- §3.3 — insert — ambiguity — activation accepts an entirely absent body; `default_valuation_basis` read live at activation — `routes_listings.py:98-100,128`
- §3.3 — **revise** — **mismatch** — withdrawal's `reason` is validated then **discarded**; a `Listing` has no field for it (contrast `termination_reason`) — `routes_listings.py:144`
- §3.3 — insert — ambiguity — valuation-preview has no ownership or state precondition (answers for DRAFT/WITHDRAWN/SOLD); its `scarcity_bps` is live and never persisted — `routes_listings.py:74-92`
- §5 — insert — ambiguity — added `ERR_ENTRY_NOT_FOUND` 404, `ERR_NOT_FOUND` 404, `ERR_INTERNAL` 500 rows plus a note that `ERR_INVALID_REQUEST` carries 405 in the one transport case — `errors.py:4-63`, `app.py:56-71`

## Step 8 hand-off findings

1. **Pinned.** §3.2 now reads: "a `premises_id` that resolves to a premises whose `buyer_id` is some other buyer is refused with `ERR_PREMISES_NOT_FOUND` (HTTP 404), exactly as an unresolvable `premises_id` is". (`routes_reference.py:148-150`)
2. **Pinned as a mismatch, not merely a silence.** Grepping every `require_buyer`/`require_seller`/`require_brokerage` call site confirms `require_buyer` fires only on the escrow deposit and the disclosure acknowledgement — **no endpoint ever compares a caller to a premises' `buyer_id`**. So §2.9's twelve-operation list was already correct, but §2.1's sentence promised a comparand that does not exist. §2.1 now says ownership compares to "the `buyer_id` of the purchase agreement being acted on, and to nothing else", and spells out that premises registration and landlord consent are unguarded for any Broker or Buyer. §3.2 also now notes landlord consent has "no ownership check".

### Pass 2 summary (verbatim)

Pass 2 complete.

## Counts
- `PRD_COMPLETED.md` **before**: 478 lines / 106,232 chars
- `PRD_COMPLETED.md` **after**: 478 lines / **110,977 chars**
- 16 edits: **12 ambiguity-pins**, **4 mismatch-revisions**. All in-paragraph (no new paragraphs, no new sections, so line count is unchanged).

## Changes
- **2.9 check 4** — revise — mismatch — the "sole exceptions" to the body-must-be-a-JSON-object rule were listed as listing activation/withdrawal only; agreement execution declares no input field and never parses the body at all (ignores malformed JSON). Worded additively so pass 3 can add accept-review/post-notice. — `routes_agreements.py:200`
- **3.1 (reverse lookups)** — insert — ambiguity — filter sets of the two nested reverse lookups I own: escrow-ledger accepts `entry_type` (ignores `agreement_id`); nested disclosures accepts `status` (ignores `agreement_id`). — `routes_agreements.py:133,164`
- **3.4 (drafting)** — insert — ambiguity — `premises_id` is never cross-checked against the offering `buyer_id` or the license's county; `closing_window_start` is unconstrained relative to the logical clock. — `routes_agreements.py:47-49,58`
- **3.4 (funding)** — insert — ambiguity — `amount_cents` has no declared range, so zero/negative -> `ERR_DEPOSIT_AMOUNT_MISMATCH` not `ERR_INVALID_REQUEST`; money dimension is inspected *before* the contract dimension, so a CLOSED agreement with funds still HELD reports `ERR_ESCROW_MUST_BE_SETTLED_FIRST`, not `ERR_ALREADY_TERMINAL`. — `routes_agreements.py:180-188`
- **3.4 (funding)** — insert — ambiguity — `version` advances once for the whole act; response is the updated `PurchaseAgreement`, not the appended ledger row. — `routes_agreements.py:192-195`
- **3.4 (ledger)** — revise — mismatch — PRD claimed `memo` "carries a human-readable label of the movement"; impl stores the client-supplied text verbatim and null when omitted, never synthesising a label. — `domain.py:41-52`
- **3.4 (termination)** — insert — ambiguity — termination inspects the contract dimension first (opposite of funding), so CLOSED/TERMINATED reports `ERR_ALREADY_TERMINAL` even with funds HELD. — `routes_agreements.py:246-254`
- **3.5 (disclosure filing)** — insert — ambiguity — no state precondition and no uniqueness rule: filable against an agreement in any state, and any number may accumulate. — `routes_disclosures.py:19-47`
- **3.5 (acknowledgement)** — insert — ambiguity — role/`party` disagreement also reports `ERR_PARTY_NOT_REPRESENTED`. — `routes_disclosures.py:78-80`
- **3.5 (acknowledgement)** — insert — ambiguity — no state precondition; the precondition sits on the *promotion*, so a `VOID` disclosure still accepts an ack (timestamp stamped, version advanced) and stays `VOID`. — `routes_disclosures.py:96-98`
- **3.5 (execution effects)** — insert — ambiguity — with several `FULLY_ACKED` disclosures, the earliest-created one drives both the gate and the `commission_mode` freeze. — `domain.py:60-64,115-117`
- **3.5 (execution effects)** — insert — ambiguity — `open_offer_count` is *not* recomputed at execution nor by the approval cascade's move to SOLD, so it keeps counting the executed agreement; only termination and the compensating cascade recompute it. — `domain.py:113-126,130-150`
- **3.8 (settlement intro)** — insert — ambiguity — the dependency is read off the *most recently created* application when several exist, and an agreement with no application at all is refused `ERR_TRANSFER_NOT_APPROVED` in all three branches. — `domain.py:93-96`, `routes_agreements.py:283-291`
- **3.8 (commission)** — insert — ambiguity — neither split line is persisted or reported; only their sum reaches `commission_total_cents`. — `calc.py:266-272`, `routes_agreements.py:310-312`
- **3.8 (county fee)** — revise — ambiguity — "the county's `transfer_fee_bps`" pinned to the county that governs the underlying license, read live at settlement. — `routes_agreements.py:298-304`
- **3.8 (release rows)** — revise — mismatch — PRD claimed every row's `balance_after_cents` is "lower than the row before it"; a zero bucket (e.g. `transfer_fee_bps` of 0, which the county schema permits) still gets a row with amount 0 and an equal balance. Also pinned: all three rows carry the same supplied `memo` and one shared `occurred_at`, order preserved by the `created_at`/creation-sequence tie-break. — `routes_agreements.py:313-317`, `store.py:132`
- **3.8 (compensating cascade)** — revise — mismatch — the agreement's `version` advances **twice** on a refund/forfeiture (settlement write + hop-2 termination write), not once; license, listing, county and each voided disclosure advance by one. — `routes_agreements.py:322-332`, `domain.py:161-183`

## Notes for pass 3
- Everything in `calc.py` (valuation, scarcity tiers, deposit, filing fee, qualification score, suitability ladder, safekeeping fee/window) and the county-quota recompute was already pinned uniquely by the PRD — no changes needed there.
- `accept-review` and `post-notice` (pass 3's `routes_applications.py`) also never call `json_body()`, so they are further exceptions to the 2.9 check-4 sentence I revised; extend that list rather than rewriting it.

### Pass 3 summary (verbatim)

Pass 3 complete.

## Counts

| | lines | chars |
|---|---|---|
| `PRD_COMPLETED.md` before my pass | 478 | 110,977 |
| `PRD_COMPLETED.md` after my pass | 478 | 121,324 |
| `PRD_FINALIZED.md` (Step 9 source) | 471 | 93,825 |

Line count is unchanged because every edit was an in-paragraph insert or revision — no new paragraphs, no new sections.

**33 changes: 24 ambiguity-pins, 9 mismatch-revisions.**

## Changes

- §2.1 — revise — mismatch — "the value survives the deficiency-and-resubmission loop" overstated the SoD comparand's stability; a further `accept-review` overwrites it, and a null comparand bars nobody — `routes_applications.py:137`
- §2.9 check 4 — revise — mismatch — **(pass-2 hand-off 1)** extended the never-parses-the-body list from agreement execution alone to also cover accept-review and post-notice (verified by `json_body` grep: those are the only two writes in my slice with no body) — `routes_applications.py:127,195`
- §2.9 check 23 — revise — mismatch — `ERR_SAFEKEEPING_EXTENSION_LIMIT` is also raised on the safekeeping *decision*, not only on filing/listing activation — `routes_safekeeping.py:119`
- §2.10 — insert — mismatch — the county recompute on a granted safekeeping decision is unconditional, including the extension self-loop that changes no license status — `routes_safekeeping.py:130`
- §3.1 — insert — ambiguity — the nested-reverse-lookup filter enumeration omitted `GET /transfer-applications/{application_id}/protests` (accepts `status`, ignores `application_id`/`grounds`) — `routes_applications.py:121`
- §3.6 — insert — ambiguity — omitted `applicant_statement_ref` is stored as null — `routes_applications.py:49`
- §3.6 — insert — ambiguity — the four state/escrow refusal codes at filing and their order (contract dimension before money); plus: nothing blocks a second application on one agreement — `routes_applications.py:53-62`
- §3.6 — insert — ambiguity — `decision_note` added to the application's initial-null field list — `routes_applications.py:89`
- §3.6 — revise — mismatch — "re-checks **four** regulatory conditions" then listed five; corrected to five and pinned that they fire in the order written — `routes_applications.py:24-40`
- §3.6 — insert — mismatch — the filing's distance re-check uses the **license's** county, not the premises'; the two `county_id`s are not forced to agree — `routes_applications.py:65`
- §3.6 — revise — ambiguity — accept-review carries no body and **overwrites** `accepted_by_analyst_id` rather than first-wins — `routes_applications.py:137`
- §3.6 — insert — ambiguity — `deficiency_codes` is an unvalidated string array (empty array accepted), stored verbatim, replacing the prior round's — `validation.py:138`, `routes_applications.py:157`
- §3.6 — insert — ambiguity — resubmission always returns to `SUBMITTED`; `applicant_statement_ref` is a partial update (omitted/null retains) — `routes_applications.py:185,189`
- §3.6 — revise — ambiguity — resubmission overwrites `fee_paid_cents` with the latest tender while `fee_paid_total_cents` accumulates; the two diverge — `routes_applications.py:187-188`
- §3.6 — insert — ambiguity — resubmission re-checks none of the five regulatory gates and neither agreement dimension — `routes_applications.py:162-192`
- §3.6 — revise — mismatch — publication's four preconditions are evaluated distance -> suitability -> CUP -> collision, not in the narrated order — `routes_applications.py:206-227`
- §3.6 — insert — ambiguity — the conflict scan skips every other status and any null `posting_ends_at`, and spans all applications on that `premises_id` regardless of license/agreement — `routes_applications.py:215-227`
- §3.6 — revise — mismatch — the posting/protest windows come from the **premises'** county, read live — `routes_applications.py:205,230-232`
- §3.7 — insert — ambiguity — `response_due_days` is unbounded (zero/negative accepted) and is not persisted — `routes_applications.py:291,307`
- §3.7 — insert — ambiguity — **at most one protest per application ever**, since acceptance leaves `POSTED` and nothing returns to it — `routes_applications.py:294,313`
- §3.7 — revise — mismatch — a terminal protest yields `ERR_ALREADY_TERMINAL`, not `ERR_INVALID_PROTEST_STATE`; guard order is protest state -> application state -> window — `routes_applications.py:346-357`
- §3.7 — insert — ambiguity — the decision's three common preconditions fire in §2.9 order (SoD first, elapsed last); null comparand imposes nothing — `routes_applications.py:245-257`
- §3.7 — revise — ambiguity — approval writes `status`/`decision_note` too and bumps the application before any cascade write; cascade write order pinned — `routes_applications.py:268-277`
- §3.7 — insert — ambiguity — the approval cascade's hops are genuinely conditional and stop silently (license not `IN_ESCROW` => application written, nothing else) — `domain.py:130-150`
- §3.7 — revise — ambiguity — denial writes `status` and `decision_note` as well — `routes_applications.py:268-271`
- §3.7 — insert — ambiguity — denial recomputes no county counter; application written before protests — `domain.py:153-157`
- §3.9 — insert — ambiguity — `TRANSFERRED` => `ERR_ALREADY_TERMINAL`; `EXTENSION` with null window => `ERR_INVALID_LICENSE_STATE`; state -> pending -> limit -> nonuse order; filing does **not** require the license to be in the status the grant will need — `routes_safekeeping.py:39-55`
- §3.9 — insert — ambiguity — both month caps and the month clamp are silent; `requested_months` retained verbatim; a lapsed-window extension is granted a past window unrebased — `routes_safekeeping.py:57,61,70`
- §3.9 — insert — ambiguity — `expected_license_version` is not persisted on the filing — `routes_safekeeping.py:63-74`
- §3.9 — revise — ambiguity — grant's license-state mismatch => `ERR_INVALID_LICENSE_STATE`, limit re-check after it => `ERR_SAFEKEEPING_EXTENSION_LIMIT`; a denial examines neither — `routes_safekeeping.py:111-121`
- §3.9 — revise — mismatch — county recomputed on **every** grant (not "because a status changed"); denial recomputes nothing and leaves `safekeeping_extensions_count` alone; grant write order filing -> license -> county — `routes_safekeeping.py:122-137`
- §3.9 — insert — ambiguity — `safekeeping_extensions_count` is assigned, so an initial grant **resets** it to 0 — `routes_safekeeping.py:126`
- §3.9 — insert — ambiguity — an already-decided filing => `ERR_ALREADY_TERMINAL` — `routes_safekeeping.py:108`

## Final consistency check

- `diff -q` vs `PRD_FINALIZED.md`: **differs** (exit 1). Not byte-identical.
- Not truncated: still ends at `| ERR_INTERNAL | 500 |` plus the closing `ERR_INVALID_REQUEST`/`ERR_INTERNAL` note — a real section boundary.
- §4 endpoint table: **57** rows, exactly matching the 57 `@bp.route` decorators in `implementation/`.
- §5 error table: **58** rows (55 in `PRD_FINALIZED.md` + the 3 pass-1 additions), intact. Total pipe-rows 119 = 57+2 and 58+2 as expected.
- Heading count 24, identical to `PRD_FINALIZED.md` — no sections added or lost.
- Contradiction sweep on every subject I touched (`accepted_by_analyst_id`, `ERR_INVALID_PROTEST_STATE`, `protest_deadline_at`, `safekeeping_extensions_count`, `ERR_SAFEKEEPING_EXTENSION_LIMIT`, "never parse", "four preconditions"): three latent contradictions found and resolved rather than left — §2.1's over-broad SoD-survival claim, §2.10's "because a license changed status" framing of the safekeeping recompute, and my own first draft's overreach that publication is the *only* operation reading the premises' county (premises suitability does too, per `routes_premises.py:81,100`).
- No `worklog.md` access; no `SCAFFOLD*.yaml` read; no broad `pkill`; no file created.

### Orchestrator verification of Step 9

- `wc -l -c`: PRD.md and PRD_FINALIZED.md both 471 / 93,825; PRD_COMPLETED.md 478 / 121,324. `diff -q PRD_FINALIZED.md PRD_COMPLETED.md` reports they differ, so the scan genuinely ran (a byte-identical Step 9 output would mean it did not).
- §4 endpoint table: 59 pipe-rows minus 2 header rows = 57 endpoints, matching the implementation's 57 routes. §5 error table: 60 minus 2 = 58 rows.
- `tail` ends on the §5 closing note about `ERR_INVALID_REQUEST` 405 / `ERR_INTERNAL` — a real section boundary, not mid-sentence.
- Grep for "harder than expert" and "scaffold" in PRD_COMPLETED.md: 0 hits. The difficulty directive never reached any PRD variant.

## Pipeline complete — 2026-09-05T15:50:00.000Z

All nine steps done. Final state: 8/8 sweep rounds at 98/98 passing, `workspace/PRD_COMPLETED.md` written.
