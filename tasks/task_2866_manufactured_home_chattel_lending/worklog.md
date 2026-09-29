# Worklog — task_2866_manufactured_home_chattel_lending

## Step 1: Create task directory — 2026-09-05T08:21:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2866_manufactured_home_chattel_lending` and its `workspace/` subdirectory. Index 2866 was pre-assigned by the orchestrating caller; no scan of `./tasks/` was performed (concurrent pipelines on this host would collide on auto-allocation).

## Step 2: Generate scaffold — 2026-09-05T10:25:00.000Z

All three scaffold artifacts are complete and the task directory passes the linter.

**Lint verdict (verbatim, final run):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2866_manufactured_home_chattel_lending/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2866_manufactured_home_chattel_lending/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2866_manufactured_home_chattel_lending/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    49
  §1.1 entities declared:     10
  §1.8 instances scanned:     18
  §1.9 instances scanned:     50
  Calls scanned (§1.8+§1.9):  828

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Deliverables**
- `SCAFFOLD.yaml` — 2796 lines. Top-level keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles. Confirmed to contain **no** `scaffold_difficulty_design` / `scaffold_corner_design` keys.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1797 lines, exactly one top-level key, 18 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3125 lines, exactly one top-level key, nine sections in guide order (entities 12, state_machines 13, calculations 11, validations 22, endpoints 5, errors 2, rbac 4, cross_cutting_complexity_layers 5, consistency_model 1) = 75 instances: 50 real `test_recipe`s + 25 `excluded_because` stubs that cite §1.8 instances. All three files end at real structural boundaries and parse cleanly.

**Shape of the domain**: api_prefix `/chattel`; 10 entities; 49 endpoints; 48 validations; 55 errors; 7 roles; complexity_profile = expert / workflow_orchestration + pricing_engine / layers [optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers] / flat topology / branching state machines / segregation_of_duties / immediate consistency. Two `concurrency_rules` (`valuation-create-stale-unit` with `expected_unit_version` → ERR_STALE_UNIT_VERSION 412; `policy-create-stale-loan` with `expected_loan_version` → ERR_STALE_LOAN_VERSION 412), each with its own OCC instance.

**Coverage checks I ran beyond the linter**
- **Error triggerability: 55/55.** Driven mechanically — 36 uncovered after the calculations section, 7 after validations/endpoints, `missing []` after adding the `errors` section.
- **Instance-name uniqueness:** 75 + 18 across both design files, no duplicates.
- **Every numeric literal recomputed** with `Decimal(...).quantize(ROUND_HALF_UP)` against the §1.4 formulas (valuations, APR stacks, term clamps, required coverage, accruals, payoff and its off-by-one-cent refusal boundary). All matched.

**Disclosures the caller should see**
1. **The directive line was deliberately excluded from `scenario:`.** The scenario prose starts at "Manufactured Home Chattel Lending (21st Mortgage): ..." — "Generate task harder than expert level!" is not in the file, so it cannot leak into a generated PRD.md. Verified: `'harder' in scenario` is `False`.
2. **Count overage against the Expert guideline band:** 49 endpoints (band 20–32) and 55 errors (band 18–30). Accepted deliberately — 17 of the endpoints are read endpoints mandated by lint check (f) FK reverse-reachability, and §0.4 states the bands are guidelines.
3. **Fixes applied to SCAFFOLD.yaml** (earlier in the pipeline): `ERR_CLASSIFICATION_PATH_MISMATCH` moved from priority 59 to 25 so it is actually reachable rather than shadowed; validation p44 scoped to `source == BORROWER_PROVIDED`; two default-declaring side effects added on `POST /chattel/communities` and `POST /chattel/loans/{loan_id}/fund`.
4. **§1.8 corrections** (earlier): four HTTP codes 422→409; `insurance_state`→`insurance_compliance`; `servicing_state == null`→`NOT_SERVICING`; unit `.collateral_classification`→`.classification`.
5. **Two §1.9 content bugs found and fixed this session** — both would have made the recipe assert something the scaffold cannot produce:
   - `lot_rent_state: "IN_ARREARS"` was an undeclared enum member (real set is {CURRENT, DELINQUENT, EVICTION_FILED}); left alone it would have tripped p6 ERR_INVALID_REQUEST instead of the intended p30 ERR_LOAN_SERVICING_INVALID_STATE. Changed to `"DELINQUENT"`.
   - An invented location key and value: `location_key == PRIVATE_LAND_OWNED and certified_value_cents == 5947653`. The declared key is `PRIVATE_LAND` (900 bps) and the correct total is 5365440 + 482890 + 250000 = **6098330**.
6. **No sibling task directory was read, listed, globbed or grepped** at any point; the scaffold came only from the scenario text and the generator skill's own spec plus `references/claim-extraction-guide.md`. Scratch was confined to `/tmp/task_2866_scratch/`. Nothing outside the three output paths was created, modified or deleted.

**Orchestrator note:** verified independently that `grep -n "harder than expert\|expert level" SCAFFOLD.yaml` returns no match, so the difficulty directive cannot reach PRD.md via the scaffold.

## Step 3: Copy shared files — 2026-09-05T10:26:00.000Z

Copied `INSTRUCTION.md` from the project root to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T10:41:00.000Z

The PRD is complete and verified. Final state of `workspace/PRD.md`: **468 lines, 13,121 words**, built via 12 incremental appends (no truncation).

