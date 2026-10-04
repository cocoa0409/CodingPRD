# Worklog — task_3376_analyst_inquiry_entitlements_research_process_vendor_briefings

## Step 1: Create Task Directory — 2026-10-01T10:45:00.000Z

Task directory was pre-allocated by the caller at `./tasks/task_3376_analyst_inquiry_entitlements_research_process_vendor_briefings/` with an empty `workspace/` subdirectory. Per the caller's explicit instruction, no new index was computed and no other `task_*` directory was created. Verified: task dir exists, `workspace/` exists and is empty, and `./INSTRUCTION.md` exists at the project root (1424 bytes).

## Step 2: Generate Scaffold — 2026-10-01T11:42:00.000Z

Subagent returned (verbatim):

Done. Scaffold generated from the scenario plus the skill spec only — no sibling task under `tasks/` was read.

### Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_3376_analyst_inquiry_entitlements_research_process_vendor_briefings/SCAFFOLD.yaml` (§1.0–§1.7; no `scaffold_difficulty_design` / `scaffold_corner_design` key)
- `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level `scaffold_difficulty_design`)
- `.../SCAFFOLD_CORNER_DESIGN.yaml` (single top-level `scaffold_corner_design`)

### Counts

| Dimension | Value |
|---|---|
| Entities | 11 (ClientAccount, Seat, Analyst, InquiryRequest, ResearchDocument, Vendor, VendorInclusion, VendorBriefing, SalesRelationship, ConferenceEvent, Sponsorship) |
| State machines | 11 (incl. 3 cyclic/parallel: InquiryRequest re-route loop, ResearchDocument `editorial_status × embargo_status`, VendorInclusion `inclusion_status × fact_check_status` + appeal loop) |
| Endpoints | 54 |
| Error codes | 37 |
| Calculations | 6 |
| Validations | 11 priority levels |
| Roles | 9 |
| §1.8 instances | 24 (2–3 per Difficulty Rule; 9 rules) |
| §1.9 instances | 39 (33 with recipes + 6 `excluded_because` stubs) |

Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

### Key design decisions

- **Archetype**: compliance/audit + multi-party negotiation; graph topology; cyclic state shape; `segregation_of_duties` role model; OCC + cascades + version-pinning + rate thresholds.
- **Difficulty density over volume**: 11 entities carry 54 endpoints and 24 difficulty instances. Rules are satisfied with margin — Rule 2 in all three modes (nested-min / nested-rounding order / pinned evaluation order), Rule 3 on three different entities, Rule 8 with three different interval semantics (raw half-open, 15-min buffer-expanded, tier-scoped exclusivity), Rule 9 with three different conserved quantities (inquiry units, cents, licensed copies).
- **All formula-derived asserts were computed in Python**, not estimated: utilization 91.05/82.24/90.88/65.00/55.00/35.00/32.24, evaluation 3.86 vs 3.85 and 4.06 vs 4.04, reprint fees 468000/855000/250000, sponsor share 0.4 vs 0.4286, weekend-rolled deadline 2026-09-21T23:59:59Z.

### Adjudications worth flagging

1. **OCC kept to true races only.** Three concurrency rules (inclusion create → stale `ResearchDocument.version`; sales relationship → stale `Analyst.version`; sponsorship → stale `ConferenceEvent.version`). I explicitly rejected two candidates that fail §1.2.1's serial-observability filter (document publish, appeal re-file) and removed the stray `expected_inclusion_version` field that had no rule behind it.
2. **Three errors deleted as unreachable** (`ERR_VENDOR_NOT_ACTIVE`, `ERR_VENDOR_NOT_INCLUDED`, plus a redundant vendor-status enum) — no endpoint could produce them, and the §1.4 priority-9 row was rewritten around the reachable referential errors (`ERR_SEAT_NOT_ACTIVE`, `ERR_EVENT_AGENDA_LOCKED`). Enum closure now holds for every system/computed enum (`CONFLICT_BLOCKED` gained a producing threshold at 3 ties; `Vendor.status` reduced to the single system-initialized value).
3. **§1.4 priority ladder reordered to 11 levels** so the three priority-pair conflicts use genuinely different category pairs: state/referential, temporal/fiscal, state/safety. Every dual-failure recipe asserts the winner *and* isolates the loser in a second call.
4. **Selector determinism pinned** for both routing selectors (eligibility, ranking, `created_at` tie-break — never `id`, empty-pool fallback error).
5. **Endpoint count is 54**, above the ≤40 heuristic I've seen break impl-gen. The scenario names 10+ distinct workflows, and I chose the explicit "much harder than expert" directive over the heuristic — flagging it so Step 6 can be verified on disk rather than trusted from its report.

### Orchestrator verification note

All three files confirmed present on disk with correct top-level structure: `SCAFFOLD.yaml` 2352 lines (top-level keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles — and neither `scaffold_difficulty_design` nor `scaffold_corner_design`); `SCAFFOLD_DIFFICULTY_DESIGN.yaml` 1314 lines (single key `scaffold_difficulty_design`); `SCAFFOLD_CORNER_DESIGN.yaml` 1545 lines (single key `scaffold_corner_design`).

**Risk flag carried forward:** 54 endpoints exceeds the ≤40 heuristic known to destabilize the implementation generator. Step 6's output must be verified on disk (files present, package graph importable via `pytest --collect-only`), not trusted from its report.

**Clock check (orchestrator):** scaffold declares a controllable logical clock — `POST /_clock/set_current_utc` (role PlatformAdmin), server startup default exactly `2026-09-01T00:00:00Z`, never falling back to wall-clock. All deadlines, embargoes, renewal windows and capacity days evaluate against it. No undefined `CONST.*` symbols exist in the scaffold (0 references), so the undefined-constant bootstrap deadlock mode does not apply here. The clock being API-settable removes the clock-unreachability risk for Step 5 fixtures.

## Step 3: Copy Shared Files — 2026-10-01T11:44:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` (1424 bytes) to `{task_dir}/workspace/INSTRUCTION.md`. Verified present. Contents confirm the build contract: produce `./implementation/start.sh` which installs deps and starts the HTTP server in the foreground, listening on `$PORT` (default 10000), bound to `0.0.0.0`, responding within 60s; evaluator runs `bash start.sh` from `./implementation/`. No language restriction stated, but the pipeline mandates Python + Flask.

