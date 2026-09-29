# Worklog — task_2773_name_image_and_likeness_collective_administration

## Step 1: Create task directory — 2026-09-04T19:28:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2773_name_image_and_likeness_collective_administration` and its `workspace/` subdirectory. Index 2773 was pre-assigned by the invoking command; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-04T20:47:00.000Z

All three scaffold artifacts are complete and the linter reports `VERDICT: clean lint`.

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_2773_name_image_and_likeness_collective_administration/`

| File | Lines | Bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 2532 | 162483 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1619 | 109895 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3178 | 220482 |

**Counts**
- SCAFFOLD.yaml (§1.0–§1.7, no design keys present): 10 entities, 11 state machines, 4 concurrency rules, 10 calculations, 46 validations, 50 endpoints, 63 errors, 6 roles. `api_prefix: /nil`; profile = compliance_audit / ledger_reconciliation, graph topology, parallel state machines, `segregation_of_duties` role model, immediate consistency, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`.
- SCAFFOLD_DIFFICULTY_DESIGN.yaml: 9 difficulty rules x 2 = **18 instances**.
- SCAFFOLD_CORNER_DESIGN.yaml: 9 sections, **68 instances** (60 with full `test_recipe`, 8 `excluded_because` stubs, each citing a real §1.8 instance by name). Per section: entities 12, state_machines 12, calculations 9, validations 13, endpoints 6, errors 5, rbac 3, cross-cutting complexity layers 7, consistency model 1.
- Linter: 735 calls scanned across §1.8+§1.9, all conforming to §1.5, all §1.1 FKs reverse-reachable. Instance names are globally unique across both design files (verified, zero duplicates).

**Design adjudications made**
1. **Withholding default bug (fixed in both design files).** `calc_release_withholding` gives a US_PERSON athlete BACKUP withholding at 24% unless `taxpayer_doc_on_file == W9`; four recipes had asserted zero withholding for athletes left at the default doc value. Each now issues `PATCH /nil/athletes/{id}/tax-profile {taxpayer_doc_on_file: W9}` and asserts the doc state before asserting `net_payable_cents`.
2. **WAIVED vs FORFEITED.** Only FORFEITED deliverables leave `DealContract.deliverable_value_total_cents`, so a planned "waive excludes it from the total" corner was false and was replaced by `termination_forfeits_only_non_terminal_deliverables` (200000 -> 120000 with one VERIFIED and one PENDING sibling).
3. **Priority masking audited throughout.** Posture gates (23-25) outrank the athlete annual cap (39) and the roster gates (27/39), so the cap recipe pre-seeds a gross 6000000 gift (net 5874000) to keep the posture OPEN, and each OCC recipe pairs the 412 with the *next* error the same call would raise (ERR_NO_ELIGIBLE_ATHLETES 422, ERR_COLLECTIVE_FUNDING_FROZEN 409) to prove priority 21 fires first.
4. **One OCC corner per §1.2.1 rule** (4 rules -> 4 instances), all named `..._returns_412` so the linter's negative-trigger heuristic accepts the deliberately stale `${...}` versions.
5. **Segregation of duties is by X-User-ID, not role**: the SoD corner has one identity (`dual-agent`) verify as ComplianceOfficer and then attempt the payout as TreasuryOfficer -> ERR_SEGREGATION_OF_DUTIES 403, with `treasury-clean` succeeding on the identical body and reusing the same contract version (proving the rejection wrote nothing).
6. Table 6 (errors) has no named claim rows in the extraction guide, so all 5 error-section instances use `violation_to_error`; the entity-backed athlete-ownership corner uses the guide's `peer_roles` row since it is athlete-A-cannot-touch-athlete-B's resource.
7. The `Generate task harder than expert level!` directive line was deliberately kept out of the SCAFFOLD's `scenario` key (it starts at "2773. Name, Image and Likeness..."), so it cannot leak downstream into PRD.md.

**Orchestrator verification:** `grep -rn "harder than expert"` over the task directory returns nothing — the difficulty directive did not leak into any scaffold artifact.

## Step 3: Copy shared files — 2026-09-04T20:48:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (bash only, no subagent).

## Step 4: Generate PRD — 2026-09-04T21:07:00.000Z

PRD generation complete.

**Output:** `workspace/PRD.md`

## Structure

- **507 lines**, 5 top-level sections, 21 subsections.
- `## 1. Introduction` (3 paragraphs)
- `## 2. Global Specifications & System-Wide Principles` — 12 subsections (2.1 RBAC and the `X-User-Role`/`X-User-ID` contract; 2.2 response envelope; 2.3 pagination and `sequence_no` ordering; 2.4 identity/insertion order/row versions; 2.5 logical clock, tax years, calendar arithmetic; 2.6 integer cents and rounding; 2.7 stale-version guards; 2.8 the full 46-priority failure order; 2.9 nested addressing and referential integrity; 2.10 the funding-posture gate; 2.11 segregation of duties; 2.12 cascades, bubble-ups and ledger re-derivation)
- `## 3. Business Logic & Workflows` — 9 subsections (3.1 collective founding + contact adjudication; 3.2 entity-structure change and its three-level cascade; 3.3 tier ladder and donor roll; 3.4 commitments and the supersession chain; 3.5 contributions, fees, settlement; 3.6 deductibility and the two billing runs; 3.7 athlete roster, portal movement, taxpayer docs; 3.8 contracting, roster allocation, disclosure, activation; 3.9 documented services, verified payouts, reversal, clawback)
- `## 4. API Endpoint Definitions` — lead paragraph fixing 201-vs-200 per endpoint, then **50 rows, exactly 4 columns**
- `## 5. Error Codes` — **63 rows, exactly 2 columns**