## Structure
- **§1 Introduction** — 3 paragraphs; personal-property-vs-real-property collateral framing; API mounted under `/chattel`.
- **§2 Global Specifications** — 11 subsections: 2.1 Actors and RBAC (all 7 roles, opaque vs entity-backed identity) · 2.2 API Response Structure (**verified byte-identical to `section-2.2-response-structure.md` via diff**) · 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending) · 2.4 The Logical Clock (`2026-08-01T00:00:00Z`, forward-only) · 2.5 Resource Identity, Audit Fields and Versioning (incl. the two entities carrying only `id`+`created_at`) · 2.6 Path and Foreign-Key Resolution Order (all 10 not-found codes) · 2.7 Validation Precedence (full priority ladder) · 2.8 Integer Cents, Basis Points and Rounding · 2.9 Stale-Read Protection (both OCC rules, 412) · 2.10 Cross-Entity Cascade Integrity · 2.11 Segregation of Duties.
- **§3 Business Logic & Workflows** — 9 subsections covering reference data, collateral registration, dual-variant valuation, origination/pricing/funding, lien perfection with the rejection cycle, hazard coverage and force-placement, servicing/accrual/waterfall/delinquency, classification conversion, and default/enforcement/remarketing.
- **§4 Endpoint Definitions** — 4-column table, **49 rows** (count verified).
- **§5 Error Code Catalogue** — 2-column table, **55 rows** (count verified). File ends here with no audit footer.

## Hard Contract Reports

**Contract 1 — Field-Name Coverage: PASS**
| Category | Required | Present | Missing |
|---|---|---|---|
| Entity fields | 136 | 136 | 0 |
| Endpoint request-body params | 73 | 73 | 0 |
| Query params | 22 | 22 | 0 |
| Path params | 10 | 10 | 0 |

**Contract 2 — Rule Coverage: PASS** — All 48 validations, all state machines (incl. the cyclic LienFiling and classification cycles and the forking RecoveryCase), all 8 calculations, both concurrency rules and all cascade rules are stated in §2/§3. All 55 error IDs appear in §2 or §3 prose (not just §5). All state enum values and enum-typed field values appear verbatim. One gap found and repaired: §3.4's submit-underwriting paragraph named the valuation inputs but not `ERR_VALUATION_VARIANT_MISMATCH` (validation priority 36) — prose extended to state the three failure conditions and the error.

**Contract 3 — §3 Path Purity: PASS** — 921 backtick tokens scanned in §3: 0 begin with `/`, 0 are bare HTTP-method tokens, 0 combine method+path. All endpoint addressing lives in §4 only.

## Notes for downstream steps
- Zero fuzzy quantifiers (`approximately`, `roughly`, `conservatively`, …) and zero pseudocode operators (`+=`, `==`, `min(`, `round_half_up(`, …) in the prose — greps returned none.
- One deliberate non-invention: the `COMPLETE` conversion precondition "no LienFiling on this unit is in `SUBMITTED`" has no `error_id` anywhere in the scaffold, so it is stated as a precondition in prose without a fabricated code.
- Reconciled a scaffold tension on `lot_rent_months_delinquent`: the enum has no `CURED` member, so prose says a report returning standing to `CURRENT` with zero months clears the counter to 0.
- Neither withheld design YAML was opened, `worklog.md` was untouched, and nothing outside the output path (plus `/tmp/task_2866_prd_scratch/`) was written.

**Orchestrator truncation check:** `tail -25 PRD.md` ends on a complete §5 error-table row (`| ERR_LENDER_ACCESS_NOT_GRANTED | 409 |`) — a real section boundary, not mid-sentence. No regeneration needed. Independent grep confirms PRD.md contains no occurrence of "harder than expert", "expert level", or "scaffold".

## Step 6: Generate implementation — 2026-09-05T11:20:00.000Z

Implementation complete and smoke-verified.

## Deliverable
`workspace/implementation/` — 17 Python modules (~2,700 lines), `requirements.txt` (`Flask>=2.0`), and an executable `start.sh` that reads `$PORT`, binds `0.0.0.0`, and `exec`s `python3 app.py` in the foreground (installing Flask only if missing, to avoid boot contention under the concurrent per-test reboots).

Layout: `app.py` (blueprint wiring + `ApiError`/404/405/500 handlers), `core.py` (logical clock, ISO/instant helpers, calendar-day math, `round_half_up`), `errors.py` (all 55 error ids -> statuses), `store.py` (10 in-memory dicts, versioning/serialization), `envelope.py`, `shape.py`, `security.py` (7 roles, ownership scoping, list narrowing), `constants.py` (every enum and pinned constant), `domain.py` (valuation walk, pricing, insurance matrix, accrual/waterfall, settlement, exposure), and 8 `routes_*.py` modules.

## Contract conformance checks (mechanical)
- **Endpoints: 49/49.** Diffing the PRD §4 table against `app.url_map` gives zero missing and zero extra routes.
- **Errors: 55/55 ids, zero HTTP-status mismatches** against the PRD §5 table; every `ApiError(...)` id raised anywhere in the code appears in the PRD.
- **Storage:** Python dicts only; a fresh boot returns `total_count=0` on all seven list endpoints — no seeding anywhere.

## Smoke testing (4 passes, server on port 28660, killed by recorded PID each time)
All passes ended with 0 failures. Every mismatch I hit was my test script's wrong guess, each re-verified against the PRD as implementation-correct: `ERR_FILING_DOCUMENTS_INCOMPLETE` (not `ERR_DOCUMENTS_INCOMPLETE`), field `attempt_number` (not `attempt_count`), `ERR_NOT_RESOURCE_OWNER` for borrower scope, `ERR_EXPOSURE_CAP_EXCEEDED` = 422, and 405 on `GET /borrowers|/communities|/book-value-guides` (the PRD declares no list endpoints for those three).