## Step 4: Generate PRD — 2026-10-01T12:04:00.000Z

Subagent returned (verbatim):

PRD generated and verified.

### Output

`/home/ubuntu/github/CodingPRD/tasks/task_3376_analyst_inquiry_entitlements_research_process_vendor_briefings/workspace/PRD.md` — 419 lines, ~77 KB.

**Structure:** §1 Introduction (2 paragraphs); §2 Global Specifications — 2.1 RBAC, 2.2 API Response Structure (verbatim), 2.3 Pagination, 2.4 Logical Clock, 2.5 Research Independence & Separation Register, 2.6 Inquiry Allowance Ledger, 2.7 Utilization Scoring, 2.8 Evaluation/Deadline/Share Arithmetic, 2.9 Reprint Licence Arithmetic, 2.10 Common Resource Properties, 2.11 Nested Retrieval & Validation Precedence (ordered checks 1–11), 2.12 OCC & Cascading Side Effects; §3 Business Logic — 9 subsections (client/seat onboarding; inquiry routing–scheduling–prep; settlement/cancellation/ledger; renewal; authoring/peer review/fact check; publication/embargo/placement freeze; vendor placement/appeals/reprints; briefings/separation register; conference programming/sponsorship); §4 endpoint table (54 rows, 4 columns); §5 error catalogue (38 rows, 2 columns).

### Hard Contract Reports

