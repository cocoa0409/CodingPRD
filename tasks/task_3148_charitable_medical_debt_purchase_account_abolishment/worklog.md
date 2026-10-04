# Worklog — task_3148_charitable_medical_debt_purchase_account_abolishment

## Step 1: Create Task Directory — 2026-09-30T04:26:00.000Z

Pre-allocated task directory `./tasks/task_3148_charitable_medical_debt_purchase_account_abolishment` with `workspace/` verified to exist (created externally per pipeline instructions); no new index computed, no other task_* directory created.

## Step 2: Generate Scaffold — 2026-09-30T05:18:00.000Z

Done. Scaffold generated for task_3148, maximal difficulty, clean lint.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3148_charitable_medical_debt_purchase_account_abolishment/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

**Counts:**
- Entities: 15 (SourceOrganization, EligibilityPolicy, Portfolio, DebtAccount, ScreeningRun, PurchaseContract, DonorCampaign, Donation, AbolishmentBatch, NotificationLetter, CreditDeletionRequest, TaxReliefRecord, HospitalPartnership, PartnershipMilestone, ImpactReport)
- State machines: 17 (DebtAccount carries 3 parallel dimensions; cyclic machines on Portfolio re-screen back-edge, letters, CDRs, partnership suspend/resume; branching with compensation on batches/contracts)
- Calculations: 8 (eligibility threshold, tiered pricing w/ org factor, per-donation rounding order, funding waterfall, dual-variant relief valuation, dual-variant impact counting, weighted FAP score, campaign funding threshold)
- Validations: 13 priority rows; Errors: 37; Endpoints: 81; Roles: 8 (segregation_of_duties role model: contract settler ≠ executor)
- §1.8 difficulty instances: 18 (2 per rule × 9 rules — all differentiation clauses honored: distinct entity domains, modes {a}/{b}, entities, triggers, category pairs, metrics/endpoints, entity pairs, interval semantics, conserved quantities)
- §1.9 corner instances: 43 active + 4 `excluded_because` stubs across all 9 guide sections

**Design highlights:** two OCC concurrency rules on `Portfolio.version` (contract create, batch create); depth-3 finalize cascade (batch → account ABOLISHED → auto-SUBMITTED CDR → bureau_status flip) vs depth-2 refund cascade (donation → raised recompute → FUNDED→OPEN revert); half-open policy windows vs closed report periods; logical-clock endpoint with pinned default 2026-09-01T00:00:00Z.

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (81 endpoints, 15 entities, 756 calls scanned). All pinned numeric literals were verified by executing the formulas (fees, tiered prices, FPL caps, FAP scores). No forbidden concurrency vocabulary.

## Step 3: Copy Shared Files — 2026-09-30T05:19:00.000Z

Copied `./INSTRUCTION.md` to `./tasks/task_3148_charitable_medical_debt_purchase_account_abolishment/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T05:26:00.000Z

All checks pass. Final report:

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3148_charitable_medical_debt_purchase_account_abolishment/workspace/PRD.md` — 372 lines.

**Sections covered:**
- §1 Introduction (3 paragraphs, multi-angle: system goals, constituencies, design commitments)
- §2 Global Specifications — 2.1 RBAC with per-role identity translation (opaque × 7, `entity_backed:SourceOrganization` for `HospitalPartner`), 2.2 verbatim fixed envelope block, 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), 2.4 Logical Clock (startup `2026-09-01T00:00:00Z`), 2.5 Common Resource Properties, 2.6 Monetary Precision (integer cents, round-half-up), 2.7 Validation Order (13-tier pipeline in priority order), 2.8 OCC (both `expected_portfolio_version` rules with `ERR_STALE_VERSION`/412), 2.9 Derived Totals & Cascades
- §3 Business Logic — 10 subsections (Sourcing, Eligibility, Pricing, Purchase, Donor Funding, Abolishment, Letters, Credit/Tax, Partnerships, Impact Reporting) with full scattering, no paths/methods
- §4 Endpoint table — all 81 endpoints, 4 columns only
- §5 Error catalogue — all 37 error IDs, 2 columns only