Covered: full chattel happy path (guide -> borrower -> community + operator agreement -> unit -> valuation/certify -> loan -> underwrite -> approve -> filing -> agency RECORDED -> policy -> fund -> payment -> reversal -> assessment -> force-place -> default -> notice -> possession -> liquidation valuation -> refurbishment -> resale -> settlement) with `CLOSED_DEFICIENCY`, commission 550+250=800 bps, and borrower exposure returning to 0; the real-property branch (private land -> deed/affidavit -> INITIATE/COMPLETE conversion -> lien released, loan `RE_PERFECTION_REQUIRED` -> deed-of-trust filing -> `PERFECTED`, `REAL_PROPERTY_ESCROW_FIRST` allocation, exact payoff); caps and gates (LTV, term floor, exposure cap, SoD, borrower suspension, lot-occupancy 7-day buffer, filing attempt limit, agreement termination blocking funding, all three funding insurance gates, recovery-hold gating); lot-rent acceleration (default refused at 40 days, allowed after the operator reports 3 months); force-placed premium 429,585 -> pro-rata refund 404,869 leaving 24,716 outstanding; the foreclosure arm (`REDEMPTION_WINDOW`, possession refused while open, timely redemption restoring the loan to `CURRENT` and the borrower to `ACTIVE`); and envelope/pagination/RBAC negatives.

