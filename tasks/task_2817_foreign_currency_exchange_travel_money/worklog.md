# Worklog — task_2817_foreign_currency_exchange_travel_money

## Step 1: Create task directory — 2026-09-05T01:39:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2817_foreign_currency_exchange_travel_money` and its `workspace/` subdirectory. Index fixed by the pre-assigned output path (no auto-allocation).

## Step 2: Generate scaffold — 2026-09-05T03:28:00.000Z

All three scaffold artifacts are complete and lint-clean.

## Files
- `SCAFFOLD.yaml` (2967 lines) — top-level keys only: `scenario, domain_name, api_prefix, response_envelope, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles`. Neither `scaffold_difficulty_design` nor `scaffold_corner_design` appears.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1487 lines) — single key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` (4725 lines) — single key `scaffold_corner_design`.

## Counts
- §1.0–§1.7: 14 entities, 9 state machines, 2 concurrency rules, 16 calculations, 34 validations, 62 endpoints, 67 errors, 6 roles. Profile: `compliance_audit` + `quota_allocation`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`, topology `flat`, shape `parallel`, role model `segregation_of_duties`, consistency `immediate`.
- §1.8: 9 rule_ids / 20 instances.
- §1.9: 88 instances across all nine guide sections — entities 10, state_machines 18, calculations 15, validations 21, endpoints 11, errors 4, rbac 4, cross_cutting_complexity_layers 4, consistency_model 1. Of these, 61 are full test recipes and 27 are `excluded_because` stubs, each citing a §1.8 instance that exists by name.

## Verification
- `scaffold_lint.py` -> `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (62 endpoints, 14 entities, 20 + 61 instances, 1032 calls scanned).
- Independent structural checks: zero duplicate instance names across both design files; every stub has `name`/`claim_type`/`grounds`/`rationale` and no `test_recipe`; every full instance has `distinguishing_aspect` and a complete recipe; all 67 catalog error ids are triggered somewhere in §1.8/§1.9.
- Scenario text is stored verbatim, including the leading directive line and the numbered `2817.` sentence.

Notable design literals all pre-computed and cross-checked with a scratch verifier under `/tmp/task_2817_scaffold/` (EUR mid 920000 with 550/450 spreads -> buy 970600 / sell 878600; commission floor at 400 cents; vault bands at exactly 9000/10000 bps; buyback rate lock landing on 2026-09-01T00:00:00Z so the clock sweep is boundary-exclusive; CHF plan target 37500 -> 40000 via round-half-up to the largest note).

### Orchestrator post-step action
Per the entrance skill's difficulty-directive containment rule, the orchestrator stripped the line `Generate task harder than expert level!` (and its following blank line) from `SCAFFOLD.yaml`'s `scenario:` block so the difficulty directive cannot reach PRD.md via the doc generator. Verified: `grep -rn "harder than expert" tasks/task_2817_.../` now returns nothing. YAML re-parsed cleanly after the edit; top-level key set unchanged.

## Step 3: Copy shared files — 2026-09-05T03:28:30.000Z

Copied `./INSTRUCTION.md` -> `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T03:44:00.000Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — **459 lines**, built via 10 chunked appends (never a single giant Write). `tail -40` confirms it ends at a real section boundary: the final `| ERR_ROUTE_CAPACITY_EXCEEDED | 422 |` row of the §5 table. No audit footer, no contract reports in the file.

**Section list**
- §1 Introduction
- §2 Global Specifications: 2.1 Counter Staff, Head Office and Access Control / 2.2 API Response Structure (verbatim fixed block, byte-identical) / 2.3 Pagination / 2.4 Resource Identity, Audit Stamps and the Logical Trading Clock / 2.5 Integer Money, Micro-Rates and Rounding / 2.6 The Vault Posture Gate / 2.7 Reserve-and-Truncate Writes and Version Pinning / 2.8 The Order in Which a Request Is Refused / 2.9 Cascade Discipline / 2.10 Currency Handling Classes and the Disclosure Regime
- §3 Business Logic & Workflows (9 subsections): 3.1 Standing Up the Network / 3.2 The Wholesale Feed and the Retail Board / 3.3 Seasonal Stocking: Corridors, Plans and Treasury Review / 3.4 Opening a Currency Position and Keeping the Mix Honest / 3.5 The Counter: Quoting, Authorising, Settling, Voiding and Reversing / 3.6 Structuring Surveillance, Compliance Decisions and the Filing Cycle / 3.7 Buy-Back Guarantees and Rate Locks / 3.8 Counterfeit, Damaged and Obsolete Notes / 3.9 Cash Logistics: Armored Movement, Arrival Variance and Repatriation
- §4 Endpoint Definitions (62-row table)
- §5 Error Code Catalogue (67-row table)

**Coverage vs scaffold (all mechanically diffed):** endpoints 62/62 (table rows match scaffold method+path in order, all authorized roles present per row) · errors 67/67 (every row matches `id` + `http` exactly, and all 67 IDs also appear in §1–§3 narrative attached to their triggering condition) · calculations 16/16 · validations 34/34 (all with `applies_to` sets enumerated exhaustively in the §2.8 ladder) · state machines 9/9, 47/47 transitions · concurrency rules 2/2 · every state name and every enum constraint value appears in the narrative (0 missing).