**Tail verified complete:** the file's last line is the final error row `| ERR_RELEASE_EXCEEDS_PAYOUT_ELIGIBLE | 422 |`. §5 is a complete section, nothing is cut mid-sentence, and there is no audit/report footer.

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS.** 144 unique identifiers extracted from the scaffold (111 `entities[].fields[].name` including the nested `evidence_records` element fields, 91 distinct `input` names across all 50 endpoints after stripping optional markers, 15 inline output-object keys) were checked against the 461 backticked tokens in the PRD (code fences excluded). **Missing: 0.** `id`, `created_at`, `updated_at` and `version` are additionally covered explicitly in §2.4, including the two exceptions (`Collective` has no `sequence_no`; `CommunicationLog` has no `updated_at` and no `version`).

**Contract 2 — Rule Coverage: PASS.** All 63 error IDs appear in §2/§3 *prose*, not merely in the §5 table (checked over sections 2-3 only: 0 missing). All 118 enum values and state-machine states appear verbatim. All 60 state-machine transitions across the 11 machines are covered — 57 explicit `from -> to` pairs verified by co-occurrence, plus the 3 `from: "*"` funding-posture re-derivations covered by §2.10. All 46 validation priorities are enumerated in order in §2.8; all 10 calculations are written out in prose (including the pinned stage order for `calc_deliverable_payout_eligible` — share floor first, 15-percent lateness penalty second — and the post-forfeiture timing of `calc_clawback_amount`); all 4 concurrency rules are in §2.7 with their `expected_*_version` names and 412 error IDs; the three DealContract dimensions, the `applies_to` posture scopes, and the sibling-branch symmetry of the payment/disclosure/deliverable machines are all stated.

**Contract 3 — §3 Path Purity: PASS.** 1141 backticked tokens (389 unique) in §3 were scanned: **0** begin with `/`, **0** are a bare HTTP method, **0** combine method+path. There are also zero raw unbackticked `/nil/...` strings and zero bare `GET`/`POST`/`PATCH`/`PUT`/`DELETE` words anywhere in §3.

## Additional verification

- §2.2 is **byte-identical** to `skills/prd-bench-doc-generator/section-2.2-response-structure.md` (verified by `diff`).
- No pseudocode or operator syntax anywhere.
- No fuzzy quantifiers ("approximately", "roughly", "etc.", "TBD") anywhere.
- No Hard Contract report, coverage table or audit footer was written into PRD.md or any sibling file.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped or referenced; no other `task_*/` directory was read.

**Orchestrator verification of the known truncation failure mode:** `tail -15 PRD.md` ends on the final `ERR_RELEASE_EXCEEDS_PAYOUT_ELIGIBLE` table row — a real section boundary, not mid-sentence. `grep -in "harder than expert\|scaffold" PRD.md` returns nothing, so neither the difficulty directive nor any scaffold reference leaked into the PRD. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-04T22:26:00.000Z

Generation is complete. All 18 test files and the helper package are in place at the task root.

## Files

**`test_helpers/`** (9 files, 2,236 lines): `__init__.py`, `api_client.py` (ISO timestamps canonicalised; money always sent as JSON integers), `api_errors.py` (error-id constants + `set_error_http_status_map`), `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`.

**`test_suite/`** (`conftest.py` + 18 test modules, 8,836 lines):
- Queue A (§1.8 depth): `test_01`-`test_09` — 36 tests
- Queue B (§1.9 breadth): `test_10` entity shapes (11), `test_11` state machines (10), `test_12` calculations (6), `test_13` validation ladder (12), `test_14` endpoint behaviour (6), `test_15` error identity (5), `test_16` role boundaries (3), `test_17` stale-version guards + window boundaries (5), `test_18` immediate consistency (1) — 59 tests

## Counts and coverage

- **95 tests total**, all collected cleanly (`pytest test_suite --collect-only -q` -> `95 tests collected`).
- **Queue A: 36 tests covering 18/18 live instances** (no stubs in the difficulty index).
- **Queue B: 59 tests covering 59/60 live instances**; the 8 `excluded_because` stubs are never referenced.
- Every test carries **exactly one** `Design:` line; a yaml-parsing audit confirms every tag resolves to a real non-stub instance and every tag has the `Queue/section/name` shape. No untagged or dual-tagged tests.
- Unused-import AST sweep clean on every file.

## Skipped / adapted instances

