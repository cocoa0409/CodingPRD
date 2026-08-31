# Worklog — task_2147_food_recall_effectiveness

## Step 1: Create task directory — 2026-08-24T14:32:28.727Z

Created `tasks/task_2147_food_recall_effectiveness/` and `tasks/task_2147_food_recall_effectiveness/workspace/`.

## Step 3: Copy shared files — 2026-08-24T14:32:55.000Z

Copied `INSTRUCTION.md` -> `tasks/task_2147_food_recall_effectiveness/workspace/INSTRUCTION.md` (1424 bytes).

## Step 2: Generate scaffold — 2026-08-24T15:39:00.000Z

All three artifacts are generated and pass the skill's linter.

## Generated files
- `SCAFFOLD.yaml` (§1.0–§1.7, 117 KB)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8 only)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9 only)

## Contents

**Profile** — `compliance_audit` × `ledger_reconciliation`; layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; topology `graph` (self-referential Consignee tree + junction rows); shape `parallel`; role model `segregation_of_duties`; `api_prefix: "/"` (flat top-level collections, one level of sub-resource).

**Scale** (deliberately above the Expert band per the "harder than expert" instruction):
- **12 entities**: Firm, Recall, HazardEvaluation, Consignee (self-FK, 3-tier cap), DistributionRecord, ConsigneeNotification, RetrievalReceipt, PublicWarning, DispositionOrder, StatusReport, CostEntry, InsuranceClaim
- **10 state machines / 53 transitions** — Recall (cyclic: TERMINATION_REQUESTED→RETRIEVAL_ACCOUNTING, self-loop reclassify), HazardEvaluation (SUBMITTED<->RETURNED cycle + SUPERSEDED), ConsigneeNotification (**parallel** delivery_state x response_state), DistributionRecord (branching CONFIRM/DISPUTE/CORRECT/VOID with cycles), PublicWarning (review-reject cycle), DispositionOrder (verify-reject cycle), StatusReport, CostEntry (ACCEPT<->REJECT), InsuranceClaim (supplement cycle), RetrievalReceipt
- **2 concurrency rules** — OCC on `Recall.version` (hazard-eval create) and on `Consignee.version` (notification dispatch), both 412
- **8 calculations** — hazard_score_and_class (PRELIMINARY vs RATIFIED variants), effectiveness_sample_scope, effectiveness_percentage (CONTACT vs QUANTITY variants, agency-selected), recall_cost_accumulation (per-line rounding pinned), insurance_settlement (sublimit -> tier -> deductible -> aggregate-clamp -> fee, order pinned), report_cadence_schedule, compliance_posture, notification_aging_and_cooling_off
- **33 validations** in a single strict precedence ladder (auth -> existence -> tenant scope -> schema -> OCC -> 9 state rows -> safety -> referential -> temporal -> constraint -> fiscal)
- **53 endpoints** (incl. `GET /recalls/{id}/effectiveness` computed read and `POST /_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` startup default)
- **33 error codes**, **5 roles** (1 `entity_backed:Firm`, 4 `opaque`)

**§1.8** — 9 rule_ids x exactly 2 instances = **18**. Notable: depth-4 reclassify cascade (cadence -> report re-date -> OVERDUE flip -> posture escalation), depth-3 receipt-verify cascade (accounting -> EFFECTIVENESS_REVIEW -> FINAL report mint), hazard score exactly 70.00 vs 69.00, empty-sample 100.00 vs zero-shipped 0.00, half-open report windows vs buffer-expanded contact windows, unit-conservation vs cents-conservation invariants.

**§1.9** — **60 instances** across all 9 guide sections (51 with full recipes + 9 `excluded_because` stubs, each citing a real §1.8 instance name).