Field coverage check: entities[].fields 132/132; endpoints[].request_body 79/79; query_params 34/34; path_params 1/1 — PASS.
Rule coverage check: validations 34/34; OCC rejections 2/2; transitions 47/47; calculations 16/16; validation->error_id 34/34; side_effects/applies_to 31/31; entity field structured content 161/161; sibling-branch symmetry 14/14 groups — PASS.
Path purity check (§3 only): 957 backtick tokens scanned, 0 leading-`/` tokens, 0 bare HTTP-method tokens, 0 method+path tokens — PASS.

Two notes worth relaying: (1) the auto-generated §4 description column initially leaked internal vocabulary — the literal word "scaffold" and the raw constant name `RATE_LOCK_DAYS` — from first-sentence extraction of scaffold descriptions; both were rewritten in place ("this specification", "a fixed 31-day term") and a re-grep is clean. (2) Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened or grepped, and no sibling task directory was read; all scratch stayed under `/tmp/task_2817_prd/`.

### Orchestrator truncation guard
Independently verified the known doc-generator truncation failure mode: `wc -l` = 459, `tail -15` ends on a complete `| ERR_... | 422 |` table row at the true end of §5, section headings present in order (§1 L3, §2 L11, §3 L168, §4 L318, §5 L387). Row counts re-counted by the orchestrator (see command output above). Difficulty-directive leak grep over PRD.md returned no matches. No regeneration needed.

## Step 6: Generate implementation — 2026-09-05T04:14:00.000Z

Implementation complete and verified.

## Files written (all under `workspace/implementation/`)

| File | Lines |
|---|---|
| `app.py` | 71 |
| `core.py` | 746 |
| `calc.py` | 615 |
| `routes/__init__.py` | 1 |
| `routes/reference.py` | 362 |
| `routes/rates.py` | 160 |
| `routes/inventory.py` | 242 |
| `routes/customers.py` | 169 |
| `routes/transactions.py` | 384 |
| `routes/buyback.py` | 214 |
| `routes/notes.py` | 167 |
| `routes/shipments.py` | 180 |
| `requirements.txt` | 1 |
| `start.sh` | 10 |
| **total** | **3322** |

Nothing empty or missing; `py_compile` clean on every module. Nothing was created at the task root, and `__pycache__` dirs were removed.

## Architecture
- `core.py` — 67-entry `ERRORS` registry, the in-memory store (`S = {kind: {}}`, one dict per entity kind, empty on every boot), logical clock anchored at `2026-08-01T00:00:00Z`, integer money helpers (`rhu` round-half-up / `fdiv`), the response envelope (`meta` + `response_type` + `data`), the `endpoint(roles)` decorator (rank-1 401 -> rank-2 403 -> path resolution, handler body under a global `RLock`), every body/query validator, and pagination.
- `calc.py` — the 16 calculations plus the cascades (four/five-hop inventory, surveillance, branch-posture rederivation, repatriation waterfall, liability reconciliation).
- `routes/*.py` — one blueprint per domain area, registered in `app.py`.
- Storage is plain Python dicts only: no SQLite, no disk files, no `/tmp` cache (`grep` confirms no `open(`, no `json.dump`, no `sqlite`). No entity is seeded, preloaded or hardcoded — a fresh boot answers `total_count: 0` on all 13 collection endpoints.
- `start.sh` reads `$PORT`, binds `0.0.0.0`, installs Flask only if missing, and `exec`s the server in the foreground.

## Coverage
- **62 endpoints** — registered route count verified as exactly 62, matched one-for-one against the PRD §4 table.
- **67 error ids** — `len(core.ERRORS) == 67`, each with its PRD-mandated HTTP status; conditions that the PRD leaves without a dedicated id fall back to `ERR_INVALID_REQUEST`.
- **16 calculations** — card-rate derivation, FX gross, per-line USD conversion, tiered commission, same-day settled basis, corridor targets, position/vault/utilisation rederivation, buy-back pricing, liability reconciliation, damaged-note recovery, manifest valuation, surveillance scoring, route capacity, rate-board projection, repatriation surplus waterfall.
- **34 validations** — implemented on the 13-rank precedence ladder, with the three pinned conflict pairs honouring PRD prose over the SCAFFOLD `priority` ordering, and both optimistic-concurrency checks (`expected_branch_version`, `expected_customer_version` -> 412) evaluated at rank 6, after existence and target-state.
- **9 state machines** — including the parallel `settlement_status` x `compliance_status` axes, the cyclic `SUBMITTED->DRAFT` and `FILED<->AMENDING` loops, the `IN_TRANSIT->{DELIVERED,EXCEPTION}->RECONCILED` fork-join, the derived `Branch.posture` aggregate gate, and re-entrant `PARTIALLY_REDEEMED`.