- **SKIPPED — `Corner/entities/contribution_computed_net_ignores_client_supplied_net_amount`**: the instance asserts `ERR_INVALID_REQUEST` for a client-supplied `net_amount_cents`, but PRD §2.8 states "Unknown body fields are ignored rather than rejected", so the asserted outcome is not uniquely derivable. Gap left as a gap.
- **Adapted — `Corner/calculations/clawback_cap_percentage_differs_by_association_ruleset`**: yaml `home_state_code: IA` is outside the PRD's permitted set {AL, CA, FL, OH, TX}; used FL with citation "FL-1006.74".
- **Adapted — `Corner/state_machines/...voids_queued_release`**: omitted the yaml's `net_payable_cents == 0` sub-assertion on a VOIDED release (PRD does not derive it; §3.9 only says a VOIDED release moves no money).
- **Adapted — `Corner/errors/unchanged_entity_structure_returns_its_own_dedicated_error`**: yaml asserts `structure_effective_at == null`, contradicting PRD §3.1 which stamps it at creation; asserted "unchanged from creation" instead.
- **Setup adaptations (claim untouched)**: two corner recipes (`athlete_cannot_touch_another_athletes_deliverable`, `disclosure_submitted_after_the_window_is_recorded_as_late`) create two contracts against an unfunded collective, which per PRD §2.10 would drive `funding_posture` to FROZEN and make the *second* creation fail on priority 23 before the rule under test could run; both now fund the collective with a 500,000-cent gift (net 487,470) so the posture stays OPEN. Releases read the contract's current `version` immediately before the call rather than reusing an activation-time capture, since deliverable changes re-derive contract fields.

Neither `test_helpers/` nor `test_suite/` exists under `workspace/`; `workspace/implementation/` was never read or modified, and `worklog.md` was not touched.

**Orchestrator verification:** confirmed `workspace/test_helpers` and `workspace/test_suite` do not exist — both directories landed correctly at the task root, so no relocation was needed before Step 7.

## Step 6: Generate implementation — 2026-09-04T22:26:30.000Z

The implementation is complete.

## Files (all under `workspace/implementation/`)

| File | Lines |
| --- | --- |
| `start.sh` (chmod +x) | 10 |
| `requirements.txt` | 1 |
| `app.py` | 70 |
| `errors.py` | 101 |
| `clock.py` | 84 |
| `store.py` | 61 |
| `envelope.py` | 98 |
| `auth.py` | 37 |
| `shape.py` | 96 |
| `calc.py` | 147 |
| `derive.py` | 402 |
| `serialize.py` | 239 |
| `lookup.py` | 53 |
| `routes/__init__.py` | 0 |
| `routes/clock_routes.py` | 22 |
| `routes/collectives.py` | 205 |
| `routes/tiers.py` | 97 |
| `routes/donors.py` | 103 |
| `routes/commitments.py` | 155 |
| `routes/contributions.py` | 188 |
| `routes/athletes.py` | 157 |
| `routes/contracts.py` | 342 |
| `routes/deliverables.py` | 196 |
| `routes/releases.py` | 171 |
| `routes/comms.py` | 100 |
| **total** | **3135** |

## Verification

- **Endpoints: 50/50.** Programmatically diffed Flask's `url_map` against the PRD §4 endpoint table (method + path with placeholders normalised): zero missing, zero extra.
- **Errors: 63/63** catalog codes reachable — 53 raised directly, the 10 not-found codes raised via `lookup._get`. No code is raised that isn't in the catalog.
- **Fresh boot confirmed.** `PORT=18774 bash start.sh` in a fresh process: `GET /nil/collectives` -> HTTP 200 with `total_count 0` and empty `data` (store starts empty, nothing seeded), `POST /nil/collectives` -> HTTP 201, unauthenticated request -> HTTP 401 `ERR_MISSING_AUTH_HEADER` in the correct envelope. Server killed by the specific PID bound to that port; both smoke ports confirmed free afterwards and `__pycache__` removed.
- **End-to-end flow exercised** against a live server: collective -> tier open -> donor -> commitment -> contribution settle (fee 2.10% => net 4,895,000 on 5,000,000, verified) -> athlete + W-9 tax profile -> contract -> disclosure submit/accept -> activate -> CHARITY_WORK deliverable -> evidence -> submission -> VERIFY -> payment release (SoD rejection for the verifying user, then success) -> reversal -> billing runs (both kinds) -> roster allocation -> portal entry -> commitment restructure -> clock set -> entity-structure restructure -> termination. All state derivations came out consistent: contract reached `COMPLETED` via the fully-paid bubble-up, the reversal drove `payment_status` back to `UNPAID` and the athlete's tax-year figures to zero, `reversed_total_cents` 400000, posture recomputed to `OPEN`, comm-log verdict `PROHIBITED`/`COACH_DEAL_TERMS_BARRED`.

## Notable interpretation decisions

- **§2.9 beats §2.8 on the two nested paths.** For membership-tiers-under-a-collective and deliverables-under-a-contract the parent is resolved before any body field; every other endpoint runs shape (5) before existence (6).
- **Priority 17 codes** for deliverable submission and release creation: terminal lifecycle -> `ERR_CONTRACT_TERMINAL`, non-terminal non-ACTIVE -> `ERR_CONTRACT_NOT_ACTIVE` (scaffold priority-17 rule text; PRD §3.9 names only the latter).
- **`settled_net_funds_cents`** uses the literal §2.10/§3.5 formula (sum of SETTLED nets less REFUNDED nets), which both PRD and scaffold state identically.
- **Clock-dependent and sibling-dependent figures** (`payout_eligible_cents`, `deliverable_value_total_cents`, athlete tax-year sums, `tax_form_required`, `active_commitment_count`) are computed at serialization time so a fresh computation and the reported value can never diverge; only the collective ledger + posture, donor lifetime figures, contribution money fields and `clawback_amount_cents` are persisted.
- Free-text inputs with no declared entity field (`reviewer_note`, `review_note`, `submission_note`, `state_law_citation`, `association_rule_citation`) are type-validated then discarded; `note` on communication logs is stored and serialized since PRD §3.1 describes it on the record.