**Contract verification (all PASS):**
- **Contract 1 (Field-Name Coverage):** 106 required identifiers (all `entities[].fields[].name`, endpoint inputs, path params, query params, common fields) — 106 present, 0 missing. Fixed 4 during review (`accounts`, `campaign_id`, `partnership_id`, `status`).
- **Contract 2 (Rule Coverage):** All 13 validation tiers expressed with explicit priority ordering in §2.7; both OCC rules with write endpoint + `expected_portfolio_version` + `ERR_STALE_VERSION`/412; all 72 state-machine transitions covered in §3 narrative with preconditions, error IDs, and side-effect cascades (donation refund two-link cascade, batch finalize three-link cascade, batch reversal compensations); all 8 calculations in precise prose (FPL cap 15,650.00 + 5,560.00/member with round-half-up, tiered quote 1M/4M at 2.5%/1.5%/0.8% with org factors 1.0/0.9/0.75 and single final rounding, per-donation 2.9% fee round-then-sum with the 3,333-cent worked example, earmark waterfall ordering, provisional-vs-final relief valuation, per-account vs deduped household counting, weighted FAP score with zero-denominator fallback, campaign funding threshold with equality-is-funded); all 37 error IDs appear in §2/§3; sibling branches symmetric (re-screen flips, MISSED→MET late completion, reject at/below resubmission ceiling, assess ASSESSED vs EXEMPT).
- **Contract 3 (§3 Path Purity):** 544 backticked tokens scanned in §3 — 0 paths, 0 bare HTTP methods, 0 method+path combinations.

All 8 roles, all 14 entities (including common-fields note), all 17 state machines, all state/enum values (including `EMAIL` channel), and all 81 endpoints are represented.

## Step 5: Generate Unit Tests — 2026-09-30T05:52:00.000Z

Generation complete. Summary:

## Files written

**`test_helpers/`** (9 modules, all under `/home/ubuntu/github/CodingPRD/tasks/task_3148_charitable_medical_debt_purchase_account_abolishment/test_helpers/`):
- `types.py` — 15 entity TypedDicts + 20 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (59 endpoints incl. the logical clock)
- `api_errors.py` — 38 `ApiErrorId` members + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity field validators + common-fields checker
- `factories.py` — payload factories (input fields only)
- `constants.py` — FPL base/increment, tier schedule, ORG_FACTOR, FEE_PCT, letter/CDR ceilings, pagination defaults
- `test_users.py` — `TEST_USERS` shared constants + per-role `make_*_headers` builders (incl. `make_hospital_partner_headers` for the entity-backed role)
- `fixtures.py` — composite setup chain: `set_clock`, `create_org`, `create_active_policy`, `create_priced_portfolio`, `create_settled_portfolio`, `setup_standard_priced/settled`, `setup_funded_campaign`, `setup_committed_batch`, `setup_finalized_batch`, `stage_batch`
- `__init__.py` — barrel re-export of framework generics + PRD-specific code

**`test_suite/`**: `conftest.py` + 16 test files (`test_01_…` through `test_16_…`), 79 tests total, collected cleanly by pytest.

## Coverage
- **Queue A (Difficulty): 18/18 instances, exactly 2 tests each → 36 tests**
- **Queue B (Corner): 43/43 non-stub instances, 1 test each → 43 tests**
- The 4 `excluded_because` stubs (`impact_report_input_set_excludes_excluded_accounts`, `campaign_threshold_boundary_equality`, `finalize_cascade_creates_letters_tax_cdrs`, `raised_cents_reconciles_after_receive_and_refund`) were not translated; all four cross-references resolve to real difficulty instances.

## Skipped instances
None — every non-stub instance in both indices passed the PRD-first two-condition filter (verbatim PRD coverage + unique derivability).

## Verification performed
- `py_compile` passes on all files; pytest collects all 79 tests with no import errors.
- Programmatic audit: every test docstring ends with exactly one `Design:` tag; every tag resolves to a real non-stub instance `name:` in the source yamls; every design instance is referenced (no gaps, no orphans).
- Every PRD citation in every docstring survives a whitespace-normalized literal grep of `PRD.md` (0 failures; four initially-failing citations were rewritten to match the PRD text exactly).
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere; no "scaffold"/table references in generated code comments.

One note: `test_helpers/__init__.py` barrel initially omitted the `make_*_headers` builders; this was caught by pytest collection and fixed.

## Step 6: Generate Implementation — 2026-09-30T06:12:00.000Z

Implementation complete and verified.

## Summary