## Smoke test
Booted from a fresh process with `PORT=21861 bash start.sh &`, exercised over HTTP, then stopped with `kill <pid>` on the single recorded PID only (no pattern kill was ever issued). Results:
- `POST /branches` -> 201 with `version: 1`, `posture: OPEN`, `created_at: 2026-08-01T00:00:00.000Z` (logical clock, not wall clock), `home_currency_code: USD`, all derived money fields 0.
- `GET /branches?limit=1` -> `response_type: "array"` with `limit`/`offset`/`total_count`/`has_more` inside `meta`, exactly per PRD §2.2.
- Duplicate `code` -> `ERR_DUPLICATE_BRANCH_CODE` (409); missing headers -> `ERR_UNAUTHENTICATED` (401); `Customer` role on `GET /branches/nope` -> `ERR_UNAUTHORIZED` (403, proving permission precedes path resolution) while `PlatformAdmin` on the same path -> `ERR_BRANCH_NOT_FOUND` (404).
- A longer end-to-end script covered quote -> authorize -> settle -> reverse, buy-back issue/redeem/supersede, note assessment (all three outcomes), shipment schedule/dispatch/arrive-with-variance/reconcile, auto-repatriation on a breached vault ceiling, inventory-plan submit/review/activate, threshold- and counterfeit-report file/amend, and the clock-sweep expiry endpoint. Hand-checked figures all matched: quote 5x EUR100 at sell 897000 -> 55,741c + 1,394c commission = 57,135c; buy-back fee 1,672c with liability 53,022c -> 31,813c after a partial redemption; auto-repatriation surplus 1,270,932c -> 187 x JPY10,000 manifest; damaged-note recovery 52,589c. Reversal correctly restored the note mix, reset the customer's aggregates to `NORMAL`, and left `compliance_hold_active` true.

Two apparent failures during the final smoke run were bugs in the agent's throwaway curl commands, not the implementation: it sent `branch_code`/`display_name` instead of the PRD's `code`/`name`, and hit `/regulatory-reports` instead of the PRD's `/compliance-reports`. Both endpoints behave correctly when called as specified.

## Step 5: Generate unit tests — 2026-09-05T05:22:00.000Z

All queue A and queue B instances are now translated; the suite is complete.

## Files written (all at the task root, nothing under `workspace/`)

`test_helpers/` — 9 files, 2684 lines: `__init__.py` 96, `api_client.py` 316, `api_errors.py` 162, `assertions.py` 491, `constants.py` 163, `factories.py` 376, `fixtures.py` 703, `test_users.py` 71, `types.py` 306.

`test_suite/` — `conftest.py` 63 plus 20 test modules, 6430 lines: test_01 207, test_02 192, test_03 147, test_04 224, test_05 232, test_06 198, test_07 152, test_08 202, test_09 207, test_10 554, test_11 407, test_12 438, test_13 497, test_14 376, test_15 454, test_16 403, test_17 515, test_18 413, **test_19_corner_rbac.py 388**, **test_20_corner_cross_cutting.py 224**.

## Tests per queue

- Queue A (§1.8 difficulty): **40 tests** across test_01–test_09, covering **20/20** rule instances.
- Queue B (§1.9 corner): **61 tests** across test_10–test_20, covering **61/61** non-stub instances (entities 10, state_machines 13, calculations 9, validations 14, endpoints 5, errors 4, rbac 4, cross_cutting 1, consistency 1).
- Total 101 tests, 101 `Design:` tags, one tag per test, all resolving to a real `name:` in the source yaml; none of the 27 `excluded_because:` stubs was translated.

test_19 covers 401 outranking 403/404; the seven-probe 403 matrix incl. 403-before-404; the six-role positive pass; segregation binding only submit/review while activate and lone-teller authorize+settle stay legal. test_20 covers both version pins rejecting stale tokens with no supersession; immediate consistency of the settle body plus the first reads of position/branch/customer.

## Instances skipped

**None.** Every non-stub instance in both indices passed the PRD-first two-condition filter and was emitted. No `skip`/`xfail`/placeholder appears anywhere in the suite.

## Deliberate PRD-over-index deviations (asserted per PRD.md, not per the index)

(a) `computed_targets` entries carry only `currency_code` + `target_minor_units`; (b) `total_target_usd_equivalent_cents` is not a PRD field; (c) `activated_at` is not a PRD field; (d) post-REJECT `reviewed_by_user_id` is the reviewer, not null; (e) 3x10000 BUY commission/total is 773/30136, not 1082/29827 (four sites, incl. test_20); (f) `ERR_SHIPMENT_WINDOW_NOT_OPEN` at 409 not 422; (g) bare-date season fields rendered as full instants; (h) an extra MAD wholesale quote in one plan-rejection setup; (i) `ECB_FIX` -> `INTERBANK_CLOSE`; (j) CHF 22954/803/23757 not 22960/804; (k) the `minor_unit_digits: 1` sub-case omitted as PRD-silent; (l) transaction-listing page contents asserted as sets, since every row shares `created_at`; (m) plan `target_lines` compared as a currency->baseline mapping, order being unpinned; (n) the segregation test registers a CHF wholesale mid (912345) that the index's setup omits, because PRD 3.3's vault-cap step needs a mid for the line's currency before CHF->40000 is derivable; (o) the index's "settlement takes Branch.version to 4" is asserted as a +1 delta, since the PRD does not state whether publish bumps the branch version; (p) `vault_utilization_bps` 98 in the positive RBAC matrix (round-half-up of 195652/20,000,000), a value the index left unstated.

Verification run: `py_compile` clean on all 30 files, no `scaffold`/§ references in emitted code, no `skip`/`xfail`/`TODO`, every module docstring quotes PRD.md, and `workspace/` contains only `INSTRUCTION.md`, `PRD.md` and the parallel agent's `implementation/` (untouched and unread by the test generator).

### Orchestrator post-step verification
Confirmed `test_helpers/` and `test_suite/` both live at the task root (not under `workspace/`); `workspace/` holds exactly `INSTRUCTION.md`, `PRD.md`, `implementation/`. `test_suite/` = 21 files. Independent tag census: 40 `Design: Difficulty` + 61 `Design: Corner` = 101, matching 101 collected `def test_` functions. Zero `pytest.mark.skip`/`xfail` occurrences across both directories. Stray `__pycache__` dirs removed before the sweep.