## Step 7: Run tests and iterate — 2026-09-04T22:41:00.000Z

Loop complete — clean 8-round parallel sweep.

## Iterations run
2 (sweep 1: 90/95 in every round with an identical, fully deterministic 5-test failure set; sweep 2: clean).

## Tests deleted
None. All 5 failures passed STEP 1a (verbatim PRD coverage) and STEP 1b (unique derivability); each was either a test-setup/expected-status bug or a real implementation defect.

## Fixes applied to `test_helpers/`
None — the failures were not caused by shared fixture bugs (`build_funded_collective`, factories, and role-header builders were all PRD-faithful).

## Fixes applied to `test_suite/`
- `test_suite/test_14_endpoint_behaviour_and_bulk_runs.py` — `test_restructuring_returns_the_new_row_and_links_the_cancelled_original`: asserted HTTP 200 on `POST /nil/commitments/{id}/restructure`. PRD §4 lists "a commitment restructuring" among the endpoints that "bring a new row into existence" and "answer with HTTP 201 Created", so the assertion was a mis-translation. Changed to `expected_status=201` and cited §4 in the docstring.
- Same file, `test_a_subscription_charge_cycle_skips_the_pledge_and_charges_each_subscription`: the two `RECURRING_SUBSCRIPTION` commitments were created with `installments_total` defaulting to 1, then the test billed **two** cycles and expected `charged_commitment_count == 2` on the second run. Per PRD §3.4 the commitment advances `ACTIVE -> FULFILLED` "once `installments_charged` reaches `installments_total`", so after cycle 1 both were correctly FULFILLED and no longer chargeable — a setup bug, not an implementation bug. Both are now created with `installments_total=2`.
- `test_suite/test_11_state_machine_paths.py` — `test_a_contract_below_the_threshold_and_its_deliverable_are_born_clean`: the test drafted a 59,999-cent contract on an **unfunded** collective, then drafted a second at 60,000. PRD §3.8 ("a merely `DRAFT` contract already counts as committed") plus §2.10's cross-multiplied posture derivation make the pre-request posture FROZEN for the second creation, which §2.10 requires be refused with `ERR_COLLECTIVE_FUNDING_FROZEN`. The setup did not satisfy the PRD precondition for the disclosure rule it wanted to observe; it now seeds an OPEN tier, a donor and one 200,000-cent settled gift first.

## Fixes applied to `implementation/`
- `workspace/implementation/derive.py`, `collective_settled_net()`: it added SETTLED nets **and** subtracted REFUNDED nets, so a refund was deducted twice and drove `settled_net_funds_cents` negative (-97,470 where 0 was due; 100,000 where 500,000 was due). PRD §3.5 states "The refund reduces the collective's `settled_net_funds_cents` by that row's `net_amount_cents`" — since a refund moves the row `SETTLED -> REFUNDED`, dropping it from the SETTLED sum is the only reading that satisfies both §3.5 and §2.10. Now sums SETTLED rows only.

## Final per-round numbers (from `results.$i.json`)
Rounds 1-8: `passed 95 / total 95`, `failed 0`, `errors 0`, no non-passing tests in any round.

**Orchestrator verification:** independently re-read all eight `workspace/implementation/results.{1..8}.json` files (each ~30 KB, all present, all written at 22:38). Every round parses to `passed 95 / total 95 / failed 0 / errors 0`. The clean sweep is confirmed from the artifacts, not just from the subagent's report. Step 8 will NOT be skipped: Step 7 applied 1 `implementation/` fix and 3 `test_suite/` fixes, so its skip condition (zero fixes of any kind) does not hold.

## Step 8: Finalize PRD — 2026-09-04T22:52:00.000Z

PRD_FINALIZED.md is written. Only four lines differ from PRD.md; both files are 507 lines (0.0% line delta, 4 lines revised), and the tail is the complete §5 error-code table ending at `ERR_RELEASE_EXCEEDS_PAYOUT_ELIGIBLE | 422`.

## Changes

- **§2.10 — revise — `settled_net_funds_cents` is now defined as the sum over `SETTLED` contributions *only*; `PENDING`, `FAILED` and `REFUNDED` rows contribute nothing and are never subtracted, so a refund lowers the figure solely by leaving the `SETTLED` set** — `implementation/derive.py:137-148` (`collective_settled_net`).
- **§3.5 (refunds) — revise — the refund sentence now says the figure is re-derived from the underlying rows per §2.10, dropping by that row's `net_amount_cents` "once and only once", instead of "reduces ... by that row's `net_amount_cents`"** — `implementation/routes/contributions.py:172-188` + `derive.sync_collective` (`derive.py:169-189`).
- **§3.4 — revise — `installments_charged` rises by 1 on *every* settling contribution attributed to the commitment (from `ACTIVE` as well as from `PAST_DUE`); `FULFILLED` is reached only by a commitment standing in `ACTIVE` when the counter reaches `installments_total`; added the corollary that a one-installment subscription is discharged by its first settled charge and is skipped by a later charge cycle** — `implementation/routes/contributions.py:66-75`.
- **§3.5 (settlement fan-out) — revise — same clarification in the fan-out summary: the counter is incremented on the settlement whichever of `ACTIVE`/`PAST_DUE` the commitment was in** — `implementation/routes/contributions.py:66-75`.