## Documented ambiguity resolutions
- `api_request_timestamp` is drawn from the logical clock, per "nothing in this platform reads wall-clock time."
- A `PAYOFF` row records `to_escrow_cents` as the negative escrow refund so the five allocations sum exactly to `amount_cents` while every bucket zeroes (the PRD specifies the balance effect but not the row's escrow field).
- Recovery settlement zeroes only the four obligation buckets the PRD names; `escrow_balance_cents` is left alone.
- Enum-valued list filters with an undeclared value return `ERR_INVALID_REQUEST`; missing conditional placement fields return `ERR_PLACEMENT_FIELDS_INCONSISTENT`; a `COMPLETE` conversion blocked by a SUBMITTED filing returns `ERR_FILING_INVALID_STATE`.

Nothing outside the `implementation/` directory was created or modified; scratch stayed in `/tmp/task_2866_impl_scratch/`, and no server processes remain on port 28660.

## Step 5: Generate unit tests — 2026-09-05T12:50:00.000Z

Stage 1 and Stage 2 are complete for `task_2866_manufactured_home_chattel_lending`.

## Output (task root, nothing under `workspace/`)
- `test_helpers/` — `__init__.py` (barrel), `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`
- `test_suite/` — `conftest.py` plus 16 test modules, **90 tests collected** (`pytest --collect-only` clean in 0.59s)

`ls workspace/` shows only `INSTRUCTION.md`, `PRD.md`, `implementation` — no test dirs leaked, no `__pycache__` left behind, and I never wrote to `worklog.md`, `PRD.md`, `SCAFFOLD*.yaml` or `implementation/`.

## Design-index coverage
- **Queue A (difficulty): 18/18 live instances covered**, 41 tests, every rule id carrying 4–6 tests (>=2 per instance).
- **Queue B (corner): 49 tests over 49 of the 50 live instances**; all 25 stub instances correctly left untranslated.
- Tag hygiene verified mechanically: exactly one `Design:` line per test, always the last docstring line, no orphan tags, no `skip`/`skipif`/`xfail`, no mention of the scaffold in any docstring or comment.
- Citation verifier: `tests=90 files=16 failures=0` (every C1 quote survives a literal grep of `PRD.md`).

## The one deliberate skip
`Corner/entities/create_unit_rejects_client_supplied_system_field_classification` — skipped under the PRD-first filter. No PRD rule governs undeclared or platform-managed keys arriving in a request body: §2.7's shape layer enumerates only missing required fields, non-member enum values, out-of-range `_cents`/`_bps` amounts, unparseable ISO dates and pagination bounds. §2.9 actively points the other way — "supplying a version field where none is specified does not create a concurrency check" — so the asserted 422 is not uniquely derivable. Gap left as a gap.

## Last file written this session
`test_suite/test_16_cross_cutting_layers.py` (436 lines, 3 tests): the `expected_unit_version` guard forcing a re-read between back-to-back valuations (412, then retry supersedes with the frozen value intact); `expected_loan_version` beating an inverted coverage interval to the punch (412 `ERR_STALE_LOAN_VERSION` rather than 422, proving the §2.7 ladder order, then a 201 `ACTIVE`/`BORROWER_PROVIDED`/`COMPLIANT` policy whose `required_coverage_cents` is derived relationally from the valuation's own certified value); and lot-rent arrears pulling the 60-day personal-property default threshold down to 30 at two months behind (409 `ERR_DEFAULT_NOT_ELIGIBLE` at one month, 201 `REPOSSESSION` case seeded at 185,000 cents at two, with the ledger untouched at 98,018 interest / 3,500 fees).

## Conflicts resolved PRD-first (yaml overruled)
`SUBMITTED`->`UNDERWRITING` (§3.4), `PROPOSED`->`PENDING` (§3.1), `ERR_OPERATOR_AGREEMENT_MISSING`/`ERR_LAND_DOCUMENTS_INCOMPLETE` are 409 not 422, and the yaml's asserted list reads for borrowers/guides/communities were dropped because those entities have GET-by-id only — replaced with grounded substitutes (clock-echo proof, filtered list `total_count`). Every yaml-precomputed money figure was re-derived from §3 before use; the piered-vs-permanent foundation mismatch in the yaml's 6,098,330 pin was reconciled by threading `PIER_AND_ANCHOR` unit overrides.

**Orchestrator verification:** `ls workspace/` shows only INSTRUCTION.md, PRD.md, implementation — `find workspace -name test_suite -o -name test_helpers` returns nothing, so neither test directory drifted under workspace/. Independent `pytest test_suite --collect-only -q` confirms 90 tests collected with no collection errors.

## Step 7: Run tests and iterate — 2026-09-05T13:12:00.000Z

All 8 rounds are fully green — 90/90 passed in every round, 0 failures, 0 errors.

## Summary

**Iterations run:** 2 (one diagnostic sweep, one verification sweep).

**Tests deleted:** none. Both defects were test-artifact bugs, not PRD-coverage problems — every failing test's asserted rule traces verbatim to PRD prose and is uniquely derivable, so all 90 tests survive.

**Fixes applied to `test_suite/`:**

- `test_suite/test_14_validations_servicing_and_recovery.py` — 7 call sites of the `assert_instant_equals(actual, expected, label)` helper omitted the mandatory third `label` argument, raising `TypeError: assert_instant_equals() missing 1 required positional argument: 'label'` before the comparison ever ran. This wiped out 5 tests deterministically in all 8 rounds (`test_a_payoff_must_match_the_computed_figure_to_the_cent`, `test_a_scheduled_payment_one_cent_past_the_last_bucket_is_refused`, `test_a_terminated_agreement_bars_possession_and_a_held_unit_bars_land_work`, `test_the_cure_period_bars_possession_and_redemption_is_not_on_this_arm`, `test_the_redemption_window_shuts_at_the_instant_possession_opens`). Added the diagnostic labels (`Loan.last_accrual_date`, `LienFiling.released_at`, `RecoveryCase.cure_deadline_date` x2, `RecoveryCase.possession_date` x2, `RecoveryCase.redemption_window_ends_at`), matching the convention every other module in the suite already used. The assertions themselves were untouched — the label is purely the failure message.

- `test_suite/test_16_cross_cutting_layers.py` line 308 — `api.list_insurance_policies({"loan_id": loan_id})` passed the filter dict into the client's first positional parameter, which is `headers`, not `params`. The request therefore went out with no `X-User-ID`/`X-User-Role` at all and the PRD-faithful implementation correctly answered `ERR_UNAUTHENTICATED` (401), failing `test_a_stale_loan_version_outranks_even_an_inverted_coverage_interval`. Corrected to `api.list_insurance_policies(fixtures.SERVICER, {"loan_id": loan_id})`, matching the identical call shape used in test_06, test_09, test_10 and test_15.

**Fixes applied to `test_helpers/`:** none needed — the fixtures, factories and role-header builders were already PRD-consistent (integer cents throughout, full ISO-8601 instants rather than date-only, `CommunityOperator`/`Borrower` headers carrying the acting entity's own `id`).

**Fixes applied to `implementation/`:** none. No implementation defect was found; both failure clusters were test-side call errors. The implementation was not modified in any way.

**Additional verification:** after fixing the two arity bugs I ran an AST-based sweep over all 16 test modules checking every call site against the real signatures of `ApiClient` methods and of every function in `fixtures.py`, `factories.py` and `assertions.py` (missing required args, excess positionals, unknown keywords). Zero remaining mismatches, which is consistent with the clean sweep.

One note for the record: both bugs were latent arity errors that no amount of implementation work could have fixed, and both were fully deterministic — identical failures in all 8 rounds, with no load-induced flakiness anywhere in either sweep.

**Orchestrator verification:** independently parsed all 8 `workspace/implementation/results.$i.json` files — every one reports `passed=90 total=90 failed=0 errors=0`. Sweep artifacts are present on disk, so the clean-sweep claim is confirmed rather than taken on trust.

**Orchestrator decision on Step 8:** the skill's skip condition requires 0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes. Step 7 applied 2 `test_suite/` fixes, so the condition is not met and Step 8 runs. Both fixes were pure Python call-arity errors (a missing `label` argument used only in failure messages, and a filter dict passed into the `headers` positional) with no behavioral semantics attached, and `implementation/` was never modified — so Step 8 is expected to find no PRD silence to patch and may legitimately emit a byte-identical `PRD_FINALIZED.md`. Step 9 then does the substantive full-scan alignment work.

## Step 8: Finalize PRD — 2026-09-05T13:15:00.000Z

**Result: `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md`.** Nothing in `<step_7_diff>` is in scope for a PRD patch.

Line counts: PRD.md 468 / PRD_FINALIZED.md 468 — 0 lines changed, 0.0% delta (identical md5 `98e49f36…`).

Changes: **none.**

Why each Step 7 item is out of scope (per-item verification):

**Item 1 — `assert_instant_equals` missing `label` arg (7 call sites, `test_suite/test_14_...py`)**
- Subject: nothing behavioral. `test_helpers/assertions.py:64-69` shows `label` is interpolated only into the `assert` failure message; the comparison is `instants_equal(actual, expected)` and is unaffected by the third argument. Pure Python arity error.
- I still checked the five compared fields against the implementation, in case the underlying assertion had been sitting on a PRD silence: `Loan.last_accrual_date` = clock (`implementation/routes_loans.py:261` at funding, `implementation/domain.py:250` on accrual, initialised null at `routes_loans.py:79`); `LienFiling.released_at` = clock (`routes_servicing.py:28` payoff release, `routes_units.py:209` conversion-completion release, cleared to `None` at `routes_units.py:228` on rescind, initialised null at `routes_filings.py:49`); `RecoveryCase.cure_deadline_date` = clock + `RIGHT_TO_CURE_DAYS` (`routes_recovery.py:145`, `constants.py:92` = 10); `redemption_window_ends_at` = clock + `STATUTORY_REDEMPTION_DAYS` (`routes_recovery.py:148`, `constants.py:93` = 45); `possession_date` = clock (`routes_recovery.py:216`). Every one matches PRD §3.7 and §3.9 prose verbatim. No silence, no divergence.

**Item 2 — filter dict passed into the `headers` positional slot (`test_16_cross_cutting_layers.py:308`)**
- Subject: behavior on a request carrying no `X-User-ID`/`X-User-Role`. `test_helpers/api_client.py:207-212` confirms the signature is `list_insurance_policies(headers, params=None)`, so the dict landed in `headers` and the request went out with neither auth header.
- Enumerated impl paths: `implementation/security.py:45-55` (`authenticate()` — missing either header, blank header, or unknown role all raise `ERR_UNAUTHENTICATED`), `security.py:58-63` (`require()`, which every route funnels through before any param or version check). PRD §2.1 already states verbatim that an absent header yields `ERR_UNAUTHENTICATED` (401), and §2.7 already places that check at the top of the ladder, above the §2.9 stale-version guard the test was actually probing. Uniquely determined; nothing to pin.
- (Noted but deliberately not patched: `security.py:51` also rejects whitespace-only header values as `ERR_UNAUTHENTICATED`, which PRD describes only as "absent". That path was not exercised by either Step 7 fix, so under the hard scope rule it belongs to Step 9's full-implementation alignment scan, not here.)

`implementation/` was never modified by Step 7 and no test was deleted, so there is no fix that reveals PRD silence or PRD/impl mismatch. I made no edits rather than manufacture an out-of-scope diff. Only `PRD_FINALIZED.md` was written; `PRD.md`, `worklog.md`, `test_suite/`, `test_helpers/` and `implementation/` are untouched.

**Orchestrator note:** confirmed via `md5sum` that PRD.md and PRD_FINALIZED.md are byte-identical. This is the legitimate outcome for Step 8 when Step 7 applied no `implementation/` fixes — the skill only forbids a byte-identical *Step 9* output. Step 9 is therefore the step that must produce a real diff, and to guard against the known failure mode where a single Step 9 agent no-ops on a large spec, the orchestrator will run it as three sequential passes partitioned by implementation module over one shared `PRD_COMPLETED.md` (pass 1 performs the `cp`; passes 2 and 3 must not).

## Step 9: Complete PRD — 2026-09-05T14:00:00.000Z

Run as **three sequential passes partitioned by implementation module** over one shared `workspace/PRD_COMPLETED.md`. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying so as not to destroy earlier edits. Total: **69 changes (50 ambiguity-pins, 19 mismatch-revisions)**, 468 -> 471 lines, 92,566 -> 121,689 chars (+29,123).

### Pass 1 — cross-cutting + reference + units + valuations
Slice: app.py, envelope.py, shape.py, security.py, store.py, core.py, errors.py, constants.py, routes_reference.py, routes_units.py, routes_valuations.py, and the valuation walk in domain.py.
468 -> 471 lines, 92,566 -> 102,286 chars (+9,681). **20 ambiguity-pins, 5 mismatch-revisions.**

- §2.1 — insert — ambiguity — blank/whitespace-only `X-User-ID`/`X-User-Role` are `ERR_UNAUTHENTICATED`, not just absent ones — security.py:51-52
- §2.1 — insert — ambiguity — how a `Borrower` owns a unit (`land_owner_borrower_id` match **or** any loan on the unit with its `borrower_id`; loan state irrelevant) — security.py:82-88
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric chars — core.py:50,64
- §2.2 — insert — ambiguity — three transport-level codes outside §5 (`ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500), unauthenticated, plus trailing-slash insignificance — app.py:38,48-67
- §2.3 — revise — ambiguity — non-integer/decimal/sign-prefixed `limit`/`offset` are `ERR_INVALID_REQUEST`; empty string takes the default; whitespace stripped — envelope.py:57-67
- §2.3 — revise — ambiguity — `has_more` = `offset + len(page) < total_count`; ownership narrowing happens after filters and before the page cut so `total_count` is post-narrowing; object responses carry no pagination meta — envelope.py:16-32,80-84, routes_units.py:175-176
- §2.4 — revise — ambiguity — clock response `data` is only `{current_utc}`; setting to the current instant is accepted — routes_reference.py:27-30
- §2.5 — insert — ambiguity — all instant fields use the 3-fractional-digit form, unset fields render as `null`, internal bookkeeping fields are never serialized — store.py:51-67, core.py:71-80
- §2.6 — insert — ambiguity — within one body FKs resolve in declaration order (`community_id` before `land_owner_borrower_id`; `unit_id` before `guide_id`); non-string FK is a shape failure at that rung; optional `null` counts as absent — routes_units.py:93-98, routes_valuations.py:25-26, shape.py:118-132
- §2.7 — revise — **mismatch** — ownership precedes existence only for identifier-only checks (operator/community, borrower/borrower -> 403 even for an unknown id); resource-reading ownership checks come *after* path resolution (-> not-found) — routes_reference.py:89-90,121-122 vs routes_units.py:153-154
- §2.7 — insert — ambiguity — new paragraph pinning the four shape conventions: missing/null/non-object body handling, JSON `null` == absent, non-blank strings & boolean rejection, lenient instant parsing (Z / offset / bare date / naive->UTC) — shape.py:15-51,94-99, core.py:83-101
- §2.8 — insert — ambiguity — half up on a negative quotient means half away from zero (-0.5 -> -1) — core.py:142-152
- §2.10 — insert — ambiguity — definition of "non-terminal loan" (servicing not `PAID_OFF`/`CHARGED_OFF` and underwriting not `DECLINED`; `DRAFT`/`UNDERWRITING` loans included) — routes_units.py:29-37
- §3.1 — insert — **mismatch** — `state_code` is only validated as a non-empty string; no two-letter/alphabet check on borrower or community — routes_reference.py:76,104
- §3.1 — insert — ambiguity — wrong-role arm of the operator-agreement endpoint is `ERR_ROLE_NOT_PERMITTED`, judged after community resolution and `action` enum validation, before the standing gate — routes_reference.py:135-139
- §3.1 — insert — ambiguity — `TERMINATE` does not clear `agreement_executed_at`; re-execution overwrites it — routes_reference.py:152-156
- §3.2 — revise — ambiguity — `model_year` is an unbounded integer — routes_units.py:105
- §3.2 — revise — **mismatch** — the exact placement-consistency test: only the two FKs are cross-checked for absence, so `land_parcel_apn`/`land_county` on a community placement and `lot_number`/`placement_start_date` on a private-land placement are accepted and stored — routes_units.py:54-67
- §3.2 — revise — ambiguity — lot-occupancy boundaries: null `placement_end_date` incumbent has no end and no buffer (conflict at/after its start), null `placement_start_date` incumbent is ignored, earlier-than-incumbent start never conflicts — routes_units.py:70-84
- §3.2 — revise — **mismatch** — land-document recording is **not** gated on `placement_type`; a repeat recording of an already-true flag still bumps `updated_at`/`version` — routes_units.py:183-196
- §3.2 — insert — ambiguity — list-filter semantics for every list endpoint: bad enum filter -> `ERR_INVALID_REQUEST`, id filters matched opaquely (unknown id matches nothing), empty value == omitted — routes_units.py:20-26,161-174
- §3.3 — revise — ambiguity — every retired valuation gets its own `updated_at`/`version` bump; `DRAFT` rows and the other variant are untouched — routes_valuations.py:50-56
- §3.8 — revise — ambiguity — a still-`SUBMITTED` filing refuses `COMPLETE` with `ERR_FILING_INVALID_STATE` (409), checked after the classification and recovery-hold gates — routes_units.py:262-264
- §3.8 — revise — **mismatch** — loans are touched unconditionally but a policy is touched only when the re-score actually moves a stored field; a loan with no policy keeps `UNKNOWN`, one with only non-`ACTIVE` policies recomputes to `NON_COMPLIANT` — domain.py:172-215
- §3.8 — insert — ambiguity — release cause is internal and unserialized; restoration is only `TITLE_LIEN` and only `RELEASED`->`RECORDED` — routes_units.py:203-230, store.py:51-57

Verified separately: errors.py `ERROR_STATUS` matches the §5 table exactly (55 ids, identical statuses), so §5 needed no edits.

### Pass 2 — loans + filings + insurance + pricing engine
Slice: routes_loans.py, routes_filings.py, routes_insurance.py, and the pricing engine / insurance requirement matrix / exposure / `rescore_policy` in domain.py.
471 -> 471 lines, ~102,230 -> ~110,900 chars (+~8,670). **15 ambiguity-pins, 5 mismatch-revisions.**

- §2.6 — revise — ambiguity — body-FK resolution order for loan application pinned (`borrower_id` -> `unit_id` -> `origination_valuation_id` -> `refinanced_from_loan_id`); "two of them" widened to "more than one" — routes_loans.py:38-43
- §2.9 — insert — ambiguity — both `expected_*_version` fields are integers with no range, so 0/negative draws the 412 rather than `ERR_INVALID_REQUEST` — routes_insurance.py:38-41
- §2.10 — revise — **mismatch** — the bullet claimed every affected policy is re-scored on creation/supersession/lapse/cancellation; only the §3.8 classification cascade re-scores. Now: recompute of `insurance_compliance` on classification change and policy creation; lapse -> `NON_COMPLIANT` outright, force-placement -> `COMPLIANT` outright; re-score narrowed to §3.8 and touch-only-on-movement — routes_insurance.py:96,178; routes_servicing.py:229-235; domain.py:172-198
- §3.4 — insert — ambiguity — `refinanced_from_loan_id` is resolved for existence only; never checked for same unit/borrower/state — routes_loans.py:41-43
- §3.4 — revise — ambiguity — `CONVERSION_PENDING` snapshots to `PERSONAL_PROPERTY`; mapping stated exactly — routes_loans.py:20-24
- §3.4 — insert — ambiguity — a `certified_value_cents` of zero or less yields `ERR_LTV_CAP_EXCEEDED` with no quotient formed — domain.py:107-111, routes_loans.py:142
- §3.4 — insert — ambiguity — approval recomputes the borrower's derived exposure fields *before* the suspension gate, and that recompute may move `status`/`version` even on a request about to be refused — routes_loans.py:170-172
- §3.4 — insert — ambiguity — `decline_reason` stored verbatim (empty string included), null when omitted — routes_loans.py:191-193
- §3.4 — revise — **mismatch** — funding's four conditions were narrated perfection-first; impl order is filing-type match -> three insurance counts -> operator agreement -> perfection last. Also pinned: the type check applies to *every* `RECORDED` filing and passes vacuously with none; `escrow_target_cents` is zero or more; two worked consequences of the ordering — routes_loans.py:236-256
- §3.5 — insert — ambiguity — tender stores `submitted_documents` as sent (array of strings, extras/duplicates/order tolerated), `missing_documents` necessarily empty, no servicing/recovery-hold gate, no per-loan filing ceiling, lien dimension written from whatever it held — routes_filings.py:26-56
- §3.5 — insert — ambiguity — `title_status` moves only from `ACTIVE_TITLE` (otherwise the unit's `updated_at`/`version` do not move); `agency_reference` and `rejection_code` are both optional, each recorded only on its own arm and discarded on the other; each arm writes the loan's lien dimension outright — routes_filings.py:99-120
- §3.5 — insert — ambiguity — re-tender replaces `submitted_documents` wholesale and never re-checks `filing_type` against the loan's current classification — routes_filings.py:134-143
- §3.5 — insert — ambiguity — agency response and re-tender return the filing row, not the loan — routes_filings.py:121,151
- §3.6 — insert — ambiguity — `coverage_days` is a whole-calendar-day count and can be 0 for a sub-day interval; policy creation is gated by no loan standing — routes_insurance.py:66, core.py:104-108
- §3.6 — revise — ambiguity — insurable value is the cited `origination_valuation_id` row read at its current `status` (a `SUPERSEDED` one still counts, variant/certification not re-verified), 0 when it resolves to nothing; exposure keyed on `underwriting_state == FUNDED`; each policy stores its own `required_coverage_cents` snapshot — domain.py:138-154
- §3.6 — revise — **mismatch** — creation cascade: "either COMPLIANT or NON_COMPLIANT" was wrong for a loan with no policy row (stays as held); now COMPLIANT iff at least one surviving `ACTIVE` policy is graded COMPLIANT (a live force-placed one counts), superseded rows keep their grading, no other policy re-scored, touch-only-on-movement, loan `version` increments regardless — routes_insurance.py:79-97, domain.py:201-215
- §3.6 — revise — **mismatch** — funding's wind and dwelling counts said "the active policy"; impl tests each independently across all clock-covering `ACTIVE` candidates (they may be different policies), ignores stored `insurance_compliance`/`compliance_state`/policy snapshots, and recomputes the requirement with exposure = `principal_cents` — routes_loans.py:206-225
- §3.6 — revise — ambiguity — force-placed row's unstated fields pinned: `status` ACTIVE, `wind_deductible_cents` 0, `unearned_premium_refund_cents` 0, `compliance_state` COMPLIANT by construction — routes_insurance.py:155-173
- §3.6 — revise — ambiguity — a placement spanning no whole calendar day prices at 0; `insurance_compliance` set to COMPLIANT outright (no derivation, no supersession, no re-score); response is the policy row — routes_insurance.py:151-180
- §3.6 — revise — **mismatch** — refund arm cancels *every* ACTIVE force-placed policy (whether or not it still covers the clock); refund is 0 when `coverage_days` is not positive; remaining days are not floored, so a clock past `expiry_date` yields a negative figure stored and applied as computed, with only the loan bucket floored at zero — routes_insurance.py:86-94, domain.py:225-230

Handed-down resolution: the impl never calls `rescore_policy` from policy creation or force-placement (only from the §3.8 conversion cascade), so §3.6 pins that creation grades only the new row and force-placement re-scores nothing, cross-referencing §3.8's touch-only-on-movement rule; §2.10's bullet was corrected to match. Pass 1's §3.8 sentences untouched. Only pass 1's §2.6 FK-order sentence was widened ("two of them" -> "more than one"); no pass-1 wording removed.

### Pass 3 — servicing + recovery + accrual/waterfall/settlement
Slice: routes_servicing.py, routes_recovery.py, and accrual / waterfall / `payoff_amount_cents` / `default_threshold_days` / `commission_bps_for` / `settle` in domain.py.
471 -> 471 lines, ~110,900 -> 121,689 chars (+10,789). **15 ambiguity-pins, 9 mismatch-revisions.**

- §2.5 — revise — mismatch — carved out the one field that is *absent* rather than null: `reversal_reason` is written only onto rows the reversal endpoint creates — routes_servicing.py:206 vs 61-79
- §3.1 — revise — mismatch — exposure recomputation call sites corrected: every payment posting **and reversal**, every lot-rent report, every recovery-hold change; unit/placement writes do **not** trigger it — routes_servicing.py:53,129,149,208; routes_recovery.py:88,183,326
- §3.5 — revise — mismatch — settlement release is gated on nothing: the lien dimension is written to `RELEASED` outright (not only from `PERFECTED`), **every** `RECORDED` filing on the loan is released, and zero buckets are a consequence not a precondition — routes_servicing.py:23-31
- §3.7 — revise — mismatch — principal also moves via payoff and §3.9 settlement; **payment reversal carries no servicing-standing gate**, so a `PAID_OFF`/`CHARGED_OFF` loan can still be reversed — routes_servicing.py:181-209 vs 93
- §3.7 — insert — ambiguity — accrual day count truncates both endpoints to UTC calendar date; negative span -> 0; null endpoint -> 0; null `apr_bps` accrues nothing — core.py:104-108, domain.py:237-245
- §3.7 — insert — ambiguity — `amount_cents` is an unbounded integer (zero/negative accepted at the shape rung); a refused posting commits nothing — no row, no interest, watermark unmoved — routes_servicing.py:90,98,109,134
- §3.7 — insert — ambiguity — the interest bucket in the waterfall is stored interest **plus** the interest this same call accrued — routes_servicing.py:99, domain.py:265-273
- §3.7 — revise — mismatch — overpayment refusal fires only on a **strictly positive** residue; a negative amount is absorbed whole by the first bucket and increases it; a directly posted `REVERSAL` kind is exempt and its residue is discarded — routes_servicing.py:132-134, domain.py:275-281
- §3.7 — revise — mismatch — payoff: expected figure not floored (negative when escrow exceeds the buckets); `CURRENT` **or** `DELINQUENT` -> `PAID_OFF`; `delinquent_days` reset to 0; lien written `RELEASED` outright; **every** `RECORDED` filing released; the row's `to_escrow_cents` is the *negative* of the refunded escrow; `next_due_date` untouched — routes_servicing.py:102-130
- §3.7 — insert — ambiguity — cure fires whatever the `payment_kind`; one-month advance clamps the day of month (31 Jan -> last day of February) carrying time of day; null `next_due_date` stays null; a `CURRENT` loan's due date never advances — core.py:115-128, routes_servicing.py:139-145
- §3.7 — insert — ambiguity — reversal row fully pinned: negated `amount_cents`, `posted_at` = clock, `allocation_variant` copied, `accrual_days`/`accrued_interest_at_posting_cents` 0, own `reversed` false, `reversal_reason` verbatim incl. blank; and **nothing else is rewound** (`servicing_state`, `next_due_date`, `delinquent_days`, `last_accrual_date`; a reversed payoff stays `PAID_OFF` with filings `RELEASED`) — routes_servicing.py:181-209
- §3.7 — revise — mismatch — assessment's four steps in order; **every** expired `ACTIVE` policy lapses; one lapse writes `insurance_compliance` to `NON_COMPLIANT` **outright** even where a compliant force-placed policy survives; version increments on every call; no exposure recompute; answers with the loan — routes_servicing.py:223-243
- §3.7 — insert x2 — ambiguity — `months_delinquent` is an integer >= 0 with no upper bound; the report increments `version`, re-derives exposure, and answers with the loan row — routes_servicing.py:44-54
- §3.9 — insert — ambiguity — default declaration neither accrues nor refreshes `delinquent_days`; it reads the counter as the last assessment left it — routes_recovery.py:46
- §3.9 — insert — ambiguity — full field-initialization list for a new case (15 nulls, empty line-item array, `refurbishment_cost_cents` 0) and the absence of any "one case per loan" check — routes_recovery.py:54-79
- §3.9 — insert — ambiguity — cure/redemption deadlines are exact instant arithmetic (10 or 45 x 24h, clock's time of day carried) compared as instants, not calendar days; the loan moves `DEFAULT`->`RECOVERY` only where it stands at `DEFAULT` (else untouched, no version bump); recovery actions answer with the case row — routes_recovery.py:145-156, core.py:111-112
- §3.9 — insert — ambiguity — redemption: standing move conditional on `RECOVERY` though the loan is touched either way, unit touched only if a hold was cleared; `title_status` **stays** `TITLE_ENCUMBERED`, buckets/`delinquent_days`/`next_due_date`/`last_accrual_date` untouched, filing stays `RECORDED` — routes_recovery.py:159-184, 26-31
- §3.9 — revise — mismatch — possession weighs access -> perfection -> timing per §2.7 (paragraph reordered); recorded filing is sought **on the loan**, not on the unit; the access test reads the unit's current `community_id`, not the loan's `placement_type`; possession touches only the case — routes_recovery.py:187-218
- §3.9 — insert — ambiguity — `cost_cents` is zero or more — routes_recovery.py:252
- §3.9 — insert — ambiguity — `resale_price_cents` is an integer >= 0, unbounded above; `resale_loan_id` is resolved for existence ahead of the rest of the body (404 beats a missing price) and is otherwise never cross-checked — routes_recovery.py:289-292
- §3.9 — insert — ambiguity — settlement re-derives the capitalized sum from the line items and writes it back onto `refurbishment_cost_cents` — domain.py:337-349
- §3.9 — insert — ambiguity — the four buckets are read as they stand (no accrual at settlement); `recovery_expense_cents` already carries the path seed plus expensed lines; `payoff_amount_cents` is **not floored** and a negative payoff enlarges the surplus — domain.py:345-358
- §3.9 — revise — mismatch — `escrow_balance_cents` alone survives the zeroing; unit touched whether or not the hold was set; **every** `RECORDED` filing released with the lien written outright; the surplus exists only as `surplus_cents` (no cash movement, no payment row, no loan/borrower field) — routes_recovery.py:300-327

Pass 3 notes: `domain.payoff_amount_cents` is dead code — no route calls it; the payoff expectation is computed inline in routes_servicing.py:103-107 with the identical formula, which is what §3.7 now pins. `core.add_one_month` clamping pinned with leap-year-safe phrasing. §3.9's cure deadline and redemption window turned out not to be calendar-day counts at all (`core.add_days` + instant comparison), so that was pinned instead. Three sentences outside pass 3's own sections needed minimal adjustment (§2.5 `reversal_reason` absence, §3.1 exposure recomputation call sites, §3.5 settlement release gating) — all three were original PRD prose, not passes 1/2 insertions, and no earlier edit was reverted or reworded.

Pass 3's final consistency read: 471 lines, §4 endpoint table intact at 49 rows, §5 error table intact at 55 rows, file ends at `| ERR_LENDER_ACCESS_NOT_GRANTED | 409 |`.

**Orchestrator verification of Step 9:** `md5sum` shows `PRD_COMPLETED.md` (44b3fd71…) is NOT identical to `PRD_FINALIZED.md`/`PRD.md` (98e49f36…), so the scan genuinely ran — 123 changed lines under `diff`, 468 -> 471 lines, 92,566 -> 121,689 chars. Independently confirmed the §4 table still carries 49 `/chattel` endpoint rows, the §5 table still carries 55 `ERR_` rows, and the file's last line is a complete table row rather than mid-sentence. Step 9 edited only the PRD, so the Step 7 sweep artifacts (`results.1..8.json`, all 90/90) remain the valid evidence of a green suite.