**Files written** under `/home/ubuntu/github/CodingPRD/tasks/task_3148_charitable_medical_debt_purchase_account_abolishment/workspace/implementation/`:

- `app.py` (~1,300 lines) — the entire Flask implementation
- `start.sh` — executable foreground launcher: `cd` to its own dir, guarded dep install (`pip install` only if `flask` import fails), `exec python3 app.py`
- `requirements.txt` — `flask`

**Endpoints implemented: 81 routes across 60 endpoint table entries** — the logical clock (`POST /_clock/set_current_utc`) plus all CRUD/list/transition endpoints for SourceOrganization, EligibilityPolicy, Portfolio, DebtAccount, ScreeningRun, PurchaseContract, DonorCampaign, Donation, AbolishmentBatch, NotificationLetter, CreditDeletionRequest, TaxReliefRecord, HospitalPartnership, PartnershipMilestone, and ImpactReport.

**Key fidelity points honored:**
- Envelope: `meta.api_request_id` (`req_`-prefixed) / `meta.api_request_timestamp` (ISO-8601 UTC, 3 fractional digits, logical clock), `response_type`, `data`; pagination fields (`limit`/`offset`/`total_count`/`has_more`) live in `meta`, list-only, defaults 10/0 with clamp 1..100.
- Logical clock boots at exactly `2026-09-01T00:00:00Z`, never wall-clock; all stamped timestamps (`executed_at`, `abolished_at`, `sent_at`) and the milestone due-date gate read from it.
- All monetary math in `Decimal` with `ROUND_HALF_UP`: FPL income cap, three-tier quote (tier math on face first, single rounding after org factor), per-donation fee (round-then-sum pinned — verified the 3333+3333 → 6472 example).
- Full validation pipeline ordering (request shape → auth → RBAC → path existence → body FKs → state → cross-entity gates → covenants → temporal windows → referential fit → domain constraints → money → OCC), with the scaffold's exact error IDs and HTTP codes (including `ERR_BATCH_EMPTY` 422, `ERR_INSUFFICIENT_FUNDING` 402, `ERR_STALE_VERSION` 412).
- All state machines with side effects: settle partitions accounts PURCHASED/EXCLUDED; finalize cascade creates letters/tax records/auto-SUBMITTED CDRs and flips `bureau_status`; reversal gates on irreversible artifacts and restores campaign/portfolio totals; portfolio auto-CLOSE; campaign OPEN↔FUNDED threshold with equality funded; letter 3-bounce ceiling; CDR 2-resubmission ceiling; FAP weighted score with WAIVED excluded from both numerator and denominator.
- OCC via `expected_portfolio_version` on the two named child-creation endpoints only.
- No seeding — store starts empty; everything built via the API surface.

**Boot verification:** `bash start.sh` runs in foreground, binds `0.0.0.0`, reads `$PORT` (tested on 17389/17390), responds within ~1.5s (well under the 60s limit), and a fresh restart showed an empty store with the default clock — clean for `--isolation per-test-server`. A 74-assertion end-to-end smoke run (clock, auth, orgs, policy windows, import atomicity, screening, quote math, contract OCC/SoD/covenants, waterfall earmark ordering, finalize cascade, letters/CDR/tax lifecycles, partnership FAP gates, impact report variants and closed-interval overlap) passed with zero failures. Both test servers were killed afterward (PIDs verified by `/proc/<pid>/cwd` match before killing).

## Step 7: Run Tests and Iterate — 2026-09-30T06:27:00.000Z

All 8 rounds pass 79/79. Clean sweep.

Summary:
- Iterations run: 3 (three 8-round parallel sweeps; the first identified the failures, the second verified the implementation fix, the third verified the test fix — final sweep is 8× 79/79).
- Tests deleted: none.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `test_suite/`:
  - `test_03_calculations.py` — `TestFundingWaterfall.test_waterfall_draws_earmarked_classes_in_order`: the test's own arithmetic was wrong. PRD pins the per-donation fee at `round_half_up(gross × 0.029)`; for gross 514933 the fee is `round_half_up(14933.057) = 14933`, so net is 500000 (not 14934 → 499999 as the test's comment assumed, requiring a 2-cent top-up to reach 500001). Removed the erroneous top-up donation and corrected the asserted `raised_cents` to 500000, making the test faithful to PRD §"each donation's economics are computed per donation".