No edit was made for the other two Step 7 items: the restructure endpoint's HTTP 201 is already pinned by §4 ("a commitment restructuring" is listed among the 201-Created creators) and `implementation/routes/commitments.py:155` returns 201; and the FROZEN-posture refusal that broke `test_a_contract_below_the_threshold...` is already uniquely determined by §3.8 ("a merely `DRAFT` contract already counts as committed") plus §2.10's cross-multiplied derivation.

## Per-edit pre-edit search log

**Edit 1 — §2.10 `settled_net_funds_cents`**
(a) Subject: definition of the collective's settled-net ledger figure and the treatment of `REFUNDED` contributions.
(b) Paths enumerated/read: `derive.collective_settled_net` (SETTLED-only sum), `derive.sync_collective` (persists all four figures + posture, `touch` only when something changed), `derive.collective_released_total` / `collective_reversed_total` / `collective_committed_unreleased` (untouched by the wording), `derive.designated_pool` and `derive.has_settled_designation` (both SETTLED-only, per-designation — consulted by the §3.9 release checks), `derive.sync_donor_lifetime` (SETTLED-only), `routes/contributions.py:172-188` (refund: status->REFUNDED, donor lifetime sync, collective sync), `routes/contributions.settle_contribution` (SETTLED/FAILED writes), `calc.funding_posture` (consumer of the figure). Also grepped PRD for every `REFUNDED` / `settled_net_funds_cents` mention (lines 177, 179, 181, 207, 272, 274, 282) to be sure no other sentence contradicts.
(c) Adjustment: originally intended a bare "sum over `SETTLED` rows"; widened to name `PENDING`, `FAILED` and `REFUNDED` as contributing nothing *and* never being subtracted, so the sentence also covers the pending/failed rows the impl skips and cannot be re-read as an incremental deduction. Deliberately did not say anything about the refunded row's stored `deductible_amount_cents` (the impl leaves it in place), keeping that under-determined.

**Edit 2 — §3.5 refund sentence**
(a) Subject: what a refund does to the collective ledger.
(b) Paths enumerated/read: `routes/contributions.refund`, `derive.sync_collective`, `derive.collective_settled_net`, `derive.sync_donor_lifetime`, `derive.attribute_deductibility` (confirmed the refund path does *not* re-run attribution, so the existing "the next time attribution is computed" clause stays true), plus PRD §2.12's "recomputed from the underlying rows rather than adjusted incrementally" sentence for consistency.
(c) Adjustment: kept the observable magnitude claim ("lowers the figure by that row's `net_amount_cents`") rather than deleting it, but re-anchored it to a re-derivation "exactly as §2.10 defines it" and added "once and only once", so a fresh implementer cannot pair the §2.10 sum with an extra subtraction here. Did not assert a `version` bump (the impl only `touch`es the row).

**Edit 3 — §3.4 installments/FULFILLED**
(a) Subject: when `installments_charged` increments and when a commitment reaches `FULFILLED`.
(b) Paths enumerated/read: `routes/contributions.settle_contribution:66-75` (only increment site in the codebase — verified by grepping `installments_charged` across all modules), the three callers of that helper (`create_contribution` inline resolve, `POST /contributions/{id}/settlements` deferred resolve, `routes/collectives.billing_run` `SUBSCRIPTION_CHARGE_CYCLE`), the chargeability gate `routes/contributions.py:107-108` (`ERR_COMMITMENT_NOT_CHARGEABLE`), the billing-run target filter (`ACTIVE`/`PAST_DUE`, `RECURRING_SUBSCRIPTION`), `routes/commitments._new_commitment_row` and `restructure_commitment` (both start the counter at 0), the DECLINE branch (`ACTIVE -> PAST_DUE` only, no counter change), and `derive.maybe_lapse_donor`.
(c) Adjustment: two wordings were loosened. First, I avoided writing "from `ACTIVE` or `PAST_DUE`" as an exhaustive list of the states the counter can rise from — a `DEFER`-then-settle can resolve while the commitment has since become `PAUSED`/`CANCELLED`/`FULFILLED` (the settlements endpoint re-checks only contribution state), and the impl still increments there; the sentence now says "whichever state the commitment stood in beforehand". Second, the `FULFILLED` clause was narrowed to "a commitment standing in `ACTIVE` at that point", matching the impl's `status == "ACTIVE"` guard, so a paused commitment whose counter crosses the total is not mis-described as fulfilling. Left the donor-lapse re-evaluation clause as-is (the impl re-evaluates on every commitment-bearing settlement, a superset of what the PRD claims, so the existing sentence stays true).

**Edit 4 — §3.5 settlement fan-out**
(a) Subject: same as Edit 3 (the fan-out summary of the commitment advance).
(b) Paths enumerated: identical set to Edit 3, re-checked that the fan-out order in `settle_contribution` (deductibility -> donor activate -> lifetime -> commitment advance -> collective sync) still matches the four-direction narrative unchanged.
(c) Adjustment: scoped the clarification to "whichever of those two states it was in" rather than repeating the fully general claim, because this sentence is explicitly about the normal chargeable `ACTIVE`/`PAST_DUE` path; the general rule now lives in §3.4, and neither sentence denies the other's cases.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` reports 8 changed lines (4 revised line-pairs) — the file is genuinely patched, not a byte-identical copy — and both files are 507 lines with an intact §5 tail.