**Lint** (pasted verbatim):
```
Coverage
  §1.5 endpoints declared:    53
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     51
  Calls scanned (§1.8+§1.9):  697

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Additional verification run beyond the linter: all 78 instance names unique across both files; every `grounds:` ref resolves to a declared calculation/error/validation-priority/entity-field/state-machine/role/concurrency-rule; all 9 stub targets exist in §1.8; enum-value closure checked entity by entity; zero forbidden concurrency vocabulary; every formula-derived assert literal computed by hand against the pinned constants (e.g. 87.40->48.07, 3x3716=11148, capped 15733716 -> 0.85 -> 11248659 + 337460 = 11586119). No sibling task directories were read.

## Step 4: Generate PRD — 2026-08-24T15:48:00.000Z

PRD generated at `workspace/PRD.md`.

**Line count:** 355 lines. Built with 5 incremental appends (no single oversized Write), so no section was truncated — the file ends at the §5 error table with no audit footer.

**Section list**
- §1 Introduction (4 paragraphs: business context, segregation-of-duties framing, dual-basis measurement, root mount + logical clock)
- §2 Global Specifications — 2.1 Acting Identity and RBAC · 2.2 API Response Structure (verbatim from `section-2.2-response-structure.md`, byte-identical) · 2.3 Pagination and List Ordering · 2.4 Case Record Identity, Versioning and the Logical Clock · 2.5 Optimistic Concurrency on Parent Records · 2.6 The Rejection Ladder (all 33 rungs, ordered) · 2.7 Arithmetic Discipline · 2.8 Cascade Discipline and Derived Case Counters · 2.9 Path Resolution and Sub-Resource Addressing
- §3 Business Logic — 3.1 Opening the Case: Firms, Recalls, Distribution Tree · 3.2 Hazard Evaluation and Panel Ratification · 3.3 Classification, Sampling Scope and Reporting Cadence · 3.4 Distribution List Reconciliation · 3.5 Consignee Notification: Two Independent Dimensions · 3.6 Press Release / Public Warning Decision · 3.7 Retrieval Accounting, the Two Effectiveness Bases, Disposition Custody · 3.8 Reporting Cadence, Checkpoints and Compliance Posture · 3.9 Cost Accumulation, Insurance Settlement and Closing the Case
- §4 Endpoint Definitions (4-column table) · §5 Error Code Catalogue (2-column table)

**Coverage verification (machine-checked against SCAFFOLD.yaml)**

| Scaffold table | Required | Represented |
|---|---|---|
| entities | 12 | 12 (all named; 119/119 field names backticked) |
| state machines | 10 | 10 (53 transitions; every from/to/initial/terminal state token present, incl. both dimensions of ConsigneeNotification) |
| calculations | 8 | 8 (hazard score, sample scope, dual-basis effectiveness, cost accumulation, insurance waterfall, cadence schedule, compliance posture, aging + cooling-off — every constant embedded in business prose) |
| validations | 33 | 33 (§2.6 ladder, ascending priority, each with error id, HTTP status and applies_to scope) |
| endpoints | 53 | 53 rows in §4 |
| errors | 33 | 33 in §5; all 33 also referenced in §2/§3 prose |
| roles | 5 | 5 (identity binding translated: FirmRecallOfficer entity-backed on Firm, other four opaque with the field each is recorded as) |
| concurrency rules | 2 | 2 (write endpoint + expected_recall_version / expected_consignee_version + ERR_STALE_RECALL_VERSION / ERR_STALE_CONSIGNEE_VERSION + 412) |

**Hard contract reports**

```
Field coverage check:
- entities[].fields: 119 required, 119 present, 0 missing
- endpoints[].request_body: 55 required, 55 present, 0 missing
- endpoints[].query_params: 10 required, 10 present, 0 missing
- computed-read output fields (shipped_units, official_basis): 2 required, 2 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 33 checked, 33 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed, 0 missing
- state_machines[].transitions: 53 checked, 53 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed, 0 missing
- validations[] conditions: 33 checked, 33 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 53 checked, 53 expressed, 0 missing
- entities[].fields[] structured content: 119 checked, 119 reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked, 8 with equal prose density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 315
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was opened, grepped, or referenced, and no sibling task directory was read. Notable rules deliberately spelled out for the implementer: the pinned per-line rounding order in cost loading (with the 3x3333 -> 11,148 vs 11,149 worked contrast), the insurance waterfall's tier pinned to capped_total_cents, the deliberately disagreeing empty-set boundaries (100.00 vs 0.00), the non-iterating Cascade A hop-2 cadence pin, and the three compensating round trips.