- Fixes applied to `implementation/`:
  - `app.py` — `create_donation`: reordered validation to honor PRD §2.7's tier pipeline (tier 1 request shape → tier 2 auth → tier 3 role → tier 4 path existence). Previously the campaign path lookup (`get_res("campaigns", cid)` → 404 `ERR_NOT_FOUND`) ran before the body-shape checks (`req_str`/`req_int` → 400 `ERR_INVALID_REQUEST`), so a malformed body against a non-existent campaign id surfaced `ERR_NOT_FOUND` instead of the PRD-mandated `ERR_INVALID_REQUEST`. Body field extraction now precedes the path-resource lookup. No PRD-required check was removed or weakened.

Files touched:
- /home/ubuntu/github/CodingPRD/tasks/task_3148_charitable_medical_debt_purchase_account_abolishment/workspace/implementation/app.py
- /home/ubuntu/github/CodingPRD/tasks/task_3148_charitable_medical_debt_purchase_account_abolishment/test_suite/test_03_calculations.py

## Step 8: Finalize PRD — 2026-09-30T06:31:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_3148_charitable_medical_debt_purchase_account_abolishment/workspace/PRD_FINALIZED.md` produced as a byte-identical copy of PRD.md (372 lines each, 0% delta) — **zero edits were warranted**.

**Analysis of the two `<step_7_diff>` items:**

1. **Test-suite fix** — `test_03_calculations.py::TestFundingWaterfall.test_waterfall_draws_earmarked_classes_in_order`: pure fixture arithmetic bug. PRD §3.5 already pins the fee as `round_half_up(gross × 0.029)` per donation ("the fee is rounded per donation, and only then are nets summed into campaign totals"), and §2.6 pins half-up rounding "at exactly the point the governing calculation specifies." For gross 514933, fee = 14933, net = 500000 — exactly what the PRD determines. The test's own comment assumed 14934; nothing in the PRD was silent or wrong. **No edit.**

2. **Implementation fix** — `app.py::create_donation` validation reorder (impl file lines 1146–1157): the implementation was changed to *conform to* PRD §2.7, which already pins tier 1 request-shape (`ERR_INVALID_REQUEST`, 400) strictly before tier 4 path existence (`ERR_NOT_FOUND`, 404), with the worked example "a malformed body surfaces as `ERR_INVALID_REQUEST` even if the caller is also unauthorized." The PRD already determines this behavior uniquely; the implementation was the divergent side and was fixed. **No edit.**

**Pre-edit search log** (no edits were committed, but the verification searches were still performed for both candidate subjects):

- (a) Subject: per-donation fee rounding. (b) Paths enumerated: `app.py:38` (`FEE_PCT = Decimal("0.029")`), `app.py:1158` (per-donation `ROUND_HALF_UP` quantize), `app.py:1186–1224` (`_campaign_threshold_update`, `receive_donation`, `refund_donation` — net-summing into `raised_cents`), plus PRD §2.6 and §3.5 wording. (c) No edit — PRD wording already matches all enumerated impl paths exactly.
- (a) Subject: validation ordering (request shape vs path existence). (b) Paths enumerated: `create_donation` (1145–1168: `get_body`→`auth`→`require_role`→`req_str`/`req_int`→`get_res`), `create_screening_run` (839–864), `create_contract` (950–974), `create_batch` (1231–1281), `create_cdr` (1619–1640), `create_milestone` (1902–1930); helpers `get_body`/`auth`/`require_role`/`req_str`/`req_int`/`get_res` (200–284, 370). (c) No edit — PRD §2.7's 13-tier pipeline plus the earliest-tier rule sentence already describes the behavior of every enumerated path, including the fixed `create_donation` order; any additional wording would risk the NO-NEW-MISMATCH failure mode (e.g., other endpoints like `create_batch` legitimately interleave body checks with path-resource checks in ways §2.7's tier list already covers).

A fresh implementer reading PRD.md (= PRD_FINALIZED.md) already produces the current implementation's behavior on both Step 7 sites, so the minimal correct patch is the empty patch.

## Step 9: Complete PRD — 2026-09-30T06:45:00.000Z