## Step 9: Complete PRD — 2026-09-04T23:16:00.000Z

**Orchestrator decision (recorded per the autonomy directive):** Step 9 was run as THREE sequential, module-partitioned passes over one shared `PRD_COMPLETED.md`, rather than as a single subagent doing a whole-implementation scan. A 3,135-line, 25-file implementation reliably under-covers in one pass, and the known failure mode is a `PRD_COMPLETED.md` that is byte-identical to its source (i.e. the scan never really ran). Pass 1 owned the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying and edited the same file in place with surgical `Edit` calls only. Each pass was given a disjoint module partition and was told to hand any residual it found outside its own partition to the next pass.

### Pass 1 — globals + fundraising (`app.py`, `auth.py`, `envelope.py`, `shape.py`, `errors.py`, `clock.py`, `store.py`, `lookup.py`, `routes/{clock_routes,collectives,tiers,donors}.py`)

Created `PRD_COMPLETED.md` from `PRD_FINALIZED.md`, then applied 18 in-paragraph edits. Lines 507 -> 507. Chars 109,091 -> 113,502 (+4,411). **14 ambiguity-pins, 4 mismatch-revisions.**

- §2.1 — revise — mismatch — an empty `X-User-Role` is treated as absent (`ERR_MISSING_AUTH_HEADER`), not as an unrecognised role — `auth.py:31`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` plus exactly 20 uppercase-alnum chars; `api_request_timestamp` comes from real server time, not the logical clock — `envelope.py:19,23`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` -> `ERR_INVALID_REQUEST`; empty-string value = absent; unknown query params ignored; undeclared enum-filter value -> `ERR_INVALID_REQUEST`; id-valued filter naming a missing row matches nothing rather than 404 — `envelope.py:57-98`
- §2.3 — insert — ambiguity — the collective list is ordered by collective creation, since collectives carry no `sequence_no` — `store.py:51`
- §2.8 — insert — ambiguity — lenient ISO parsing (optional `Z`, offset normalised, optional seconds, extra fractional digits truncated on output) — `clock.py:14-71`
- §2.8 — insert — ambiguity — absent body = empty object; non-object JSON body -> `ERR_INVALID_REQUEST`; explicit `null` = absent; required strings must be non-empty/non-whitespace; JSON booleans rejected for integer fields — `shape.py:14-72`
- §2.9 — insert — ambiguity — nested list endpoints resolve the outer entity before validating pagination/filters — `routes/tiers.py:56`
- §2.9 — insert — ambiguity — multiple FKs in one payload resolve in declaration order (`collective_id` before `membership_tier_id` on donor creation) — `routes/donors.py:32-33`
- §3.1 — revise — ambiguity — `institution_ipeds_code` length is never validated (any non-empty string) — `routes/collectives.py:31`
- §3.1 — revise — ambiguity — IPEDS uniqueness is an exact case-sensitive comparison — `routes/collectives.py:40`
- §3.3 — insert — ambiguity — two `OPEN` tiers of equal `benefit_rank` are never compared, so their dues may be equal — `routes/tiers.py:85-90`
- §3.3 — revise — ambiguity — donor `email` uniqueness is exact/case-sensitive and address syntax is not checked — `routes/donors.py:38`
- §3.3 — revise — ambiguity — donor tax-profile fields are both optional; a request supplying neither still succeeds and bumps `version` — `routes/donors.py:92-102`
- §3.6 — insert — ambiguity — charge-cycle contributions carry `designation` `UNRESTRICTED`; the target commitment set is snapshotted before the first charge — `routes/collectives.py:160-177`
- §3.6 — insert — ambiguity — billing report also echoes `collective_id`; non-applicable counters report 0; `failed_contribution_count` is always 0 on a charge cycle; `recomputed_contribution_count` counts every row walked whether or not it moved — `routes/collectives.py:196-205`
- §4 intro — insert — ambiguity — a trailing slash addresses the same endpoint — `app.py:30`
- §4 table (PATCH entity-structure) — revise — mismatch — "repricing unreleased contributions" replaced with the actual three-level cascade plus an explicit no-rewrite-of-history note — `routes/collectives.py:107-136`
- §4 table (PATCH donor tax-profile) — revise — mismatch — "re-deriving the deductibility of that donor's unreleased contributions" replaced with version bump + no retroactive rewrite — `routes/donors.py:100-102`
- §4 table (tier transitions) — revise — mismatch — "or retiring it" implied a third action; pinned to exactly `OPEN` and `CLOSE` — `routes/tiers.py:76`
- §5 intro — insert — ambiguity — unrouted path -> `ERR_INVALID_REQUEST` 404, disallowed method -> `ERR_INVALID_REQUEST` 405, both without regard to auth headers — `app.py:44-50`