## Step 6: Generate implementation — 2026-08-24T16:12:00.000Z

(Note: this subagent was interrupted once by a transport error mid-run after writing core.py/domain.py/resolve.py/routes_recall.py/routes_hazard.py; it was resumed with context intact and completed.)

Implementation complete.

## Modules written

All under `workspace/implementation/` (2,308 lines of Python across 9 modules, split to stay well under the output cap):

| File | Purpose |
|---|---|
| `start.sh` | Guarded-install launcher, `exec python3 app.py`, `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | `flask>=2.0` |
| `app.py` | Flask entrypoint, blueprint registration, global request lock, error-envelope handlers |
| `core.py` | Logical clock, in-memory `Store`, UUID/`_seq` row minting, dirty-row version/`updated_at` flush, `meta`/`response_type`/`data` envelope, auth rungs 1-2, body/enum/int/datetime validators, pagination, `ROUND_HALF_UP` helpers |
| `domain.py` | All scaffold constants + the 8 calculations (hazard scoring w/ PRELIMINARY vs RATIFIED variants, sampling scope, dual-basis effectiveness, per-line cost loading, insurance waterfall, cadence, compliance posture, notification aging/cooling-off), Cascade B, checkpoint |
| `resolve.py` | Ladder rungs 3-7 and 11 (firm/recall/consignee/sub-resource existence, tenant scoping, recall-state gates) |
| `routes_recall.py` | Firms, recalls, classify (+Cascade A), checkpoint, effectiveness read, request/decide termination, `/_clock/set_current_utc` |
| `routes_hazard.py` | Hazard evaluations, consignee tree + 4 reverse-reachability listings, distribution records + reconcile |
| `routes_notify.py` | Notifications (independent delivery x response dimensions), retrieval receipts, disposition orders |
| `routes_report.py` | Public warnings, status reports |
| `routes_cost.py` | Cost entries, insurance claims |

## Endpoint count

**53 routes registered** — exactly matching the 53 rows of PRD §4.

## Verification

`bash start.sh` boots and serves (tested on a free port, then killed; no leftover processes). Verified live over HTTP: empty store on boot, `POST /firms` -> 201, unauthenticated request -> 401.

Behavioural checks passed in-process: PRELIMINARY 88.40 -> RATIFIED 70.72 evidence scaling; Cascade A (cadence pinned at hop 1, re-dated report flips OVERDUE -> `ESCALATED`); Cascade B (verify -> 100.00 quantity basis -> `EFFECTIVENESS_REVIEW` + minted `FINAL_EFFECTIVENESS` report); confirm->dispute->confirm and execute->reject compensations exact; per-line cost rounding 3x3716=11148 (not 11149); insurance waterfall with sublimit cap 4,170,000 -> 0.80 tier -> 2,536,000 payable -> 76,080 fee; notification aging at the CLASS_I 24 h edge; cooling-off, tier cap, SoD, OCC 412s, and the full 401/403/404/409/412/422 ladder.

Two PRD/scaffold tensions resolved in favour of the more specific rule, worth flagging: insurance-claim **submit/adjudicate are allowed on a `TERMINATED` recall** (§3.9's explicit state list beats the generic terminal-lockdown sentence), and `VOID` on a distribution line is rejected with `ERR_ROLE_NOT_PERMITTED` for a `FirmRecallOfficer` (§3.4 reserves it to the coordinator even though the endpoint lists both roles).

## Step 5: Generate unit tests — 2026-08-24T16:20:00.000Z

Test infrastructure and suite generated for `task_2147_food_recall_effectiveness`.

## Files written

**`test_helpers/`** (Stage 1) — 9 files
- `types.py` — 12 entity TypedDicts (all carry `id`/`created_at`/`updated_at`/`version`, per PRD §2.4) + 20 status/enum classes
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (52 methods, incl. `/_clock/set_current_utc`)
- `api_errors.py` — all 33 `ApiErrorId`s + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + `assert_recall_invariants`, `assert_effectiveness_payload`
- `factories.py`, `constants.py`, `test_users.py` (incl. mandatory `make_firm_officer_headers(firm_id)` for the `entity_backed:Firm` role, plus `MISSING_ROLE_HEADERS`)
- `fixtures.py` (22 KB) — `RecallCase` builder (~45 workflow methods, identity-threaded) + 5 tiers of composite scenarios: `draft_case`, `classified_case`, `case_with_confirmed_shipment`, `case_in_retrieval_accounting`, `case_with_verified_receipt`, `case_in_termination_requested`, `terminated_case`

**`test_suite/`** (Stage 2) — `conftest.py` + 8 test files, **87 tests**:

| File | Tests |
|---|---|
| `test_01_case_intake_and_distribution_tree.py` | 14 |
| `test_02_hazard_evaluation_and_classification.py` | 16 |
| `test_03_notification_and_contact_effectiveness.py` | 11 |
| `test_04_retrieval_accounting_and_effectiveness.py` | 15 |
| `test_05_public_warning_workflow.py` | 5 |
| `test_06_status_reporting_and_compliance.py` | 7 |
| `test_07_cost_ledger_and_insurance.py` | 12 |
| `test_08_termination_and_access_control.py` | 7 |

## Coverage vs. the design indices

- **Queue A (§1.8 Difficulty): 18/18 instances translated, 2 tests each = 36 tests.** No shortfalls.
- **Queue B (§1.9 Corner): 51/51 non-stub instances translated, 1 test each = 51 tests.** No shortfalls.
- **9 `excluded_because:` stubs not translated** (correct per spec). All 9 `difficulty_instance` cross-references were checked and resolve to real §1.8 instances.
- **0 instances skipped.** Every instance passed the PRD-first two-condition filter — the PRD covers all 33 error IDs' trigger conditions, both OCC rules, the explicit rejection-ladder ordering (which grounds all four priority-conflict tests), all pinned constants (severity/probability/evidence scales, sublimits, coinsurance tiers, cadences, buffers), and both compensating round trips.

## Verification performed

- **Verbatim PRD citation sweep (C1)**: all 189 quoted citations across the 8 files were programmatically matched against `workspace/PRD.md` (whitespace-normalized) — **0 misses**.
- **C4 scaffold-tag sweep**: every test docstring ends with exactly one `Design:` line; 0 untagged, 0 dual-tagged, 0 tags pointing at non-existent instances.
- **No `skip`/`skipif`/`xfail`** anywhere.
- **No "scaffold"/"§1.x"/"Table N" references** leak into generated code (PRD-only prose).
- `pytest --collect-only` -> **87 tests collected**, clean; `pyflakes` clean on `test_suite/`.

## Notable judgement calls

- On `Corner/entities/hazard_evaluation_system_fields_are_server_minted_input_ignored` the sub-assertions `return_count == 0` and `ratified_by_user_id == null` were dropped: unlike `PublicWarning` (§3.6) and `InsuranceClaim` (§3.9), the PRD never enumerates `HazardEvaluation`'s creation-time null/zero defaults, so those fall under the `default-value` silence pattern. The instance's core claim (`status` DRAFT, `variant` PRELIMINARY, `hazard_score` 87.40, `recall_id` from path, recall `version` -> 2) is fully PRD-grounded and asserted.
- Float comparisons on `overhead_rate` / `coinsurance_rate` use `pytest.approx`; all money is asserted as exact integer cents.

## Step 7: Run tests and iterate — 2026-08-24T16:32:00.000Z

All 8 parallel rounds pass 87/87.

## Summary

**Iterations run:** 2 (each an 8-round concurrent sweep, 87 tests x 8 = 696 test executions per iteration).

Iteration 1 result: 85/87 in all 8 rounds, with the *same two* tests failing in every round — zero flakiness, both deterministic.

**Tests deleted:** none. Both failures survived STEP 1a/1b; one required a STEP 1c split.

**Fixes applied to `test_suite/`:**
- `test_suite/test_06_status_reporting_and_compliance.py` -> `TestReportingWindowOverlap::test_a_window_starting_exactly_at_the_existing_end_is_accepted` — STEP 1c partial-coverage split. The test asserted `adjacent["due_at"] == "2026-09-12T00:00:00.000Z"` on a report whose `period_end` was **client-supplied** as `"2026-09-12T00:00:00Z"`. PRD §2.4 pins three-fractional-digit rendering only for `created_at`/`updated_at`, and for the instants "the server itself stamps ... the `period_start`, `period_end` and `due_at` of any report **the server mints on its own**"; it separately says "Client-supplied instants — a shipment's `ship_date`, an explicitly filed report's `period_start` and `period_end` — are **taken as given**". Rendering-format silence for a client-supplied instant on an explicitly *filed* report: echo-as-given and normalize-to-millis are both PRD-faithful. The uncovered format literal was removed; the PRD-verbatim half of the rule ("`due_at` is always equal to `period_end` for every report kind") is retained as `assert adjacent["period_end"] == adjacent["due_at"]` (and is also enforced by `assert_status_report`). All other `.000Z` literals in the suite sit on server-stamped instants and were left untouched.

**Fixes applied to `test_helpers/`:** none needed — no fixture/factory/header inconsistency surfaced.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes_recall.py`, `classify()` (Cascade A hop 4) — after `apply_compliance_posture(recall)` raised the posture to `ESCALATED`, the recall was left with `report_cadence_days == 7` (the hop-1 value), violating PRD §3.3 "The `report_cadence_days` is the escalated cadence of 3 days whenever the recall's `compliance_flag` is `ESCALATED` or `DELINQUENT`" and §3.8 "once the recall is `ESCALATED` or `DELINQUENT`, `report_cadence_days` becomes 3 regardless of hazard class, and the cadence is recomputed **at classification**". Added `apply_cadence(recall)` after the posture recompute. This does **not** violate §3.3's "hop two uses the cadence pinned at hop one / no fixed-point iteration" caveat — `pinned_cadence` is captured before hop 2 and the re-dating is not re-run; only the stored derived field follows the new posture, exactly as §2.8 requires of derived fields.