```
Field coverage check:
- entities[].fields: 137 required, 137 present, 0 missing
- endpoints[].request_body/input: 77 required, 77 present, 0 missing
- endpoints[].query_params: 0 required (all query-style inputs declared in `input`), 0 missing
- path_params: none declared by the scaffold
- deduplicated total: 138 required, 138 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 11 checked, 11 expressed in prose (fixed precedence order, scopes enumerated), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write operation + expected_*_version + parent `version` + ERR_STALE_VERSION 412), 0 missing
- state_machines[].transitions: 54 checked, 54 fully expressed, 0 missing
- calculations[]: 6 checked, 6 fully expressed (formulas, constants, pinned rounding/evaluation orders, rejected variants, guards), 0 missing
- validations[] conditions: 11 checked, 11 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 54 endpoints checked, 54 expressed, 0 missing
- entities[].fields[] structured content: 137 checked, reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 sibling groups checked, 9 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 787
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: §2.2 is byte-identical to `section-2.2-response-structure.md` (0-line diff); §4 table matches all 54 scaffold endpoints with exact role lists; all 37 catalogue error IDs appear in §2/§3 prose; all 43 state values and 93 enum values appear verbatim; no fuzzy/approximating words anywhere.

### Rules that were hard to state unambiguously (scaffold-internal conflicts; resolution chosen)

1. **`ERR_PREPARATION_NOTES_REQUIRED` is not in `errors[]`.** It appears only in an `InquiryRequest` state-machine side effect, with no HTTP status pinned anywhere. I stated it as HTTP 409 in §3.2/§3.3 and added it as a §5 row, so §5 is 37 catalogue errors + this one.
2. **"utilization_score computed (0.00 with no seats)" contradicts the §1.3 formula.** A fresh account with contracted seats evaluates the retention term to 25 (no revocations, `(1-0)/0.95` capped at 1), not 0. I stated the formula and its three explicit guards and did not repeat the "0.00 with no seats" claim.
3. **`Seat entitlement expiry`** is listed among the clock endpoint's time-derived fields, but no Seat field or transition implements an expiry. I listed only the concrete clock-driven evaluations (embargo release, `IN_PREP` entry, `RENEWAL_REVIEW` entry, fact-check lapse).
4. **Briefing creation side effect vs. state machine.** The create endpoint claims a briefing can be created `DECLINED` with `FAIL_SALES_RELATIONSHIP`, but there is no `REQUESTED → DECLINED` transition and the routing note says an empty pool is a 403 with no row created. I followed the state machine + note (403 `ERR_BRIEFING_SEPARATION_FAILED`, no row).
5. **`record-briefing` takes an optional `held_at` while the HELD transition stamps `held_at` with the clock.** I stated the recorded instant is the clock reading and that the payload may carry `held_at`.
6. **`SCHEDULED → CANCELLED` lists "status == SCHEDULED or status == IN_PREP"**, overlapping the separate `IN_PREP → CANCELLED` transition; I expressed cancellation as available from `ROUTED`/`SCHEDULED`/`IN_PREP`, with the charge determined solely by the 24-hour boundary.

Clock semantics are stated explicitly in §2.4 and reinforced where each boundary applies: `/_clock/set_current_utc` with input `current_utc`, PlatformAdmin-only and exempt from the auth headers, startup default exactly `2026-09-01T00:00:00Z`, never falls back to wall-clock, and the inclusive/strict boundary list (90-day renewal entry, 24-hour prep and cancellation boundary, embargo release, strict fact-check lapse, strict event completion, appeal window, no past inquiry start).

### Orchestrator verification note

`workspace/PRD.md` confirmed on disk: 419 lines, 77037 bytes. Section structure matches the report exactly (§1–§5, §2.1–§2.12, §3.1–§3.9, §4 Endpoint Definitions, §5 Error Code Catalogue). The six adjudications above are carried forward as watch-items for Steps 5/6/7 — in particular item 1 (`ERR_PREPARATION_NOTES_REQUIRED` synthesized into §5 with HTTP 409) and item 4 (briefing separation failure = 403 with no row created), since tests generated from the design indices may assume the scaffold's original, contradictory phrasing.

## Step 5: Generate Unit Tests — 2026-10-01T12:30:00.000Z

Subagent returned (verbatim):

Test infrastructure is complete and verified.

### Files written

**`test_helpers/` (10 files, 1,838 lines)**
| File | Lines |
|---|---|
| `__init__.py` | 30 |
| `types.py` | 447 |
| `api_client.py` | 262 |
| `api_errors.py` | 91 |
| `assertions.py` | 207 |
| `constants.py` | 103 |
| `factories.py` | 200 |
| `fixtures.py` | 451 |
| `test_users.py` | 47 |

**`test_suite/` (12 files, 3,370 lines)** — `conftest.py` + 10 test modules: `test_01_allowance_ledger.py` (8), `test_02_accounts_and_seats.py` (7), `test_03_inquiry_routing_and_scheduling.py` (15), `test_04_utilization_and_renewal.py` (5), `test_05_documents_peer_review_and_embargo.py` (10), `test_06_vendor_evaluation_scoring.py` (6), `test_07_publication_cascade_appeals_and_reprints.py` (10), `test_08_briefings_and_separation.py` (7), `test_09_conference_and_sponsorship.py` (12), `test_10_validation_precedence_and_rbac.py` (7).

### Coverage

- **87 tests.** 24/24 difficulty instances translated (exactly 2 each, 48 tests); 39/39 non-stub corner instances translated (1 each, 39 tests); the 6 `excluded_because:` stubs were not translated.
- **No instance was skipped** — every one passed the two-condition filter. Zero untagged/dual-tagged/broken tags; every docstring ends with exactly one `Design:` line resolving to a real `name:`.
- **Citation audit:** 149 quoted spans, all surviving a whitespace-normalized literal grep of `PRD.md`. No `skip`/`skipif`/`xfail`, no scaffold/section-table leakage in generated code.
- **Structural validation:** ran the whole suite against a stub client that returns well-shaped envelopes — 0 structural errors (no TypeError/KeyError/AttributeError), so every fixture path executes end-to-end. 84 tests fail only on value assertions (expected against a placeholder stub), 3 pass coincidentally.

### Literals re-derived from PRD (design index contradicted the formula)

1. `Difficulty/combinatorial_formula/utilization_score_nested_min_across_five_inputs` — index asserts `utilization_score_active_weighted == 90.88`; PRD §2.7 yields **90.57** (37.5 + 35×2/2.10 + 19.74). Used 90.57.
2. `Corner/calculations/utilization_activation_target_boundary_at_eighty_percent` — index asserts 55.00 after a revoke; PRD §2.7 yields **51.05** (activation 30 + retention 21.05). Used 51.05.
3. `Difficulty/cross_entity_state_dependency/renewal_decision_requires_seat_derived_utilization` — the index's pair (35.00 dashboard / 65.00 active-weighted) is **arithmetically unreachable**: with zero settled inquiries both variants are identical, so no PRD-consistent triple produces 65.00. Re-derived with one completed inquiry: dashboard **37.50**, active-weighted **47.50** — preserving the instance's distinguishing aspect (gate passes at ≥40 while the dashboard reads below 40). Account B's 0.00 guard kept.
4. `Corner/calculations/fact_check_deadline_rolls_a_weekend_landing_to_monday` — the recipe's `*c_clock` anchor (2026-09-01) contradicts its own prose and its asserted `fact_check_requested_at`; used **2026-09-05** so the asserted due date 2026-09-21T23:59:59Z is reachable.
5. Unpinned initial `version` (PRD §2.10 says only "starts at its initial value"): the index's `version == 1` / `version == 2` assertions became `isinstance(int)` plus a `version_before + 1` increment check (the increment *is* pinned).
6. `Corner/entities/client_create_with_unknown_region…` and `Corner/validations/seat_holder_calling_client_create…` — the index asserts against `GET /research/clients` (a list endpoint that does not exist in the PRD §4 table); those two assertions were dropped.

### Rules the PRD does not uniquely determine (assertions kept, but flagged)

- **Briefing buffer interval semantics.** §3.8 pins a 15-minute buffer but not open/closed overlap for briefings, so "a briefing starting exactly 15 minutes after the previous ends is accepted" assumes half-open. The 5-minute case is unambiguous and also asserted.
- **Fact-check lapse error precedence.** §2.11's ordered list puts target-state (5) before time-windows (7) — which would give `ERR_INVALID_STATE` for a lapsed round — while §3.5 and §2.11 item 7 both name `ERR_FACT_CHECK_RESPONSE_LATE` for exactly that scenario. Asserted the named error.
- **`renewal_posture` source score.** §2.7 says "derived from a score" without naming the variant; the index's `renewal_posture == AT_RISK` assertion was dropped from the renewal-gate test because my re-derived values straddle the 40 ceiling and the derivation is ambiguous.
- **Seat entitlement-expiry transition** (adjudication 6) — no index instance asserted one, so no impact.

All fixture dates are set explicitly through `POST /_clock/set_current_utc`; every literal was checked for reachability from `2026-09-01T00:00:00Z`, and the weekend rolls were verified (2026-09-19 is a Saturday → 2026-09-21; 2026-09-15 and 2026-10-01 are not weekend landings). Create paths pass `expected_status=201` explicitly.

### Orchestrator verification note

On-disk check: `test_helpers/` has 10 files (incl. `__init__.py`), `test_suite/` has `conftest.py` + 10 test modules; combined 5208 lines. Exactly **87 `Design:` tags** across the suite, matching the reported 87 tests; tag prefixes cover all 9 Difficulty rules and all 8 Corner sections. Grep for `pytest.mark.skip` / `pytest.mark.xfail` / `@skip` / `xfail` across both directories returns **nothing** — no test was skipped or marked expected-fail.

**Watch-items carried to Steps 6/7:** (a) the six PRD-derived literal corrections above — the implementation is generated from the PRD only, so it should land on the PRD values, and any residual mismatch here is a genuine signal rather than a test bug; (b) the four flagged non-uniquely-determined rules — if Step 7 finds failures there, they are deletion candidates under STEP 1b, not implementation bugs; (c) `test_helpers/constants.py` was the last file touched (12:28) — its values must be PRD values, not scaffold values, per the known dead-constant trap.

## Step 6: Generate Implementation — 2026-10-01T13:11:00.000Z

Subagent returned (verbatim):

Implementation complete and verified.

### What was built

`workspace/implementation/` — Python + Flask, in-memory only, 26 files, 3,344 lines of Python (+ 10-line `start.sh`, `requirements.txt`):

| File | Lines | Contents |
|---|---|---|
| `app.py` | 78 | Entry point, blueprint registration, error handlers, `0.0.0.0:$PORT` |
| `db.py` | 106 | Empty-on-boot dict store, logical clock (default `2026-09-01T00:00:00Z`), entity minting, serialization |
| `errors.py` / `response.py` / `middleware.py` / `timeutil.py` | 56 / 52 / 133 / 78 | Error catalog, envelope, auth headers, pagination, ISO-8601 + weekend-roll helpers |
| `services/` (5 files) | 632 | Ledger, utilization scoring, entitlements, routing selectors, clock-driven evaluations, separation cascade, score/deadline/fee arithmetic |
| `routes/` (12 files) | 2,169 | All endpoint groups |

### Endpoint coverage

**54 / 54** endpoints from PRD §4 are implemented — verified programmatically by diffing the PRD table against Flask's `url_map` (parameter names normalized): `MISSING: []`. The only extra route is a deliberate alias `POST /research/_clock/set_current_utc` alongside the PRD/scaffold path `/_clock/set_current_utc` (the task prompt named the prefixed path, the PRD names the root path — both now work).

### How it was verified

Started the server myself on scratch ports (18957/18733/18963 — never 10000) via `bash start.sh` and ran three curl-driven suites (all passing), then killed only the PIDs I started:

- **Envelope/auth**: `meta` with `api_request_id`+`api_request_timestamp` (3 fractional digits), `response_type` object/array/error, pagination fields in `meta`, 401/403, creates 201, clock 200 with `data {}`, fresh boot shows empty store and clock `2026-09-01T00:00:00.000Z`.
- **State machines/calcs**: inquiry submit→route→schedule→IN_PREP→complete/cancel (free vs late units), decline re-route, peer review APPROVE/REVISE, publish freeze cascade, revise round-trip, appeal loop + cap + window, UPHOLD reopen, fact-check dispute loop to round 3, lapse, supersede, seat revoke → `RENEWAL_REVIEW` at the `ceil(contracted/2)` threshold (inclusive), CHURN seat cascade, RENEW gate on `utilization_score_active_weighted` (57.5 passes, 0.00 → `ERR_RENEWAL_UTILIZATION_TOO_LOW`), reprint brackets (540000 / 867000 / 0), sponsor share boundary 0.4000 accepted, PLATINUM overlap, agenda lock/reopen.
- **Error paths**: all 404 family, `ERR_STALE_VERSION` (all three OCC sites), `ERR_INQUIRY_START_IN_PAST`, `ERR_SEAT_NOT_ACTIVE`, `ERR_INQUIRY_SLOT_OVERLAP`, `ERR_ANALYST_DAILY_INQUIRY_CAP`, `ERR_INQUIRY_ALLOWANCE_EXHAUSTED`, `ERR_BRIEFING_SLOT_CONFLICT`, `ERR_BRIEFING_SEPARATION_FAILED`, `ERR_APPEAL_WINDOW_CLOSED`/`LIMIT_REACHED`, `ERR_EMBARGO_ACTIVE`, `ERR_AGENDA_LOCKED`/`ERR_EVENT_AGENDA_LOCKED`, `ERR_SPONSOR_EXCLUSIVITY_OVERLAP`, `ERR_REPRINT_COPIES_EXCEEDED`, `ERR_INCLUSION_CRITERIA_NOT_MET`, `ERR_PREPARATION_NOTES_REQUIRED`, `ERR_DUPLICATE_SEAT_EMAIL`.

Note: port 18731 is occupied by another pipeline's server on this host — my first smoke run accidentally probed it. I did not touch that process; I hardened the readiness probe and moved to free ports. No processes or ports from my work remain.

### Ambiguities resolved (flagging for Step 7)

1. **Late fact-check responses**: §2.11/§5 say a response landing after `fact_check_due_utc` is refused with `ERR_FACT_CHECK_RESPONSE_LATE`, while §3.5 also describes a *penalty* for a late response — mutually exclusive. I implemented refusal (both when already `LAPSED` and when the clock is past the due date); the 0.25 penalty branch exists but is unreachable by construction.
2. **UPHOLD on a published document** leaves the document at `REVISED` (PRD §3.7 literal), not auto-advanced to `FACT_CHECK` (the scaffold's generic REVISED→FACT_CHECK event is applied only on the `/revise` endpoint, which §3.6 states explicitly).
3. **Sponsor keynote exclusivity** implemented literally per §5's condition: refused when the row's own `sponsor_vendor_id` holds an ACTIVE PLATINUM window overlapping the event window (the "unless it is that vendor's own sponsorship" clause is vacuous under that reading).
4. **`placement_locked` on ResearchDocument** is a live flag (`True` while PUBLISHED), matching the freeze semantics.
5. A fresh account's `utilization_score` is **25.00** (retention term only) per the §2.7 formula; the scaffold's "(0.00 with no seats)" note contradicts the formula, and PRD wins.
6. **Decline with an empty re-route pool** returns 409 `ERR_ANALYST_NOT_ELIGIBLE` with no mutation (the error's catalogued condition explicitly covers "every candidate has already declined").

### Orchestrator verification note

On-disk check performed independently (the 54-endpoint scaffold exceeds the size at which this generator has previously degraded, so the report was not trusted):

- `workspace/implementation/` contains `app.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `timeutil.py`, `start.sh` (executable), `requirements.txt` (`Flask>=3.0`), plus `routes/` (12 modules + `__init__.py` + `_common.py`) and `services/` (4 modules + `__init__.py`). Total 3,344 lines of Python — no stub or placeholder files, no file truncated to zero.
- `python3 -m compileall -q .` exits 0 — every module compiles.
- `import app` succeeds and `app.app.url_map` yields **56 routes** (54 PRD endpoints + the clock alias + Flask's static route), confirming the package graph is intact (no dangling imports).
- Independent boot smoke test: `PORT=18991 bash start.sh` bound `0.0.0.0`, `POST /research/_clock/set_current_utc` returned `{"meta":{"api_request_id":"req_...","api_request_timestamp":"2026-09-01T00:00:00.000Z"},"response_type":"object","data":{}}` — envelope matches PRD §2.2 and the logical-clock default is correct. Process killed by exact PID ($!); no stray processes left.
- **Storage check:** `db.py` is a dict-backed store with no file/disk persistence; no seed data path observed at boot (fresh boot returned an empty store).

**Step 6 ambiguities 1 and 3 are the highest-risk items for Step 7** — both are places where the PRD's own prose is internally inconsistent (fact-check late-response refusal vs. penalty; sponsor exclusivity's vacuous self-sponsorship clause), so tests touching them are STEP 1b deletion candidates if they fail.