Handed to pass 3 (both in `derive.py`, outside pass 1's partition): the §2.10 unconditional-`updated_at` claim, and the §3.6 `YEAR_END_RECOMPUTE` stamping claim on a non-deductible collective.

### Pass 2 — money movement + athletes (`calc.py`, `routes/{commitments,contributions,athletes,comms}.py`)

14 in-paragraph edits. Lines 507 -> 507. Chars 113,502 -> 116,725 (+3,223). **12 ambiguity-pins, 2 mismatch-revisions.**

- §2.8 — insert — ambiguity — an optional string that is supplied must also be non-empty/non-whitespace, with a communication record's `note` as the sole exception (empty/whitespace accepted, stored verbatim) — `routes/comms.py:48`, `shape.py:41`
- §3.1 — insert — ambiguity — an omitted `athlete_id` or `note` on a communication record is stored and reported as null — `routes/comms.py:47-48,61,71`
- §3.4 — insert — ambiguity — a restructure's replacement row carries `pause_reason` `NONE` regardless of the original's; an omitted `installments_total` is inherited from the original rather than reset to 1; the original's `amount_cents`/`installments_total` are untouched — `routes/commitments.py:144-148`
- §3.5 — insert — ambiguity — a `PENDING` row reports fee/net/deductible 0 and null `deduction_variant`; `processor_outcome` is persisted and echoed, and a later settlement `outcome` does not rewrite it — `routes/contributions.py:35-40,160`
- §3.5 — insert — ambiguity — belonging/chargeability rules are evaluated whenever a `commitment_id` is present and outrank the source-kind pairing rule, so a `ONE_TIME_GIFT` naming a cancelled commitment reports `ERR_COMMITMENT_NOT_CHARGEABLE` — `routes/contributions.py:103-114`
- §3.5 — insert — ambiguity — a deferred settlement does not re-check chargeability: a since-paused/cancelled/fulfilled commitment still takes the `installments_charged` increment while its `status` stays put — `routes/contributions.py:163-168,68-72`
- §3.5 — insert — ambiguity — the `AT_RECEIPT` pass re-runs across the donor's whole settled current-tax-year set, so sibling rows' `deductible_amount_cents` may move and a row previously stamped `YEAR_END_RECOMPUTE` is restamped `AT_RECEIPT` — `routes/contributions.py:63`, `derive.py:282-286`
- §3.5 — insert — ambiguity — on a failing contribution `deduction_variant` stays null; a commitment already `PAST_DUE` is left untouched — `routes/contributions.py:77-84`
- §3.5 — insert — ambiguity — no attribution pass runs in the refunding request; surviving rows keep their figures, the refunded row keeps its own stored fee/net/deductible/variant, and the attributed commitment is untouched — `routes/contributions.py:172-188`
- §3.6 — insert — ambiguity — each charge's `gross_amount_cents` equals the commitment's per-installment `amount_cents` — `routes/collectives.py` billing_run -> `routes/contributions.py:25`
- §3.7 — insert — ambiguity — `portal_user_id` uniqueness is exact case-sensitive and collective-scoped (reusable on another collective); `taxpayer_doc_on_file`/`treaty_exempt_claimed` are not accepted at creation — `routes/athletes.py:42-44,56-57`
- §3.7 — insert — ambiguity — `taxpayer_doc_on_file` is required, `treaty_exempt_claimed` defaults to false, and the recording overwrites both outright, so omitting the flag clears a previously-true claim — `routes/athletes.py:147-155`
- §4 table (`POST /nil/commitments/{id}/transitions`) — revise — mismatch — "or marking it fulfilled" removed: only `PAUSE`/`RESUME`/`CANCEL` are accepted, `FULFILLED` is consequence-only — `routes/commitments.py:103`
- §4 table (`POST /nil/athletes/{id}/eligibility-changes`) — revise — mismatch — "graduation" replaced by the five real values `ENTER_PORTAL`/`WITHDRAW_FROM_PORTAL`/`COMPLETE_TRANSFER`/`DECLARE_INELIGIBLE`/`REINSTATE` — `routes/athletes.py:23-24,99`

Pass 2 reported `calc.py` as already fully pinned: every formula, rounding step, order of operations, band boundary and constant (fee bands, 60/100% AGI, 30%/24% withholding, 300,000-cent treaty ceiling, 15% lateness penalty, 75% coverage, clawback caps 100/50/75, 60,000-cent 1099 threshold, 5,000,000-cent cap, 168h window, limits 2/3/2/2) already matched the PRD exactly — zero edits needed there.

### Pass 3 — contracting, deliverables, payouts, derivations (`derive.py`, `serialize.py`, `routes/{contracts,deliverables,releases}.py`)

13 in-paragraph edits. Lines 507 -> 507. Chars 116,725 -> 122,182 (+5,457). **8 ambiguity-pins, 5 mismatch-revisions.**

Disposition of the two handed-off residuals — BOTH CONFIRMED against the code and revised:
1. §2.10 `updated_at` — `derive.sync_collective` (`derive.py:176-189`) computes a `changed` flag over the four ledger figures plus `funding_posture` and calls `touch` only if one differs. The unconditional PRD claim is now conditional, and it is additionally pinned that a re-derivation never bumps the collective's `version`.
2. §3.6 `YEAR_END_RECOMPUTE` stamping — `derive.attribute_deductibility` (`derive.py:267-273`) early-returns on `charitable_deduction_enabled == false`, zeroing `deductible_amount_cents` and touching only previously-non-zero rows, without writing `deduction_variant`, so walked rows stay `AT_RECEIPT`. Pass 3 also found the gate's *scope* overstated (it hits only the donor's `SETTLED` current-tax-year rows, not every contribution of every donor, so a prior-year settled row keeps its deductible amount). Both pinned, in the §3.6 gate paragraph and the §3.6 billing-run paragraph. Counters confirmed unaffected by the gate.