Both changes are confined to the reclassification branch and the single adjacency test; `run.*.log` scratch files were removed, leaving `results.1..8.json` in `workspace/implementation/`.

(Orchestrator verification: all 8 results files re-read, each 87/87.)

## Step 8: Finalize PRD — 2026-08-24T16:40:00.000Z

`PRD_FINALIZED.md` written at `workspace/PRD_FINALIZED.md`.

## Size

- PRD.md: 355 lines / 11,196 words / 84,093 bytes
- PRD_FINALIZED.md: 355 lines / 11,332 words / 84,961 bytes
- Delta: +0 lines (0.00%), +136 words (+1.21%), +868 bytes (+1.03%) — both edits are inline extensions of existing sentences inside existing paragraphs.

## Changes

- **§2.4 (Case Record Identity, Versioning and the Logical Clock)** — revise — the "Client-supplied instants ... are taken as given" sentence now pins that each such string is persisted and echoed back byte-for-byte and is *not* re-rendered into the three-fractional-digit form, that an explicitly filed report's `due_at` therefore carries the client's `period_end` string verbatim, and that only a later server re-dating (Cascade A's re-dating hop, or the two-day rejection extension) produces a three-digit-rendered instant — `routes_report.py:124-144` (raw echo), `routes_hazard.py:217,225` (raw `ship_date`), `routes_report.py:204-209` and `routes_recall.py:178-180` (re-render via `iso()`).
- **§3.3 (Classification, Sampling Scope and the Reporting Cadence)** — revise — Cascade A hop four now also recomputes `report_cadence_days` from the newly raised posture (leaving the escalated 3-day value in the stored field), and hop four is stated to fire only when hop three flipped at least one report — `routes_recall.py:184-191`.

## Per-edit pre-edit search log

**Edit 1 — §2.4**
- (a) Subject: how client-supplied instants (and the report `period_start`/`period_end`/`due_at` triple) are stored and rendered.
- (b) Paths enumerated and read: `core.py:342-349` (`req_datetime` returns raw + parsed), `core.py:73-92` (`iso`/`parse_iso`), `routes_report.py:117-151` (`create_report` stores `start_raw`/`end_raw`, `due_at=end_raw`), `routes_report.py:185-210` (adjudicate REJECT — `due_at`/`period_end` recomputed via `iso(add_days(...))`), `routes_recall.py:170-183` (Cascade A hop 2), `routes_hazard.py:217,225` (`ship_date` stored raw), `domain.py:246-262` (`mint_report` — server-stamped via `iso`), all other `mint_report` callsites, `routes_recall.py:287-298` (`set_clock` returns `iso(parsed)`, i.e. *not* a verbatim echo). Grepped `ship_date|req_datetime|_raw` across all impl modules.
- (c) Adjustments: (i) "each such string" rather than a general claim about all client input, so the `to_iso8601` -> `current_utc` path (which *is* re-rendered) is not swept in; (ii) added a second sentence explicitly carving out the two server re-dating paths, so the verbatim claim is not a false universal; (iii) dropped an earlier draft phrase "computed from the logical clock" — both replacements are computed from a stored instant, not the clock.

**Edit 2 — §3.3**
- (a) Subject: when `report_cadence_days` and `compliance_flag` are recomputed inside the re-classification cascade.
- (b) Paths enumerated and read: `routes_recall.py:157-193` (hop 1 `apply_cadence`, `pinned_cadence` captured, hop 4 guarded by `if flipped:`), `routes_recall.py:276-282` (DENY branch), `domain.py:395-398` (checkpoint step 3), `domain.py:265-278` (`flip_overdue_reports`), `domain.py:225-235` (`cadence_days` ordering), `domain.py:209-222` (`compliance_posture`), plus a repo-wide grep of `apply_cadence|apply_compliance_posture|report_cadence_days|mint_report`.
- (c) Adjustments: (i) scoped the no-flip clause with "in this cascade" so it does not contradict the checkpoint path, which recomputes unconditionally; (ii) said "in its stored field" so the sentence cannot be read as re-dating already-minted reports — the "One subtlety in Cascade A" paragraph stays verbatim and true; (iii) did not touch hop one's cadence sentence, which remains governed by the paragraph's umbrella rule matching `cadence_days()`'s ordering.

## Step 9: Complete PRD — 2026-08-24T16:52:00.000Z

All 20 edits landed cleanly. `PRD_COMPLETED.md` written at `workspace/PRD_COMPLETED.md`.

- **Line counts:** PRD_FINALIZED.md 355 -> PRD_COMPLETED.md 355 (no new lines/sections; all edits are in-paragraph)
- **Char delta:** +4,825 (84,961 -> 89,836); 18 distinct lines touched
- **Counts:** 20 changes — **15 ambiguity-pins**, **5 mismatch-revisions**

### Changes

- §2.1 (auth headers) — insert — ambiguity — blank/whitespace-only `X-User-ID` counts as absent (401) — `core.py:241`
- §2.1 (identity binding) — insert — ambiguity — firm scoping on lists is a silent filter, not an error; `GET /firms/{id}` is not firm-scoped — `routes_recall.py:117-118`, `routes_recall.py:66-69`
- §2.2 (success envelope) — insert — ambiguity — `api_request_timestamp` comes from real wall-clock, not the logical clock — `core.py:193`
- §2.3 (ordering) — insert — ambiguity — `created_at` ties broken by ascending creation sequence — `core.py:376-377`
- §2.4 (versioning) — insert — ambiguity — at most one bump per row per request; no-op writes bump nothing; rows created by a request stay at `version` 1 — `core.py:161-184`
- §2.6 rung 3 — insert — ambiguity — omitted/null `firm_id` falls to rung 8 (400); wrong-typed value is the 404 — `routes_recall.py:77-84`, `resolve.py:415`
- §2.6 rung 7 — insert — ambiguity — on `POST /recalls` the scope comparison targets the body's `firm_id` — `routes_recall.py:80-81`
- §2.6 rung 8 — revise — ambiguity — required strings must be non-blank; each `lot_codes` element non-blank — `core.py:265-272`, `routes_recall.py:91-93`
- §2.6 rung 11 — revise — mismatch — `TERMINATED` lockdown is total *except* the two insurance-claim actions — `routes_cost.py:331`, `routes_cost.py:353-368`
- §2.6 rung 11 — insert — ambiguity — classify admitted only from DRAFT/CLASSIFIED/NOTIFICATION_IN_PROGRESS; the three flat actions with narrower gates named, all others "not TERMINATED" — `routes_recall.py:141`, `routes_report.py:59`, `routes_notify.py:238`, `routes_notify.py:311`
- §2.8 (cascade discipline) — revise — mismatch — the three custody counters are incrementally moved, not recomputed — `domain.py:137-179` vs `routes_notify.py:252,339,363`
- §3.1 (firms) — insert — ambiguity — duplicate `registration_number` -> `ERR_INVALID_REQUEST` 400 — `routes_recall.py:52-54`
- §3.1 (recall creation) — revise — mismatch — `effectiveness_check_level` starts **null**, not zero, and stays null without a hazard class — `routes_recall.py:17`, `domain.py:114-116`
- §3.3 (re-classification) — insert — ambiguity — backing-evaluation "strictly later" ties broken by creation sequence; latest qualifying candidate wins — `routes_recall.py:39-40,151,155`
- §3.4 (reconcile) — insert — ambiguity — `VOID` by a non-coordinator -> `ERR_ROLE_NOT_PERMITTED` 403, after body validation and before state checks — `routes_hazard.py:265-266`
- §3.7 (disposition verify) — insert — ambiguity — verify accepts an optional `verification_note`, recorded in either branch — `routes_notify.py:352,358-359`
- §3.9 (cost lines) — insert — ambiguity — `overhead_rate` persisted as a decimal fraction (0.115 ...), not a percentage — `domain.py:308-313`
- §3.9 (claim adjudication) — insert — ambiguity — the `paid_cents < settlement_payable_cents` test runs *after* rung 18, so an overshoot on a non-SUBMITTED claim reports `ERR_INVALID_CLAIM_STATE` — `routes_cost.py:366-372`
- §3.9 (termination decision) — insert — mismatch — the `DELINQUENT` block (rung 11) is reported ahead of segregation of duties, reversing the prose's implied order — `routes_recall.py:261-265`
- §3.9 (closing the case) — revise — mismatch — `TERMINATED` lockdown carve-out: claims may still be submitted and adjudicated after closure — `routes_cost.py:331`, `routes_cost.py:353-368`

### Notes
- The scan was run with `workspace/` as its working directory, so `test_helpers/`/`test_suite/` (which live at task root) were not cross-referenced; alignment is purely against `implementation/`, which is the mandated authority anyway.
- All 53 endpoints were walked; no impl-exposed response field lacks a PRD name after these edits.
- Dead code noted but not pinned (never invoked, so not observable): `domain.refresh_firm_paid_to_date` and `domain.refresh_firm_open_recalls`.

---

# Pipeline complete — task_2147_food_recall_effectiveness

Final state: 87/87 tests passing in all 8 concurrent stability rounds under `--isolation per-test-server`.