## Step 7: Run Tests and Iterate — 2026-10-01T13:31:00.000Z

Subagent returned (verbatim):

Done. Final sweep is clean across all 8 parallel rounds.

### Summary

**Iterations run:** 2 sweeps. Sweep 1: 67/87 passing, 20 failures — identical in all 8 rounds (deterministic, no flakiness). After fixes, sweep 2: **87/87 in all 8 rounds**, `results.1..8.json` left in place.

**Tests deleted: 0.** Every failure traced to a real defect in one of the two layers; no test asserted a scaffold-only rule.

#### Fixes to `implementation/` (3 files, 9 tests)

- **`timeutil.py` + `db.py`** — added `format_dt_seconds` and used it in `db._clean` for lifecycle instants. `format_dt` emitted 3 fractional digits for *every* timestamp, but PRD §2.8 pins "timestamps carry second precision in UTC unless a field states otherwise"; only `created_at`/`updated_at` (§2.10) and `api_request_timestamp` (§2.2) state otherwise. Fixed 8 tests (`embargo_until`, `fact_check_requested_at`, `fact_check_due_utc`, `appeal_window_closes_at`).
- **`routes/inquiries.py` → `cancel_inquiry`** — the charge is now decided by the pinned 24-hour boundary instead of the status the clock evaluation just produced. At exactly `scheduled_start_utc - 24h` the inquiry has *reached* (not crossed) the boundary and has just entered `IN_PREP`; keying off status charged it late. PRD §2.4 pins this boundary inclusive-free ("free while the clock reading is at or before…"), and §3.3 states the same rule for "a scheduled **or in-preparation** inquiry" — that phrase would be dead text under the status-keyed reading. Fixed 1 test.