- §2.10 — revise — mismatch — posture persistence refreshes `updated_at` only when a ledger figure or the posture actually changed; never bumps `version` — `derive.py:176-189`
- §3.6 (gate) — revise — mismatch — non-deductible gate scoped to the donor's current-tax-year `SETTLED` rows, touches only rows that were non-zero, and does not restamp `deduction_variant` — `derive.py:267-273`
- §3.6 (billing run) — revise — mismatch — every walked row carries `YEAR_END_RECOMPUTE` whether or not its amount moved; on a non-deductible collective no row's variant is rewritten while counters still report; donors with no qualifying row are skipped and walked donors get lifetime figures re-derived — `derive.py:274-287`, `routes/collectives.py:186-194`
- §3.8 (Activation) — insert — mismatch — activation never parses the request body at all, so no body can produce `ERR_INVALID_REQUEST` (this contradicted §2.8's global non-object-body rule) — `routes/contracts.py:313-328`
- §3.9 (Reversal) — revise — mismatch — `payment_status` may step `FULLY_PAID -> UNPAID` directly; `CLAWBACK_DUE` is left alone; no contract-lifecycle gate, so a `COMPLETED`/`TERMINATED` contract's release is still reversible; no completion re-evaluation and no clawback recompute — `routes/releases.py:148-171`, `derive.py:318-331`
- §3.3 — insert — ambiguity — donor lifetime re-derivation refreshes `updated_at` only when a figure moves and never bumps `version` — `derive.py:215-222`
- §3.8 — insert — ambiguity — `pool_amount_cents` is not shape-validated as positive; a zero/negative pool is caught by `ERR_ROSTER_SHARE_BELOW_MINIMUM` instead — `routes/contracts.py:165,210-211`
- §3.8 — insert — ambiguity — the roster batch response also echoes `collective_id`, `sport`, `allocation_mode`, `pool_amount_cents` and carries a `deal_contracts` array in distribution order, as a single object response with no pagination — `routes/contracts.py:242-254`
- §3.8 — insert — ambiguity — a non-`DRAFT` lifecycle on a compliance decision yields `ERR_CONTRACT_NOT_DRAFT` / `ERR_CONTRACT_TERMINAL`, evaluated ahead of both disclosure conditions — `routes/contracts.py:257-261,295`
- §3.8 — insert — ambiguity — the `DRAFT -> VOIDED` second-return crossover adds no second `version` bump, leaves `termination_reason` at `NONE`, computes no clawback — `derive.py:388-395`, `routes/contracts.py:305-309`
- §3.9 — insert — ambiguity — `payout_basis` is non-null from creation (read off the parent's `deal_kind`, reported even when `FORFEITED`); `payout_eligible_cents` is 0 outside `VERIFIED`/`WAIVED`; both computed at read time and stored nowhere — `serialize.py:195-196`, `derive.py:111-132`
- §3.9 — insert — ambiguity — a deliverable review has no parent-contract precondition, so `WAIVE` on a `PENDING` deliverable of a `DRAFT` contract is accepted — `routes/deliverables.py:167-196`
- §3.9 — insert — ambiguity — the `deliverable_id`/`release_kind` pairing is enforced in the priority-5 shape pass, before the contract or deliverable is resolved — `routes/releases.py:33-42`

### Orchestrator closing edit

Pass 3 reported one residual it could not author (pass 2's partition): `routes/contributions.py:170-186` (`POST /nil/contributions/{id}/refund`) likewise never calls `shape.body()`, so it shared the activation defect against §2.8's non-object-body rule while §3.5's refund paragraph carried no corresponding clause. Rather than spawn a fourth pass for one sentence, the orchestrator verified the code directly (`refund()` authenticates, looks up the row, checks `status != "SETTLED"`, and never touches the body) and appended one clause to §3.5's refund paragraph, worded identically to pass 3's activation pin. That closes the last known open item.

### Final artifact verification

- `PRD_COMPLETED.md`: 507 lines, 122,504 chars. Source `PRD_FINALIZED.md` was 507 lines / 109,091 chars -> **+13,413 chars**, 40 revised line-pairs (80 diff lines).
- **NOT byte-identical to `PRD_FINALIZED.md`** (`diff -q` reports the files differ) — the known "scan never ran" failure mode is ruled out.
- Structure intact: 5 top-level `##` sections, all 63 `ERR_*` rows present, tail ends on `ERR_RELEASE_EXCEEDS_PAYOUT_ELIGIBLE | 422`.
- Totals across the three passes plus the closing edit: **34 ambiguity-pins, 11 mismatch-revisions, 46 edits.** No new sections or paragraphs were added by any pass.
- `grep -il "harder than expert\|SCAFFOLD"` over `workspace/PRD*.md` is clean — the difficulty directive never reached any PRD variant.
- No stray `worklog.md` anywhere under the task tree; `test_helpers/` and `test_suite/` remain at the task root, not under `workspace/`.
- `implementation/` and `test_suite/` were not modified by any Step 9 pass, so the verified Step 7 result stands: `results.{1..8}.json` all report `passed 95 / total 95 / failed 0 / errors 0`.

**Pipeline complete.**
