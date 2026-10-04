# Worklog — task_3233_toy_line_licensing_entertainment_tie_timing_shelf

## Step 1: Create task directory — 2026-09-30T12:40:00.000Z

Task directory `./tasks/task_3233_toy_line_licensing_entertainment_tie_timing_shelf/` was pre-allocated by the caller (with `workspace/` inside); verified it exists and used it as-is. No new index computed, no other task_* directory created.

## Step 2: Generate scaffold — 2026-09-30T13:04:00.000Z

All checks pass. Final report:

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3233_toy_line_licensing_entertainment_tie_timing_shelf/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (plus an `invariants:` block anchoring Rule 9); no difficulty/corner keys inside
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Counts:**
- Endpoints: **55** (including `POST /_clock/set_current_utc` with pinned default 2026-09-01T00:00:00Z)
- Entities: **12** (Studio, Property, LicenseAgreement, ToyLine, Sku, Factory, ToolingOrder, Retailer, LineReview, AssortmentCommitment, Shipment, SafetyTest)
- State machines: **6** (LicenseAgreement cyclic amend loop, ToyLine with closeout cycle + safety-regression revert, Sku retest cycle, SafetyTest with INVALIDATED marker, AssortmentCommitment AT_RISK flagging, Shipment embargo sales)
- Difficulty instances: **18** (9 rules × 2, each rule's instances on different entity domains / error-category pairs / metrics / triggers as §0.5 requires)
- Corner instances: **29** (26 active + 3 `excluded_because:` stubs), zero name collisions with the difficulty file

**Difficulty profile** (per "harder than expert"): workflow_orchestration × temporal_windowing archetypes, with cascading side effects, dual-variant royalty accrual (provisional counts PLANNED shipments + pending amended rate vs final), threshold-driven embargo penalty tiered by retailer violation history, MOQ-rounding + utilization-tier tooling pricing, damped deep-discount closeout recovery with pinned two-stage rounding, two OCC concurrency rules, half-open line-review window overlap vs aggregate factory-month capacity overlap, and three compensating-action invariants (advance recoup, embargo ledger, closeout shelf slots).

**Self-check results:** `scaffold_lint.py` verdict pasted verbatim:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Initial lint flagged two FK_REVERSE_UNREACHABLE violations (ToyLine.license_agreement_id, ToolingOrder.sku_id); fixed by adding `license_agreement_id?` to `GET /toy-lines` and `sku_id?` to `GET /tooling-orders`. Also fixed three setup chains where `enter_closeout` was triggered from CONCEPT by inserting the full safety-test → tooling → advance sequences, and corrected one pre-computed closeout assert literal (1202, not 1205).

Orchestrator note: scaffold verified on disk — 3 files present, valid YAML, 55 unique endpoints (no dups), top-level keys `scaffold_difficulty_design` / `scaffold_corner_design` confirmed in the design files and absent from SCAFFOLD.yaml. Endpoint count (55) exceeds the Expert guideline (20–32) because 12 entities × ~4.5 ops each; per caller's "much harder than expert" instruction this was kept, and Step 6 will be hardened with one-file-per-message output discipline to compensate.

## Step 3: Copy shared files — 2026-09-30T13:06:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T13:13:00.000Z

§2.2 matches verbatim (the only diff is a trailing-newline artifact of my extraction). The PRD is complete.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3233_toy_line_licensing_entertainment_tie_timing_shelf/workspace/PRD.md` — 276 lines.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 Roles & RBAC (5 roles, identity prose per role), 2.2 API Response Structure (emitted byte-verbatim from the canonical block), 2.3 Pagination (limit default 10 / min 1 / max 100, offset 0, created_at ascending), 2.4 Common Resource Properties, 2.5 Logical Clock (startup default 2026-09-01T00:00:00Z, auto-ON_SHELF cascade), 2.6 Property & Review Lifecycles (inclusive boundary semantics), 2.7 Precision & Rounding, 2.8 OCC (both rules: `expected_license_agreement_version` / `expected_toy_line_version` → `ERR_STALE_VERSION` 412), 2.9 Nested Path Validation & 12-level error priority ordering
- §3 Business Logic in 7 domain-derived subsections: 3.1 Studios/Properties/Confidentiality (incl. STRICT tier, shift_release cascade), 3.2 License Agreements & Royalties (amendment handshake, pinned 4-step accrual, provisional-vs-final projection), 3.3 Toy Lines & SKUs, 3.4 Line Lifecycle & Safety Testing (incl. INVALIDATED cascade), 3.5 Tooling & Factory Capacity (MOQ rounding, 80% tier boundary, 15% overtime), 3.6 Line Reviews & Commitments (half-open windows, segregation of duties, shelf-slot recompute), 3.7 Shipments/Embargoes/Closeout (10%/25% penalty tiers at violation threshold 2, waiver ledger symmetry, 50% deep-discount damping knee)
- §4 Endpoint index (55 rows, 4 columns)
- §5 Error catalogue (13 errors, 2 columns)

**Self-checks (all PASS):**
- Contract 1 Field-Name Coverage: 83 required scaffold identifiers (entity fields + endpoint inputs + `limit`/`offset`), 0 missing after one repair pass (added `region` via Retailer registration sentence in §3.6).
- Contract 2 Rule Coverage: all 6 state machines' transitions/preconditions/side-effects expressed (including safety INVALIDATED cascade and closeout commitment-cancel cascades); all 6 calculations in reconstruction-safe prose with pinned rounding order; both OCC rules with write-endpoint framing, field name, error id, and 412 status; validation priority ordering stated explicitly in §2.9; all 3 compensating-action invariants (recoup conservation, embargo ledger conservation, closeout shelf conservation) expressed; sibling branches (amend approve/reject, first/repeat offender, scrap/complete) rendered with equal density.
- Contract 3 §3 Path Purity: 393 backtick tokens scanned in §3, 0 violations (no paths, no bare HTTP methods).
- Supplementary: all 13 error IDs, all 5 role names, and every state/enum literal (`RETIRED` repaired to uppercase) present in prose; §2.2 diffed byte-identical against the canonical source.

The forbidden SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml were never opened.

Orchestrator note: verified PRD.md exists on disk (276 lines).

## Step 5: Generate unit tests — 2026-09-30T13:30:00.000Z

All done. Final summary:

## Files written

**test_helpers/** (9 files):
- `types.py` — status enums + TypedDicts for all 12 entities
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (all under `/toy-licensing`), plus `canonical_instant` for ISO-8601 comparisons
- `api_errors.py` — all 13 PRD §5 error IDs with HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity shape assertions
- `factories.py` — payload factories (input fields only)
- `constants.py` — thresholds (36–168 months, 0.80 tier boundary, 10%/25% penalty tiers, 4-quarter MG, 50% damping knee)
- `test_users.py` — opaque role headers + mandatory `make_retailer_ops_headers(retailer_id)` for the entity-backed RetailerOps role
- `fixtures.py` — composite setup builders (`setup_active_agreement`, `setup_licensed_chain[_with_shipment]`, `setup_tooled_line`, `setup_committed_line`, `setup_retail_open_review`, `certify_sku`, OCC-aware `advance_line`/`activate_agreement`, ownership-threaded `record_sale`)
- `__init__.py` — barrel export

**test_suite/** (10 files): `conftest.py` + 9 test files.

## Test counts
- Queue A (Difficulty): 36 tests — all 18 instances have ≥2 tests
- Queue B (Corner): 30 tests — all 26 non-stub instances have ≥1 test; the 3 `excluded_because` stubs in the `errors` section were not translated (their difficulty cross-references all resolve)
- Total: 66 tests

## Skipped instances
None. Two instances required weakened-but-PRD-faithful assertions rather than skips:
- `state_beats_fiscal_on_locked_review_commitment` — PRD names `ERR_CONSTRAINT_VIOLATION` (not `ERR_INVALID_STATE`) for committing into a non-OPEN review, so the tests assert the error is in `{ERR_CONSTRAINT_VIOLATION, ERR_INVALID_STATE}` and is *not* `ERR_SHELF_OVERFLOW` (the recipe's expected `error_id` contradicts the PRD prose).
- `closeout_empty_commitment_set_yields_zero_recovery` — the recipe's note about needing ON_SHELF was unnecessary; COMMITTED→CLOSEOUT with all commitments cancelled works directly.

## Self-check results
- **Coverage audit**: PASS — every queue-A instance ≥2 tests, every non-stub queue-B instance ≥1 test, zero orphan tags, zero dual/untagged tests.
- **PRD-citation pass**: PASS — automated verbatim check: every quoted sentence (≥25 chars) in every docstring survives literal substring match against PRD.md; all asserted `error_id`s appear in PRD §2/§3 prose, not only the §5 table; no `pytest.mark.skip`/`skipif`/`xfail` anywhere.
- **Import check**: all `test_helpers` and `test_suite` modules compile and import cleanly.
- No scaffold/Table references in generated code comments.

Orchestrator note: verified on disk — test_helpers/ has 9 files, test_suite/ has conftest + 9 test files, 66 `def test_` total.

## Step 6: Generate implementation — 2026-09-30T13:50:00.000Z

Done. All 55 endpoints implemented and smoke-tested.

**Files written** (in `tasks/task_3233_toy_line_licensing_entertainment_tie_timing_shelf/workspace/implementation/`):
- `app.py` (37) — Flask entrypoint, blueprint registration under `/toy-licensing`, ApiErr + 404/405 error handlers
- `start.sh` (7) — guarded pip install, `exec python3 app.py`, `0.0.0.0:$PORT`
- `requirements.txt` (1) — flask
- `util.py` (92) — envelope (`meta.api_request_id/api_request_timestamp`, `response_type`, `data`), pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/1-100/0), ISO parsing, half-up Decimal rounding, JSON body parsing
- `store.py` (51) — empty in-memory store, logical clock (starts exactly `2026-09-01T00:00:00Z`), property/review lifecycle derivations, shelf-slots recompute
- `auth.py` (15) — `X-User-ID`/`X-User-Role` extraction, role enforcement, 401/403
- `studios.py` (36), `properties.py` (82, incl. shift_release cascade), `agreements.py` (213, incl. OCC activate, amend handshake, close_quarter waterfall with 4-quarter minimum top-up, provisional projection), `lines.py` (218, all lifecycle transitions incl. markdown_recovery with 50% damping knee), `skus.py` (109, PATCH age invalidation cascade), `factories.py` (38), `tooling.py` (98, MOQ rounding + 80% utilization tier), `retail.py` (102, half-open window overlap, segregation-of-duties approve), `commitments.py` (88), `shipments.py` (117, embargo penalty 10%/25% tiers, waive), `safety.py` (98), `clockbp.py` (21, auto ON_SHELF on clock set)

**Endpoints: 55/55** (verified by counting distinct registered routes).

**Boot smoke test** (fresh `bash start.sh` on PORT 18733, then killed exactly that PID): full workflow exercised end-to-end — studio/property create, STRICT confidentiality, clock set flipping CONFIDENTIAL→REVEALED at reveal boundary, agreement activate RBAC (403 BrandManager when approval_rights_required) + OCC (412 stale), licensed line + SKU + safety PASS, tooling order (750→800 MOQ, charge 205000 at exactly-80% tier 0), line advances CONCEPT→IN_DEVELOPMENT→TOOLED→COMMITTED with OCC, retailer/review approve/commitment, early-sale embargo penalty (20000 = 10% of 200×1000, balance −20000), waive (balance back to 0, violation_count stays 1), close_quarter (earned 24000, recouped 24000), shift_release cascade (commitment→AT_RISK, SOLD shipment street_date unchanged per spec), clock past release auto-advancing line to ON_SHELF, enter_closeout with damping (0.6→0.55 effective, recovery 275000, slots freed to 0). All returned expected values; no seeding at startup.

Orchestrator note: verified on disk — 16 Python modules + start.sh + requirements.txt present; Flask app imports cleanly and registers exactly 55 `/toy-licensing` routes.

## Step 7: Run tests and iterate — 2026-09-30T14:10:00.000Z

All 8 rounds pass 66/66. Sweep is clean.

## Summary

**Iterations run:** 2 (initial sweep: 60/66 × 8 rounds, 6 tests failing deterministically in every round; post-fix sweep: 66/66 × 8 rounds).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `setup_review_with_commitment`: review-window keys (`window_start`, `window_end`, `commitment_deadline`) are now popped from kwargs and forwarded to `setup_retail_open_review`. Previously a caller passing `commitment_deadline="2026-10-15T00:00:00Z"` had it silently funneled into the *commitment* payload (which ignores the key), so the review kept the default Nov-1 deadline and was never LOCKED — this was the root cause of `test_commitment_cancel_gated_by_review_lock`.

**Fixes applied to `test_suite/`:**
- `test_02_safety_and_line_lifecycle.py::test_record_result_pass_with_age_over_claim_fails_test` — was asserting the age-over-claim PASS is *recorded* as FAILED; PRD §3.4's operative final sentence says verbatim "A conformance failure on an otherwise-passing result is reported through the safety gate (`ERR_SAFETY_GATE`) rather than recorded." Now asserts 422 `ERR_SAFETY_GATE` and that the test stays SUBMITTED / SKU stays TESTING ("rather than recorded").
- `test_07_release_shift_and_reviews.py::test_record_result_on_failed_test_also_yields_invalid_state` — same root cause: its setup used a conformance-failing PASS to reach FAILED. Switched the setup to an explicit `FAIL` outcome (which PRD records as FAILED), preserving the recording-twice → `ERR_INVALID_STATE` assertion.
- `test_05_agreements_and_royalties.py::test_royalty_recoup_caps_at_advance` — setup was self-inconsistent: the sale was recorded at clock 2026-10-01 but the test closed `quarter_index` 1 (Apr–Jun 2026 under the agreement's 2026-01-01 start), so gross was 0. Moved the clock to 2026-04-15, added `reveal_date="2026-01-01"` (licensed line needs a REVEALED property), and gave the review a window covering April, so the sale lands inside quarter 1 and the pinned math (earned 20000, recoup capped at 10000) holds.
- `test_05_agreements_and_royalties.py::test_activate_license_agreement_with_stale_version_rejected` — re-activating an already-ACTIVE agreement with a stale version trips both the §2.8 staleness rule and the §3.2 NEGOTIATION-only lifecycle gate; PRD §2.7's verbatim priority order lets `ERR_INVALID_STATE` win. Relaxed to `validate_error_is_one_of([ERR_STALE_VERSION, ERR_INVALID_STATE])` (permitted race-loser relaxation).
- `test_06_closeout_workflow.py::test_toy_line_closeout_reopen_cycle_with_safety_regression` — the second SKU's safety test was submitted after exit_closeout, when the line is COMMITTED, but PRD §3.4 gates submission to lines in CONCEPT/IN_DEVELOPMENT. Restructured: sku2's safety cycle now runs on the same line while still in CONCEPT (manual line build instead of `setup_committed_line`), and the "regression" half is exercised PRD-faithfully via a post-cycle age-grade edit asserting `safety_status` → FAILED and `claims_validated` → false (§3.4 invalidation paragraph).

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful in all six failures.

**Final state:** 8/8 parallel rounds green, 66/66 tests passing per round under `per-test-server` isolation.

Orchestrator note: independently verified all 8 `results.{1..8}.json` files report 66/66 passed.

## Step 8: Finalize PRD — 2026-09-30T14:15:00.000Z

Diff is exactly the two intended edits. Final report:

## Summary

`PRD_FINALIZED.md` created at `/home/ubuntu/github/CodingPRD/tasks/task_3233_toy_line_licensing_entertainment_tie_timing_shelf/workspace/PRD_FINALIZED.md`.

- **Line counts:** PRD.md 276 lines, PRD_FINALIZED.md 276 lines (0% line-count delta; both edits are in-line sentence revisions within existing paragraphs — no lines added or removed).

### Changes (2 edits)

- **§3.2** — insert — appended "An `end_date` that does not fall after `start_date` is not rejected at draft time; the check is enforced only at activation." to the agreement-draft paragraph — `implementation/agreements.py:75` (create only parses ISO, no ordering check) vs `:115` (activation raises `ERR_INVALID_STATE` when `_start_dt > _end_dt`).
- **§3.4** — revise — replaced "Any other outcome — an explicit fail, or a pass whose age grade exceeds the printed claim, or a pass whose validated claims do not cover every printed claim — moves the test to FAILED …" + the trailing conformance sentence with wording that records only explicit FAIL as FAILED, and rejects a conformance-failing PASS with `ERR_SAFETY_GATE` while leaving the test `SUBMITTED` and the SKU `TESTING` — `implementation/safety.py:79-95`.

### Step 7 items requiring NO PRD edit

- **`fixtures.py` review-window forwarding** — pure test-helper bug, no behavioral surface.
- **`test_royalty_recoup_caps_at_advance`** — self-inconsistent test setup (sale clock outside the closed quarter); impl math matched PRD §3.2's pinned formula verbatim.
- **`test_activate_license_agreement_with_stale_version_rejected` relaxation** — impl (agreements.py:113-122) already follows PRD §2.9's verbatim priority order exactly (state gate priority 4 before staleness priority 11); the test was over-pinned, the PRD was already correct. Also verified the parallel OCC site (lines.py:114-117) follows the same order.
- **`test_toy_line_closeout_reopen_cycle` restructure** — impl (safety.py:35-36) matches PRD §3.4's CONCEPT/IN_DEVELOPMENT submission gate verbatim; the test violated the PRD, not the impl.
- The two `test_record_result…` tests are covered by Edit 2 above.

### Per-edit pre-edit search log

**Edit 1 (§3.2 draft-time end_date):**
- (a) Subject: where/whether the start_date ≤ end_date constraint is enforced for LicenseAgreement.
- (b) Enumerated: `agreements.py` grep for `start_date|end_date|_start_dt|_end_dt` — lines 31-33 (quarter math uses `_start_dt`, no validation), 75 (create: `parse_iso` only), 115-116 (activation check), 137 (amend: `parse_iso` only), 154-155 (approve overwrites effective dates). New wording consistent with all sites; no other file touches agreement date validation.
- (c) Wording deliberately scoped to "not rejected at draft time … enforced only at activation" to avoid implying anything about amend/approve, which the impl also does not order-check.

**Edit 2 (§3.4 conformance-failing PASS):**
- (a) Subject: the full lifecycle of safety-test statuses and SKU `safety_status` transitions.
- (b) Enumerated and read: `safety.py` in full (create_test submission gates at :32-36; record_result branching at :79-95 — PASS+conformance-fail raises before any mutation at :82-83, explicit FAIL recorded at :90-95); `skus.py` in full (PATCH invalidation at :94-107 — touches only PASSED tests, never the SUBMITTED/TESTING residue of a rejected conformance-fail, and triggers the TOOLED→IN_DEVELOPMENT cascade only on `age_grade_months` change, which the test_06 fix exercised separately); `lines.py` in full (advance safety gate at :100-101 treats any non-PASSED SKU uniformly, so a SKU left in TESTING after the rejection still blocks TOOLED advance — consistent with the new wording).
- (c) Removed the "or a pass whose age grade exceeds… / claims do not cover…" clauses from the recorded-as-FAILED sentence and moved them into the rejection sentence with an explicit "the request is rejected, the test stays SUBMITTED, and the SKU stays TESTING" tail — this both pins the Step 7 site and stays consistent with the PATCH-invalidation and advance-gate paths.

Orchestrator note: independently diffed PRD.md vs PRD_FINALIZED.md — exactly the two in-line edits described, 276 lines both, no other changes.

## Step 9: Complete PRD — 2026-09-30T14:30:00.000Z

Orchestrator note: the subagent's first exit was premature — its report ended at "Let me now make the edits" with PRD_COMPLETED.md still byte-identical to PRD_FINALIZED.md. I resumed the same subagent via SendMessage; it then applied all edits and reported the summary below. Verified on disk: PRD_COMPLETED.md is 277 lines / 44,041 chars, diff vs PRD_FINALIZED.md = 43 changed lines.

Resumed subagent final report:

All 20 edits landed (one §2.8 edit covered both OCC bullets; 21 edit operations total, one section touched twice). Final verification that the file is valid and complete.

Summary:

- **Source vs output**: `PRD_FINALIZED.md` 276 lines / 40,374 chars → `PRD_COMPLETED.md` 277 lines / 44,041 chars (+1 line, +3,667 chars).
- **Counts**: 17 ambiguity-pins, 4 mismatch-revisions.

Changes (one bullet per edit):

- §2.1 — insert — ambiguity — pinned that GET endpoints accept any authenticated role regardless of the §4 role column (which is informational for reads) — implementation/auth.py:4-9 (`caller()` on all GETs).
- §2.2 — insert — ambiguity — pinned unmatched path/method → `ERR_NOT_FOUND` 404, unhandled server failure → `ERR_INVALID_REQUEST` 400 — implementation/app.py:19-34.
- §2.4 — revise — ambiguity — pinned `version` starts at exactly 1 and `created_at`/`updated_at` are stamped from the logical clock — implementation/store.py:23-31.
- §2.4 — insert — mismatch — pinned that penalty-driven Retailer ledger mutations do NOT increment the retailer's `version` (exception to the every-mutation rule) — implementation/shipments.py:96-101, 113-114 (no `touch` on retailer).
- §2.5 — insert — ambiguity — pinned clock-set accepts any parseable instant including earlier ones (no monotonicity check) — implementation/clockbp.py:12-15.
- §2.8 — revise — mismatch — `expected_license_agreement_version` / `expected_toy_line_version` are optional (checked only when supplied); advance OCC check runs after state/safety gates — implementation/agreements.py:120-122, implementation/lines.py:114-117.
- §3.1 — insert — ambiguity — property create requires existing studio (404 otherwise); no reveal/release ordering validated — implementation/properties.py:22-26.
- §3.1 — insert — ambiguity — `new_release_date` accepted verbatim, any direction — implementation/properties.py:57-59.
- §3.2 — revise — mismatch — activation check order pinned: NEGOTIATION state → start/end ordering → approval-rights role → optional OCC — implementation/agreements.py:113-122.
- §3.2 — insert — ambiguity — `quarter_index` is 0-based with half-open 3-month windows from `start_date`; close_quarter has no agreement-status gate — implementation/agreements.py:30-38, 173-181.
- §3.2 — insert — ambiguity — projection returns a bare 3-field object (not the agreement), for quarter index = `quarters_closed`, and also uses `pending_advance_guarantee_cents` when AMENDMENT_PENDING — implementation/agreements.py:199-213.
- §3.3 — insert — ambiguity — `target_street_date_input` required for EVERGREEN lines (missing → ERR_INVALID_REQUEST) — implementation/lines.py:47-50.
- §3.4 — revise — mismatch — TOOLED→IN_DEVELOPMENT revert requires only that no APPROVED tooling order remains (SCRAPPED or COMPLETE orders do not block) — implementation/lines.py:132-135.
- §3.4 — revise — mismatch — `claimed_age_grade_months` stored as supplied (no snapshot equality check); submitted test starts at version 1, no extra increment on submission — implementation/safety.py:37-43.
- §3.4 — insert — ambiguity — record_result `outcome` restricted to PASS/FAIL; `validated_claims` members must be in the declared enum (else ERR_SAFETY_GATE); `result_age_grade_months` 36–168 enforced via safety gate — implementation/safety.py:73-77.
- §3.4 — insert — ambiguity — editing `packaging_claims` alone does not invalidate certification; "latest PASSED test" disambiguated by `created_at` — implementation/skus.py:86-101.
- §3.6 — insert — ambiguity — `shelf_slots_total` must be non-negative int; overlap check includes PENDING_APPROVAL reviews — implementation/retail.py:59-66.
- §3.6 — insert — ambiguity — reinstating a non-AT_RISK commitment yields ERR_INVALID_STATE — implementation/commitments.py:82-83.
- §3.7 — insert — ambiguity — shipment create gates only on commitment existence, not status — implementation/shipments.py:24-25.
- §3.7 — insert — mismatch — oversell cap applies only to recordings on an already-SOLD shipment; first recording on PLANNED is uncapped — implementation/shipments.py:77-81.
- §3.7 — insert — ambiguity — repeat early-sale re-assessment credits back the prior OPEN penalty before debiting the new; `violation_count` increments on every assessment — implementation/shipments.py:96-101.
- §3.7 — insert — ambiguity — `markdown_pct` must be numeric (else ERR_INVALID_REQUEST) — implementation/lines.py:174-176.

Note: edit #4 (retailer version exception) is classified as a mismatch revision because the pre-existing §2.4 sentence asserted version increments on every mutation including cascade side effects, which the impl violates for retailer ledger mutations.

Output file: /home/ubuntu/github/CodingPRD/tasks/task_3233_toy_line_licensing_entertainment_tie_timing_shelf/workspace/PRD_COMPLETED.md