#### Fixes to `test_suite/` (5 files, 11 tests)

- **`test_03`** — `_two_analyst_roster` added a third DISTINGUISHED analyst on top of the one `setup_account_with_active_seat` already creates; routing's `created_at` tie-break gave the inquiry to the discarded analyst, so the setup's `schedule` call 403'd. Now reuses the setup analyst as `first`. (2 tests)
- **`test_04`** — second completed inquiry requested start `11:00` after the first completion had advanced the clock to `12:00`, correctly refused with `ERR_INQUIRY_START_IN_PAST`. Moved to 13:00/14:00. (1 test)
- **`test_08`** — analysts built with the factory default `topic_routes=["CLOUD_COST"]` while briefings requested `MARKET_OUTLOOK`, so the pool was empty by *topic*, not by conflict. (3 tests)
- **`test_09`** — `activate_sponsorship` called with default PlatformAdmin headers, but PRD §4 authorizes activation to `EventProgrammer, SalesRep` only; the request stopped at authorization (priority 2) and never reached the state checks. Now sends EventProgrammer headers (4 call sites — one was previously unreachable because an earlier line aborted the test). (3 tests)
- **`test_09`** — sponsor-share refusal row used `duration_minutes: 10`, below PRD §3.9's minimum of 15, so the request-shape check (priority 3) fired before the share ceiling (priority 8). Changed to 15 → 95/215 = 0.4419 > 0.4000. (1 test)
- **`test_07`** — third appeal filed straight from `UNDER_APPEAL`, so the target-state check (priority 5) fired before the appeal-count gate. Added the second `DENY` so the inclusion rests in `APPEAL_DENIED` — the other source state PRD §3.7 admits — leaving the count as the only gate. (1 test)

#### Notes

- No `skip`/`xfail` anywhere; no assertion downgraded; no PRD-required implementation check removed; no endpoint, field, or seed data added (route count unchanged at 54 + 1 clock alias; storage still in-memory only).
- One judgement call worth flagging: the cancel-boundary failure was the only case where the PRD's own prose collides (`§2.4`/`§3.3` free-at-boundary vs. §3.3's "already in `IN_PREP` … always late"). I fixed the implementation rather than deleting the test because the rationale sentence's premise is "*crossed* the boundary", which is false at the exact instant, and §2.4 is the section that declares boundaries "must be applied exactly as stated where it is defined".
- All repro servers I started were killed by exact PID; verified no strays remain.