## Step 7: Run tests and iterate — 2026-09-05T05:50:00.000Z

Clean sweep achieved. Summary:

## Iterations run: 2

**Iteration 1** — all 8 parallel rounds: 97/101 passed, 4 failures, identical in every round (fully deterministic, no flakiness). **Iteration 2** — all 8 parallel rounds: **101/101 passed** (187s per round).

## Failing tests (union across 8 rounds), and their two root causes

1. `test_01::test_structuring_report_cites_the_calendar_month_variant`
2. `test_04::test_the_second_settlement_runs_aggregates_score_tier_report_and_hold`
3. `test_16::test_the_hold_release_waits_on_a_report_in_another_aggregate`
4. `test_16::test_the_origin_triad_the_redemption_ceiling_and_the_reversal_lock`

## Tests deleted: none

Both defects passed STEP 1a (verbatim PRD coverage) and STEP 1b (unique derivability); no PRD-silence or collapse pattern applied.

## Fixes applied to `implementation/`

- `workspace/implementation/calc.py` — `raise_structuring_report()`: added a `triggering_transaction_id` parameter and forwarded it into `create_report()`. It previously created every `STRUCTURING_SUSPICION` report with a null pointer.
- `workspace/implementation/routes/transactions.py` — `settle_transaction()`: passes `transaction["id"]` into `raise_structuring_report(...)`.