Done. PRD_COMPLETED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_3148_charitable_medical_debt_purchase_account_abolishment/workspace/PRD_COMPLETED.md`.

**Source vs output:** `PRD_FINALIZED.md` (source) — 372 lines / 56,070 chars; `PRD_COMPLETED.md` — 372 lines / 59,564 chars (char-delta +3,494; all changes are in-paragraph inserts/revisions, no new sections).

**Counts:** 11 ambiguity-pins, 2 mismatch-revisions (13 changed passages total).

Changes (PRD section — insert|revise — ambiguity|mismatch — what changed — impl file:line):

- §2.3 Pagination — insert — ambiguity — pinned invalid limit/offset → `ERR_INVALID_REQUEST` (400), exact per-endpoint filter sets (all exact-match), `created_at` ties broken by creation order, and `has_more` = `offset + limit < total_count` — app.py:377-409, 485-489, 560-563, 647-650, 809-815, 876-880, 986-989, 1125-1129, 1180-1183, 1293-1296, 1542-1546, 1652-1656, 1752-1755, 1832-1835, 1942-1945, 2089-2093.
- §2.4 Logical Clock — revise — mismatch — startup reading pinned as `2026-09-01T00:00:00.000Z` (PRD said `...T00:00:00Z`); `to_iso8601` accepts any ISO 8601 offset, normalizes to UTC, and is not constrained to the future — app.py:22, 433-448.
- §2.9 Derived Totals — revise — mismatch — portfolio version-bump list extended with batch creation, finalization, and reversal; uncommit explicitly does not touch the portfolio — app.py:1280, 1365, 1459, 1525 (uncommit: 1369-1384).
- §3.1 Account import — insert — ambiguity — successful bulk import returns 201 with `response_type` "array" and no pagination fields in `meta` — app.py:787, 790-793.
- §3.2 Screening run — insert — ambiguity — run born with all three counts zero and `executed_at` unset; execution re-validates the policy is still ACTIVE (`ERR_POLICY_NOT_ACTIVE` if retired after creation) — app.py:853-861, 893-894.
- §3.4 Contract execution — revise — mismatch — check order pinned: covenant check (`ERR_COLLECTION_COVENANT_MISSING`) precedes the price-drift comparison (`ERR_PRICE_DRIFT`) — app.py:1003-1008.
- §3.5 Campaigns — insert — ambiguity — receiving/refunding a donation on a CLOSED campaign still adjusts `raised_cents` but the threshold flip never changes a CLOSED campaign's status — app.py:1186-1190, 1193-1224.
- §3.5 Campaign earmarks — revise — mismatch — hospital-earmark check order pinned as suspended (`ERR_EARMARK_TARGET_SUSPENDED`) before org-type (`ERR_EARMARK_TARGET_NOT_HOSPITAL`); earmark field-shape violations pinned as `ERR_INVALID_REQUEST` (400) — app.py:1079-1100.
- §3.5 Waterfall — insert — ambiguity — `created_at` ties broken by creation order; non-positive uncommitted balance skipped; `funding_allocations` elements are `{"campaign_id", "amount_cents"}` objects — app.py:1319-1331, 1355-1357.
- §3.6 Batch creation — insert — ambiguity — pinned per-endpoint check order overriding §2.7 tiers: non-empty → account existence → portfolio state → same-portfolio → PURCHASED → version — app.py:1242-1268.
- §3.6 Finalize cascade — insert — ambiguity — auto-created deletion request records the account's `bureau_name` as its `bureau` — app.py:1424.
- §3.7 Letters — revise — ambiguity — cascade always creates letters with `channel` `MAIL` (PRD admitted MAIL-or-EMAIL); `mailing_address` snapshot may be absent — app.py:1430-1438.
- §3.8 Tax records — insert — ambiguity — record born with `insolvency_exclusion_cents` and `reportable_amount_cents` unset until assessment — app.py:1439-1445.
- §3.9 Milestones — insert — ambiguity — creation permitted in any partnership status (suspension blocks only mark-met/mark-missed/waive), creation recomputes `fap_current_score` and bumps the partnership, HospitalPartner creator identity check (`ERR_FORBIDDEN`), code uniqueness checked across all milestones regardless of status — app.py:1902-1930, 1928-1929.
- §3.10 Impact reports — insert — ambiguity — hospital-scope `scope_source_org_id` must resolve to an existing organization (`ERR_SOURCE_ORG_NOT_FOUND`); unused scope-key fields must be absent (`ERR_INVALID_REQUEST`) — app.py:2025-2040.