### Orchestrator verification note

Independent on-disk verification of the sweep artifacts (Step 7 has previously "cleaned up" the very files the output contract requires, so the report was not trusted):

- All 8 files `results.{1..8}.json` present in `workspace/implementation/`, all timestamped 13:30, sizes 28379–28388 bytes.
- Parsed each: **round 1..8 all report `passed=87 total=87`** — no round was missing, truncated, or partial.

**Step 8 is NOT skipped** (Step 7 ran 2 sweeps with 3 `implementation/` fixes and 6 `test_suite/` fixes). Step 8's scope is therefore bounded to: (a) the two `implementation/` behaviors Step 7 pinned that the PRD left ambiguous — the timestamp-precision rule (§2.8 "second precision unless a field states otherwise") and the exact-boundary cancel charge; and (b) the six `test_suite/` fixture repairs, which are pure fixture bugs and should NOT generate PRD edits. Step 7's own flag — that §2.4/§3.3 collide on the cancel boundary — is the highest-value Step 8 target.

## Step 8: Finalize PRD — 2026-10-01T13:40:00.000Z

Subagent returned (verbatim):

Done. `PRD_FINALIZED.md` is written and verified.

### Output

`/home/ubuntu/github/CodingPRD/tasks/task_3376_analyst_inquiry_entitlements_research_process_vendor_briefings/workspace/PRD_FINALIZED.md`

- **PRD.md: 419 lines / 76,910 chars → PRD_FINALIZED.md: 419 lines / 78,018 chars (+1.44% chars, +0 lines).** All three source paragraphs are single lines, so edits changed no line count. No new sections; no `implementation/` file touched.

### Changes (4 hunks, 3 subjects)

- **§2.8 — revise — timestamp rendering.** Replaced "timestamps carry second precision in UTC unless a field states otherwise" with the pinned rule: instants are rendered in UTC at second precision **dropping any fractional part**; the only fields that state otherwise are `created_at`/`updated_at` (§2.10) and `api_request_timestamp` (§2.2) at three fractional digits; every other instant — naming `embargo_until`, `fact_check_requested_at`, `fact_check_due_utc`, `appeal_window_closes_at`, plus a client-supplied instant echoed back — is rendered without a fractional part (`2026-09-15T00:00:00Z`). — `implementation/timeutil.py:31-38`, `implementation/db.py:104-107`, `implementation/db.py:41-42,53,65`, `implementation/response.py:20`
- **§3.3 — revise — cancellation charge boundary.** Deleted the false sentence "An inquiry already in `IN_PREP` has by construction crossed the 24-hour boundary, so its cancellation is always late" and replaced it with the boundary-keyed rule the implementation now uses: an inquiry that has just entered `IN_PREP` because the clock *reached* `scheduled_start_utc` minus 24 hours (but not passed it) is still cancelled free; only a clock reading strictly after the boundary is late. — `implementation/routes/inquiries.py:335-341`
- **§3.2 — insert — routing tie-break fallback.** After "The final tie-break is always `created_at`, never the analyst identifier", added that analysts registered at the same clock reading share an identical `created_at`, and that candidates still tied are won by the earliest-registered. — `implementation/services/routing.py:14-37`
- **§3.8 — insert — same fallback for briefing routing** ("…ties broken by `created_at` ascending; when candidates remain tied on `created_at` as well … the one registered earliest is chosen"). — `implementation/services/routing.py:45-60`

### Pre-edit search log

**Edit 1 (timestamp rendering).** (a) Subject: rendering precision of every instant the API emits. (b) Enumerated by grep for `strftime|isoformat|now_str|format_dt|"Z"`: the only string-producing sites are `db.now_str()`→`format_dt` (3 digits) used at `db.py:53` (created_at), `db.py:65` (updated_at), `response.py:20` (api_request_timestamp), and `db._clean`→`format_dt_seconds` for every `datetime`; confirmed by grepping every `return ok(`/`ok_list(`/`ok_empty(` in `routes/` that all payloads pass through `serialize`/`serialize_list` (single chokepoint). (c) Wording adjustment: wrote "dropping any fractional part" (truncation) rather than "rounded to the second", and phrased the exceptions as "only … state otherwise" so the universal claim holds for all serialization paths. Verified live: clock set to `…10:00:00.987Z` → `api_request_timestamp`/`created_at`/`updated_at` = `…10:00:00.987Z`; `contract_start_utc` `…00:00:00.500Z` and `requested_start_utc` `…10:00:00.250Z` echoed as `…00:00:00Z`/`…10:00:00Z`.