PRD §3.6 verbatim: *"`triggering_transaction_id` names the settlement that raised the report and is null on a `COUNTERFEIT_SEIZURE`, while `note_assessment_id` names the assessment that raised it and is null on both settlement-driven types."* `STRUCTURING_SUSPICION` is one of the two settlement-driven types, so its `triggering_transaction_id` must name the settlement that pushed the customer into `HIGH` — the only PRD-faithful reading. This single defect caused failures 1, 2 and 3 (3 tripped `assertions.assert_compliance_report`'s `is_valid_uuid(triggering_transaction_id)` branch; 2 tripped `assert None == '<uuid>'`).

## Fixes applied to `test_suite/`

- `test_suite/test_16_corner_validation_cross_entity.py`, `test_the_origin_triad_the_redemption_ceiling_and_the_reversal_lock` — the CHF sale's expected settlement commission was hardcoded as the **quote-time** figure (`803` = 350 bps on its own 22954-cent gross, total 23757). PRD §3.5 pins the settlement tier basis as *"this deal's `settled_usd_gross_cents` **plus** the sum of `settled_usd_gross_cents` over the same customer's other transactions that have `settlement_status` `SETTLED`, the same `branch_id`, and a `settled_at` falling on the same UTC calendar day"* — and the fixture settles a 22763-cent EUR sale to the same customer at the same branch on the same day first. The basis is therefore 45717 cents, which selects the 250-bps band: `574` cents commission, `23528` total. Corrected the assertion to the PRD-derived values (a *more* faithful assertion, not a weakened one — exact cent values retained) with an inline comment citing the rule. Note the PRD's basis is branch/customer/day-scoped and deliberately **not** currency-scoped, so the EUR sale counts toward the CHF deal's basis.

## Fixes applied to `test_helpers/`: none

`assertions.assert_compliance_report` was already faithful to PRD §3.6 and correctly caught the implementation defect.

Diagnostic notes for the record: no load-induced or timing-sensitive failures appeared in either sweep — both iterations were bit-identical across all 8 concurrent rounds, and no round showed `Terminated`/reaping symptoms. The private diagnostic server used for tracebacks ran on port 21817 and was killed by PID; no stray processes or files remain, and `worklog.md` was not touched.

### Orchestrator post-step verification
Independently confirmed the final sweep artifacts exist and are real rather than claimed: `results.1..8.json` all present (mtime 05:39, ~29.9 KB each), each parsing to `total: 101, passed: 101, failed: 0, errors: 0, skipped: 0` with 101 per-test entries and `duration_seconds` ~187 — a genuine full round, not a truncated or stale file. Step 7 applied 2 `implementation/` fixes, so Step 8 is NOT skipped.

## Step 8: Finalize PRD — 2026-09-05T05:53:00.000Z

Verified both Step 7 items against `implementation/`; neither reveals PRD silence or PRD/impl divergence, so `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md`.

## Line counts
- `PRD.md`: 459 lines
- `PRD_FINALIZED.md`: 459 lines — **0% delta**, md5 identical (`7b512768b89a64653ab087bd6f7589df`)

## Changes
None. Zero non-cosmetic edits (and zero cosmetic ones).

## Per-item analysis (pre-edit search log — searches run, no edit committed)

**Item 1 — `calc.py::raise_structuring_report()` + `routes/transactions.py::settle_transaction()` gained `triggering_transaction_id`**
- (a) Subject: which pointer field a `STRUCTURING_SUSPICION` `ComplianceReport` populates, and with what value.
- (b) Impl paths enumerated: `implementation/calc.py:560-585` (`create_report` — the single report factory, sets both pointers, `status=DRAFT`, `amendment_count=0`), `calc.py:586-596` (`has_outstanding_structuring_report`), `calc.py:599-622` (`raise_structuring_report` — window from `calendar_month_window()`, aggregate from `customer["calendar_month_settled_usd_cents"]`, count from `settled_count_in_window`), `routes/transactions.py:255` (only callsite of `raise_structuring_report`, from `settle_transaction`), `routes/transactions.py:260-269` (`THRESHOLD_REPORT` creation, same pointer), `routes/notes.py:132` (`COUNTERFEIT_SEIZURE` creation — sets `note_assessment_id`, leaves `triggering_transaction_id` null), `routes/transactions.py:325-336` (reversal deletes only `DRAFT` `THRESHOLD_REPORT`s pointing at the transaction — confirms reversal never raises a structuring report, consistent with aggregates only ever falling), `routes/customers.py:164` (report list filter mapping). Also grepped PRD lines 242, 254, 260, 262, 378 for every mention of the pointer.
- Verdict: PRD §3.6 line 260 already states verbatim that `triggering_transaction_id` "names the settlement that raised the report and is null on a `COUNTERFEIT_SEIZURE`", and §3.6 line 254 pins the one-report-per-outstanding-report and report-causes-hold rules. The pre-fix impl was a plain bug against pinned prose; the post-fix impl now matches it exactly. Nothing left open.
- (c) No wording adjustment — no edit.

**Item 2 — `test_suite/test_16` CHF sale settlement commission expectation corrected to 574 / 23528**
- (a) Subject: the settlement-variant commission tier basis (scope of the summed same-day volume).
- (b) Impl paths enumerated: `calc.py:110-128` (`same_day_settled_basis` — self excluded by `id`, filters on `customer_id`, `branch_id`, `settlement_status == "SETTLED"`, `utc_date(settled_at)` equality; no currency filter), `calc.py:93-107` (`commission_and_total` — tier ceilings, `PREMIUM` +50 bps, `max(400, rhu(...))` floor, sign by direction), `routes/transactions.py:228-236` (settle callsite: `settlement_status`/`settled_at` written before the basis call, so self-exclusion is by id not status), plus the quote-time callsite that passes the deal's own gross as basis. Cross-checked arithmetic: basis 22954+22763 = 45717 -> 250 bps -> `rhu(22954*250,10000)` = 574, total 23528 — matches impl output.
- Verdict: PRD §3.5 line 234 pins the basis verbatim as "this deal's `settled_usd_gross_cents` **plus** the sum of `settled_usd_gross_cents` over the same customer's *other* transactions that have `settlement_status` `SETTLED`, the same `branch_id`, and a `settled_at` falling on the same UTC calendar day", explicitly with no currency scoping. Pure fixture bug (hardcoded quote-time figure); the impl was already correct and PRD-faithful.
- (c) No wording adjustment — no edit.

Key finding: an identical `PRD_FINALIZED.md` is the correct outcome here — Step 7's single implementation fix moved the code *toward* prose the PRD already pinned uniquely, and its only test fix corrected a fixture's arithmetic, so there is no silence to close and no mismatch to reconcile.

### Orchestrator note
A byte-identical `PRD_FINALIZED.md` is legitimate at Step 8 when Step 7's implementation fixes only moved code toward already-pinned prose. Step 9, by contrast, must NOT come out identical — it is a full impl-wide scan, so the orchestrator will run it as three sequential module-partitioned passes over one shared `PRD_COMPLETED.md` (pass 1 performs the `cp`; passes 2 and 3 must not) and will verify the result differs from `PRD_FINALIZED.md`.

## Step 9: Complete PRD — 2026-09-05T06:35:00.000Z

Run as three sequential module-partitioned passes over one shared `PRD_COMPLETED.md` (pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edited in place, additively), plus one targeted follow-up edit routed back to the pass-1 agent. Partition: pass 1 = `app.py` + `core.py` + `routes/reference.py` + `routes/rates.py`; pass 2 = `calc.py` + `routes/inventory.py` + `routes/customers.py`; pass 3 = `routes/transactions.py` + `routes/buyback.py` + `routes/notes.py` + `routes/shipments.py`.

### Totals
- `PRD_FINALIZED.md` 459 lines / 116,024 chars -> `PRD_COMPLETED.md` 459 lines / **141,681 chars** (**+25,657 chars**, +22.1%). Line count unchanged: every edit is an in-paragraph insert or revision, no new sections.
- 136 diff-line hunks / 67+ lines differing from `PRD_FINALIZED.md`.
- Edit counts: pass 1 = 17 ambiguity-pins + 4 mismatch-revisions (21); pass 2 = 19 + 3 (22); pass 3 = 26 + 8 (34); follow-up = 1 mismatch-revision. **Total 78 edits — 62 ambiguity-pins, 16 mismatch-revisions.**

### Pass 1 (app.py, core.py, routes/reference.py, routes/rates.py) — 21 edits
- §2.1 — revise — ambiguity — an empty auth header counts as absent and the role match is case-sensitive — core.py:462-467
- §2.1 — insert — ambiguity — the acting `X-User-ID` is never resolved to a `Customer` row on the three reads that role may perform — core.py:456-476, reference.py:124,217,223
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — core.py:405-413
- §2.2 — insert — ambiguity — `api_request_timestamp` is real wall-clock, the one stamp not reading the logical clock — core.py:416-424
- §2.3 — insert — ambiguity — empty `limit`/`offset` treated as absent; non-decimal-integer values refused — core.py:654-671
- §2.3 — insert — ambiguity — `created_at` ties broken by server creation sequence, oldest first — core.py:368-369
- §2.3 — insert — ambiguity — filters are exact-match; empty/unknown params ignored; bool filters accept only true/1/false/0 case-insensitively — core.py:682-716
- §2.4 — insert — ambiguity — `version` bumps at most once per request; rows created in a request are never re-bumped by a cascade — core.py:317-357
- §2.4 — revise — **mismatch** — "Five reference resources" -> "Four" — reference.py:203,244,300,343
- §2.4 — insert — ambiguity — explicit `null` == absent; server stamps canonical, client-supplied instants stored/echoed byte-for-byte and normalised only for comparison — core.py:496-498,576-591; reference.py:247
- §2.4 — revise — ambiguity — clock call returns exactly `{current_utc, expired_contract_count}`, echoes the raw string, accepts backwards moves — reference.py:50-73
- §2.5 — insert — ambiguity — `minor_unit_digits` accepted only as 0-4 and read by no formula — reference.py:175
- §2.7 — insert — ambiguity — `expected_branch_version` below 1 / non-integer is rank-4 `ERR_INVALID_REQUEST`, not 412 — rates.py:50
- §2.8 rank 4 — insert — ambiguity — strict JSON integer/non-empty-string typing; duplicate `iso_code`/corridor `code`/route `code` are rank-4 `ERR_INVALID_REQUEST` (only branch code gets a 409) — core.py:500-548; reference.py:200-202,297-299,340-342
- §2.10 — insert — ambiguity — board `lines` ordered by `currency_code` asc with exactly nine named fields; `min_disclosure_text_version` is 0 when empty; the `currency_code` filter is never resolved against the catalogue — reference.py:130-161
- §3.1 — insert — **mismatch** — `home_currency_code` accepts any non-empty string verbatim, unvalidated and never forced to USD — reference.py:87,96
- §3.2 — insert — ambiguity — wholesale list ties broken by `created_at` desc then creation sequence desc — reference.py:262-263
- §3.2 — insert — ambiguity — wholesale-quote/card currency mismatch is `ERR_INVALID_REQUEST` — rates.py:57-61
- §3.2 — insert — ambiguity — publish evaluates DRAFT -> window overlap -> disclosure version (overlap beats `ERR_DISCLOSURE_VERSION_UNSUPPORTED`) — rates.py:114-135
- §3.3 — insert — **mismatch** — corridor country-code format is checked before `destination_currency_code` is resolved, so a bad country code beats the 404 — reference.py:287-290
- §4 — insert — **mismatch** — trailing slash insignificant; unrouted path -> `ERR_INVALID_REQUEST` at 404 and unsupported method -> `ERR_INVALID_REQUEST` at 405, both decided by routing before rank 1 — app.py:28,46-53

### Pass 2 (calc.py, routes/inventory.py, routes/customers.py) — 22 edits
- §2.6 — insert — ambiguity — post-credit vault projections re-value the credited position in one conversion from its post-credit `total_minor_units` — calc.py:257
- §2.6 — revise — **mismatch** — branch recomputation writes `updated_at`/`version` only when one of the four derived values actually changed — calc.py:228-253
- §2.6 — insert — ambiguity — `FROZEN -> RESTRICTED` is not a repatriation trigger even with `repatriation_pending` false — calc.py:241
- §2.9 — revise — ambiguity — wholesale-mid tiebreak beyond `created_at` desc is creation sequence, newest first — calc.py:59
- §2.9 — insert — ambiguity — the mix grows on demand: an unknown denomination on a redemption/arrival appends a zeroed entry then adjusts; only settlement refuses with `ERR_DENOMINATION_NOT_STOCKED` — calc.py:188-199
- §3.3 — insert — ambiguity — `target_lines` entry rules: objects, `baseline_daily_minor_units` integer >= 0, duplicate currency malformed, currencies all resolved before any baseline is inspected, stored sorted by `currency_code` — inventory.py:97-123
- §3.3 — insert — ambiguity — an explicitly empty `target_lines` on submit is written before the emptiness check, so the 422 leaves the plan with no lines and no version bump — inventory.py:157-163
- §3.3 — revise — ambiguity — `REJECT` keeps the submission's `computed_targets`; `review_note` written as null when absent — inventory.py:179,191-193
- §3.3 — insert — ambiguity — activation does not recompute `computed_targets` — inventory.py:198-212
- §3.3 — insert — ambiguity — a target-line currency with no effective wholesale quote fails `ERR_WHOLESALE_RATE_NOT_FOUND` after the state/target-line checks, leaving `computed_targets` and `status` unchanged — calc.py:138
- §3.4 — insert — ambiguity — `opening_denomination_mix` must be non-empty with distinct denominations >= 1; `note_count` wins over `available_note_count`; 0 accepted; not checked against `standard_denominations` — inventory.py:48-54, core.py:614
- §3.4 — insert — ambiguity — no operation ever moves a position to `CLOSED` — verified absence across all routes
- §3.4 — insert — ambiguity — branch version bumps on position creation regardless of the cascade; a missing wholesale quote 404s after the duplicate check yet the position row is kept, so a retry hits `ERR_POSITION_ALREADY_EXISTS` — inventory.py:73-75
- §3.5 — revise — ambiguity — `nationality_code` is exactly two uppercase letters, format-checked only — customers.py:47
- §3.5 — insert — ambiguity — `home_branch_id` is only resolved: no status/posture check, no branch version bump — customers.py:44,69
- §3.6 — insert — **mismatch** — all four aggregates are re-derived from scratch against the clock at recomputation time, so a reversal after the clock moved does not literally restore pre-settlement figures — calc.py:319-355
- §3.6 — insert — ambiguity — a `STRUCTURING_SUSPICION` cites `window_start` = first instant of the UTC month, `window_end` = the clock — calc.py:381-383
- §3.6 — insert — ambiguity — `transaction_count` counts the customer's SETTLED rows at **any** branch in the window; reports born `DRAFT` with null `filing_reference`/`filed_at` and `amendment_count` 0 — calc.py:386-396,581-584
- §3.6 — revise — ambiguity — `amendment_reason` validated but persisted nowhere; amend retains `filed_at` and `filing_reference` — customers.py:141-146
- §3.6 — revise — ambiguity — hold `reason` validated but stored nowhere; either action accepted when the flag already reads that value — customers.py:91-98
- §3.7 — insert — **mismatch** — liability reconciliation writes the branch only when the recomputed total differs — calc.py:423-425
- §3.9 — revise — ambiguity — repatriation candidate ties break by `created_at` asc then creation sequence asc; a manifest may come out empty and the zero-valued shipment is still raised with `repatriation_pending` true — calc.py:289,298-312

### Pass 3 (routes/transactions.py, buyback.py, notes.py, shipments.py) — 34 edits
- §2.7 — insert — ambiguity — `expected_customer_version` must be an integer >= 1; a non-integer is rank-4 malformed, not stale — buyback.py:46
- §2.8 rank 4 — revise — **mismatch** — non-standard-denomination rejection extended from "requested or returned" to requested/returned/manifested/delivered, with `opening_denomination_mix` named as the sole exemption — shipments.py:44,111; buyback.py:127; transactions.py:65
- §2.8 rank 12 — insert — ambiguity — on assess both rank-12 checks apply only to `EXCHANGED_AT_DISCOUNT`; settlement can never report `ERR_RATE_CARD_NOT_PUBLISHED` — notes.py:106-108; transactions.py:199
- §2.8 rank 13 — insert — ambiguity — the two settle checks are interleaved per denomination in ascending face value, not run as two sweeps — transactions.py:215-220
- §3.5 quoting — insert — ambiguity — card/branch/currency mismatch is `ERR_INVALID_REQUEST` at rank 4, ahead of branch status and card publication/window — transactions.py:66-70
- §3.5 quoting — insert — ambiguity — the nine settlement-side fields are born null; a quote stamps neither branch nor customer — transactions.py:100-113
- §3.5 authorising — insert — ambiguity — preconditions are narrative-ordered but rank-evaluated; FROZEN posture and compliance hold beat an expired quote — transactions.py:123-155
- §3.5 authorising — insert — ambiguity — ID gates sit behind the compliance-hold check; export-limit and exotic-plan sit at rank 11 after quote expiry — transactions.py:134-168
- §3.5 authorising — insert — ambiguity — PENDING->FLAGGED only from PENDING; authorisation stamps the transaction row alone and recomputes no aggregates — transactions.py:170-176
- §3.5 settling — insert — ambiguity — with no effective card the dual-control comparison is never made and `ERR_RATE_CARD_NOT_EFFECTIVE` wins despite rank 9 < rank 12 — transactions.py:199-210
- §3.5 settling — revise — **mismatch** — [deferred (i)] `ERR_DENOMINATION_NOT_STOCKED` applies in both directions; `ERR_INSUFFICIENT_INVENTORY` only to sells — transactions.py:212-220
- §3.5 settling — revise — **mismatch** — the row's `applied_rate_micros` is never rewritten at settle — transactions.py:228-232
- §3.5 settling — insert — ambiguity — THRESHOLD_REPORT is created last, after any structuring report, so it orders second — transactions.py:252-269
- §3.5 voiding — insert — ambiguity — `void_reason` validated before the state check and persisted nowhere — transactions.py:280-283
- §3.5 reversing — insert — ambiguity — `reversal_reason` likewise validated and persisted nowhere — transactions.py:296-297
- §3.5 reversing — revise — **mismatch** — [deferred (ii)] compensation is a delta, not a restore: no stock/vault re-check, counts may go negative, mix entries grow on demand, and with no position no notes move yet the call succeeds — transactions.py:313-323
- §3.5 reversing — revise — **mismatch** — [deferred (ii)] aggregates re-derived from the surviving SETTLED population at the reversal-time clock; a reversal never raises a structuring report — transactions.py:325-326
- §3.6 compliance decisions — insert — ambiguity — `decision_note` persisted nowhere; `settlement_status` never consulted; only the transaction row stamped — transactions.py:341-357
- §3.6 reports — insert — ambiguity — [deferred (iii)] THRESHOLD_REPORT and COUNTERFEIT_SEIZURE windows are zero-width (`window_start == window_end`) — transactions.py:260-269; notes.py:130-141
- §3.6 reports — insert — ambiguity — seizure `aggregate_usd_cents` is face minor units over the wholesale mid, rounded half up — never the card's `buy_rate_micros` — notes.py:129,138
- §3.6 reports — insert — ambiguity — seizure `customer_id` comes from the cited transaction (null if gone); `branch_id` is the detaining branch — notes.py:131-135
- §3.7 issuance — insert — ambiguity — `ERR_CONTRACT_ALREADY_ISSUED` whatever status the predecessor holds — buyback.py:48-50
- §3.7 issuance — revise — **mismatch** — incumbent's remaining/liability zeroed; matching ignores branch; oldest-first sweep; each incumbent's own branch reconciled before the new branch — buyback.py:91-113
- §3.7 redemption — insert — ambiguity — no position -> no notes move and the projection adds a separately-rounded wholesale increment (sole exception to §2.6's projection shape) — buyback.py:141-149,165-169
- §3.7 cancellation — insert — ambiguity — `cancellation_reason` persisted nowhere — buyback.py:179
- §3.8 creation — insert — ambiguity — position/branch mismatch, missing mix entry and insufficient notes are all rank-4 `ERR_INVALID_REQUEST` 400, not the rank-13 fiscal codes; the cited transaction is only resolved; the denomination need not be standard — notes.py:52-61
- §3.8 assess — insert — ambiguity — `assessment_note` persisted nowhere — notes.py:92
- §3.8 CONFISCATED — insert — ambiguity — position row stamped, branch row unstamped — notes.py:114-126
- §3.8 RETURNED — insert — ambiguity — same stamping outcome — notes.py:117-118
- §3.9 creation — revise — **mismatch** — the gate tests `RESTRICTED` exactly, so a FROZEN branch may still replenish; no posture blocks REPATRIATION; administrative status unchecked; four result fields born null — shipments.py:46-49
- §3.9 creation — insert — ambiguity — no effective wholesale quote -> `ERR_WHOLESALE_RATE_NOT_FOUND` 404 after the posture gate, and no row survives — calc.py:446-474
- §3.9 scheduling — insert — ambiguity — route status/region are rank 11 while window separation is rank 10, so a suspended-route + crowded-window request reports `ERR_ROUTE_WINDOW_CONFLICT` — shipments.py:69-78
- §3.9 arrival — insert — ambiguity — `delivered_denominations` mandatory but may be empty or all-zero; distinctness and standard-denomination checks still enforced — shipments.py:106-111
- §3.9 arrival — insert — ambiguity — unguarded REPATRIATION decrement may go negative; no position -> no hops at all, yet the arrival succeeds and the branch version still bumps — shipments.py:129-140
- §3.9 reconciliation — insert — ambiguity — no notes move, no payload; branch stamped only on the flag-clearing REPATRIATION-out-of-EXCEPTION path — shipments.py:150-158

Pass 3 resolved all three items pass 2 deferred to it: (i) the §3.5 `ERR_DENOMINATION_NOT_STOCKED` direction claim, (ii) §3.5's "fall back to pre-settlement values" reversal wording, (iii) the `COUNTERFEIT_SEIZURE` zero-width report window.

### Follow-up edit (orchestrator-routed, 1 mismatch-revision)
Pass 3 surfaced one residual mismatch living entirely in `core.py` — pass 1's module — and correctly declined to edit it rather than risk contradicting pass 1. The orchestrator routed it back to the still-live pass-1 agent, which re-verified it (read-only plus an in-process Flask test client, no ports bound) and confirmed it reproduces:
- §2.8 rank 3 — revise — **mismatch** — existence checks are not hoisted above rank 4 wholesale: an endpoint validates its declared body fields in declaration order, so a rank-4 malformedness in a field declared *before* a foreign-key or `currency_code` reference is reported as `ERR_INVALID_REQUEST` even though the later reference resolves to no live row, and a foreign-key field that is itself absent or not a non-empty string is likewise `ERR_INVALID_REQUEST` rather than its 404 — `core.py:378-382,395-399,500-508`.
- The agent explicitly avoided the false universal ("rank 4 always beats rank 3 in the body"): it verified that rank 3 still wins when the unresolvable reference is declared *earlier* than the malformed field (nonexistent currency + out-of-range `buy_spread_bps` -> 404; nonexistent `customer_id` + bad `direction` -> 404; unknown `target_lines` currency + `season_days: 0` -> 404), and the committed wording is scoped positionally to match. Handlers cross-checked for generality: rates.py:40-56, reference.py:284-296, transactions.py:56-70, inventory.py:45-47/97-125/130-134, notes.py:43-51, buyback.py:44-46, customers.py:43-48.

### Orchestrator post-step verification
`PRD_COMPLETED.md` exists and is **not** byte-identical to `PRD_FINALIZED.md` — the failure mode where the scan silently never ran. Measured independently: 459 lines / 141,681 chars vs 459 / 116,024, `diff` reporting 136 changed lines. Each pass confirmed it made no `cp`/`Write` into the shared file and that prior passes' marker phrases survived (pass 2 grepped 19 of pass 1's, pass 3 grepped 4 spanning both). No pass read `SCAFFOLD*.yaml` or `worklog.md`; no sibling task directory was read. `implementation/`, `test_suite/` and `test_helpers/` were not modified by any Step 9 pass, so Step 7's clean 8-round sweep artifacts (`results.1..8.json`, 101/101 each) remain the valid verdict for this task.

## Pipeline complete — 2026-09-05T06:35:00.000Z
All nine steps finished. Final state: 101/101 tests passing across all 8 concurrent sweep rounds; `PRD.md`, `PRD_FINALIZED.md` (identical to PRD.md, legitimately) and `PRD_COMPLETED.md` (+22.1% chars, 78 pinning edits) all present in `workspace/`.