**Edit 2 (cancel charge).** (a) Subject: which cancellation branch applies at/after the 24-hour boundary. (b) Enumerated: `routes/inquiries.py:309-353` (the only cancellation path; ROUTED→0, else `now <= start-24h`), `services/state.py:88-99` (`evaluate_inquiry`, inclusive boundary that produces `IN_PREP` before the charge is computed), `services/scoring.py:72-84` (`ledger_units` counts `CANCELLED && units_consumed==1`), and the other PRD statements of the same rule (§2.4 bullet 3, §2.6 settled-unit definition, §3.3's own free/late sentence) — all left verbatim and mutually consistent. (c) Wording adjustment: scoped the sentence to the charge decision and explicitly named the exact-boundary case, so it neither re-states nor narrows the pre-existing free/late sentence. Verified live: cancel at exactly `scheduled_start − 24h` → status `IN_PREP`→`CANCELLED`, `units_consumed` 0; one second later → 1.

**Edit 3 (§3.2 + §3.8 tie-break).** (a) Subject: which analyst wins when candidates tie on `created_at` (the normal case, since the logical clock does not advance on writes). (b) Enumerated: `services/routing.py:14-37` (`topic_route_candidates`, stable sort over `db.analysts.values()`) and `:45-60` (`briefing_candidates`, same shape), their callers `routes/inquiries.py:76,233` and `routes/briefings.py:44`, the only write to `db.analysts` (`routes/analysts.py:41`, insertion only — no deletion, so insertion order = registration order), and the unrelated `page_of` sort (`routes/_common.py:112`). (c) Wording adjustment: scoped the sentence to routing candidate selection (not list ordering) and applied it in **both** routing paragraphs, since §3.8 restates its ranking rather than inheriting §3.2's. Verified live with three same-seniority, same-`created_at` analysts: inquiry routing and briefing routing both picked the earliest-registered (index 0), twice over.

### Diff items that produced no edit

Items 4–8 of `<step_7_diff>` are fixture bugs against rules the PRD already pins verbatim: start-before-clock (§2.4/§3.2), briefing topic eligibility (§3.8), activation roles `EventProgrammer, SalesRep` (§3.8/§4 table), `duration_minutes` ≥ 15 (§3.9), and appeal source states `EXCLUDED`/`APPEAL_DENIED` (§3.7). No PRD text was changed for them.

One caveat worth flagging: the §3.2/§3.8 tie-break edit traces to a **test_suite** fix (item 3), not an `implementation/` fix — Step 7's summary labelled items 3–8 "pure fixture bugs [that] should NOT generate PRD edits". I included it because the fixture failure was caused precisely by the PRD leaving the equal-`created_at` case open while the implementation resolves it deterministically; it is the only edit that a reviewer might consider optional.

### Orchestrator verification note

- `workspace/PRD_FINALIZED.md` confirmed on disk: 419 lines, 78,159 bytes (the subagent reported 78,018 chars — the byte count differs only by multi-byte UTF-8 characters; both agree the file is ~1.4% larger than PRD.md's 77,037 bytes, and line count is unchanged at 419).
- **Sweep-integrity check (mandatory — a post-sweep `implementation/` write would invalidate the clean 8-round result):** newest implementation source file is `routes/inquiries.py` at **13:25:21**; `db.py` 13:25:13; `timeutil.py` 13:25:07. The results files are stamped **13:30:35** — i.e. the final sweep ran ~5 minutes *after* the last code edit, and Step 8 wrote no `implementation/` file at all (its latest write is `PRD_FINALIZED.md`). The clean sweep therefore remains valid.
- **Caveat carried to Step 9:** the §3.2/§3.8 tie-break edit is the one Step 8 hunk that traces to a `test_suite/` fixture fix rather than an `implementation/` fix, making it the weakest-justified edit in the set. Step 9 should re-verify it against the current implementation (and widen or revert it if it over-claims), since the NO-NEW-MISMATCH rule is the binding constraint there.

## Step 9: Complete PRD — 2026-10-01T14:00:00.000Z

Subagent returned (verbatim):

`workspace/PRD_COMPLETED.md` is written. It is a 14-hunk patch over **PRD_FINALIZED.md** (the newer/larger source; PRD.md is 77,037 chars).

**Size:** PRD_FINALIZED.md 419 lines / 78,159 chars → PRD_COMPLETED.md 421 lines / 84,363 chars (**+2 lines, +6,204 chars, 14 hunks**). Section headers, endpoint table (54 rows) and error table (38 rows) are byte-identical in structure. **Counts: 21 ambiguity-pins, 7 mismatch-revisions.**

**Carry-forward re-verification (not assumed):**
- All four Step 8 hunks re-verified against current code and kept: §2.8 second-precision rendering (timeutil.py:31-38 + db.py:99-108), §3.3 cancellation boundary (routes/inquiries.py:335-341), and both routing tie-break fallbacks. The §3.2/§3.8 tie-break edit stands on its own merits — `services/routing.py:30-36,57-59` sorts with Python's stable sort over the insertion-ordered `db.analysts` dict, so on a full tie the earliest-registered analyst wins exactly as the PRD now says. No widening/narrowing/reverting needed.
- Step 6 ambiguities: #1 (late fact-check), #2 (UPHOLD → REVISED), #3 (keynote exclusivity), #4 (document `placement_locked`), #6 (decline with empty pool) were still open and are now pinned; #5 (fresh account score) is **already uniquely pinned** by the §2.7 formula and was confirmed empirically at `utilization_score` 25.0 / `active_weighted` 0.0 / `AT_RISK`, so no edit was made.
- Every non-obvious pin was confirmed by running the real app through Flask's test client (no server started, no processes touched): both clock paths, 401/403/400 clock handling, pagination clamping, unknown-field tolerance, decline-empty-pool (409, zero mutation), complete-before-start (409 `ERR_INVALID_STATE`), briefing created `SCHEDULED` v1, decline-by-non-assigned-analyst, own-vendor-only keynote exclusivity (other vendor accepted at share 0.2308), version numbers (account 2; inquiry/briefing/inclusion/doc 1).

**Change list** (`{section} — {insert|revise} — {kind} — what — impl`):

- §2.2 — insert — ambiguity — `api_request_timestamp` is the logical-clock reading, not wall clock — response.py:20
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` clamped, non-numeric falls back to default, clamped values echoed — middleware.py:113-126
- §2.3 — insert — ambiguity — filter params named after resource fields (`<entity>_id` for FKs); empty filters ignored — routes/_common.py:109-114
- §2.4 — insert — ambiguity — `/research/_clock/set_current_utc` served as an alias of the root path — routes/clock.py:14-15
- §2.4 — insert — ambiguity — clock headers: neither OK, one → 401, both → role check (non-PlatformAdmin → 403); unparseable instant → 400 — middleware.py:32-39, clock.py:19-22
- §2.4 — insert — ambiguity — clock re-evaluation fires on single-resource reads (and their dependents), not on collection list reads — routes/*.py list vs read handlers
- §2.5 — insert — ambiguity — for fact-check response and finalize the prohibition is read against the lead analyst (`lead_analyst_conflicted`) — routes/inclusions.py:192, 329
- §2.8 — insert — ambiguity — `weight_pct` bounded 0–1 — routes/inclusions.py:60
- §2.8 — revise — mismatch — the 0.25 late-response penalty is never applied (responses past the deadline are refused) — routes/inclusions.py:336-349
- §2.10 — insert — ambiguity — transition-at-create resources start at version 1; a create that recomputes derived fields (ClientAccount) returns version 2 — db.py:51-67, routes/clients.py:74
- §2.10 — insert — ambiguity — `decline_reason`/`cancel_reason`/`termination_reason`/`revision_reason`/`rationale`/`comments`/`response_summary`/`correction_offered` are validated but never persisted — routes/inquiries.py:222,313; documents.py:214; inclusions.py:274,312; sales.py:86; sponsorships.py:151
- §2.11 — insert — ambiguity — undeclared body fields are ignored — middleware.py:48-55
- §3.1 — insert — ambiguity — entitlement list is descriptive (no error gates reads); unknown override member → 400 — services/scoring.py:46, routes/seats.py:38-49
- §3.2 — insert — ambiguity — decline with an empty re-route pool → 409 `ERR_ANALYST_NOT_ELIGIBLE`, zero mutation — routes/inquiries.py:233-239
- §3.3 — insert — ambiguity — completion outside `IN_PREP` or before `scheduled_start_utc` → 409 `ERR_INVALID_STATE` — routes/inquiries.py:269-274
- §3.5 — revise — mismatch — late response refused (lapse recorded first, precedence over state check); `fact_check_late` always false; penalty and two-late-rounds exclusion unreachable — routes/inclusions.py:319-349
- §3.5 — insert — ambiguity — fact-check response refused 403 while `lead_analyst_conflicted` — routes/inclusions.py:329-334
- §3.6 — insert — ambiguity — document's own `placement_locked` is a live flag (true while PUBLISHED; cleared on revise) — routes/documents.py:188, 220
- §3.6 — revise — mismatch — briefing eligibility = exactly-`INCLUDED` on PUBLISHED + zero active relationships, recomputed not merely set — services/state.py:176-198
- §3.7 — insert — ambiguity — appeal on a non-`PUBLISHED` document → 409 `ERR_INVALID_STATE` — routes/inclusions.py:242-244
- §3.7 — insert — ambiguity — upheld appeal leaves the document at `REVISED` (no auto-advance to `FACT_CHECK`), clears its lock, re-opens rounds — routes/inclusions.py:293-302
- §3.8 — revise — mismatch — briefing created directly in `SCHEDULED`; `PENDING`/`SCREENED` never observable — routes/briefings.py:44-81
- §3.8 — revise — mismatch — confirmed briefing created at version 1 (was "version incremented") — db.py:51-59
- §3.8 — insert — ambiguity — decline iff `decline_reason` present and `held_at` absent; supplied `held_at` ignored; decline not assignment-gated; held before start → 409 — routes/briefings.py:111-132
- §3.9 — revise — mismatch — append checks apply to `DRAFT`/`PROGRAMMING`/`AGENDA_LOCKED`, not only `PROGRAMMING` — routes/events.py:126-156
- §3.9 — revise — mismatch — keynote exclusivity reads only the row's own vendor on this event, no own-sponsorship exemption, half-open windows — routes/events.py:53-74,143
- §3.9 — insert — ambiguity — absent `sponsor_vendor_id` skips the check and stores null — routes/events.py:121,140
- §5 — insert — ambiguity — undeclared path → `ERR_NOT_FOUND` 404, bad method → `ERR_METHOD_NOT_ALLOWED` 405, crash → `ERR_INTERNAL` 500, outside the catalogue — app.py:54-68

No files outside `workspace/PRD_COMPLETED.md` were created or modified (probe scripts were written to `/tmp` and deleted; the pre-existing `implementation/__pycache__` was untouched).

### Orchestrator final verification

- **Silent-no-op check:** `diff -q workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` → files **differ**, so Step 9 genuinely wrote content (a killed-mid-flight Step 9 leaves a byte-identical copy). Line counts: PRD.md 419/77037, PRD_FINALIZED.md 419/78159, PRD_COMPLETED.md 421/84363.
- **Sweep-integrity re-check after Steps 8 and 9:** `find workspace/implementation -name '*.py' -not -path '*__pycache__*' -newermt '2026-10-01 13:30:35'` returns **empty** — no implementation source file was modified after the clean 8-round sweep. The 87/87 result therefore still stands and no re-run is required.
- **Sweep artifacts intact:** all 8 `workspace/implementation/results.{1..8}.json` present (Step 7 did not delete its own evidence this time).
- **Final workspace tree:** `INSTRUCTION.md`, `PRD.md`, `PRD_FINALIZED.md`, `PRD_COMPLETED.md`, `implementation/` (with `results.1..8.json`).

## Pipeline complete — 2026-10-01T14:01:00.000Z

All nine steps finished. Final state: **87/87 tests passing in all 8 rounds of the final stability sweep**; 0 tests deleted across the entire pipeline; 3 `implementation/` fixes and 6 `test_suite/` fixes applied at Step 7 (0 `test_helpers/` fixes); 4 PRD hunks at Step 8; 14 hunks (21 ambiguity-pins, 7 mismatch-revisions) at Step 9. Deliverables: `SCAFFOLD.yaml` (54 endpoints, 11 entities, 37 error codes), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (24 instances), `SCAFFOLD_CORNER_DESIGN.yaml` (39 instances), `test_helpers/` + `test_suite/` (87 tagged tests), `workspace/PRD.md` → `PRD_FINALIZED.md` → `PRD_COMPLETED.md`, and `workspace/implementation/` (Python + Flask, in-memory, 54/54 endpoints, boots from `bash start.sh`).
