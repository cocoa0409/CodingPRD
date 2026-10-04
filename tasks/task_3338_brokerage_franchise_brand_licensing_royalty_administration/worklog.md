# Worklog — task_3338_brokerage_franchise_brand_licensing_royalty_administration

## Step 1: Create Task Directory — 2026-09-30T21:39:08.210Z

Pre-allocated task directory `tasks/task_3338_brokerage_franchise_brand_licensing_royalty_administration/` confirmed to exist with `workspace/` inside. No new index computed; no other task_* directory created.

## Step 2 (attempt 1, interrupted) — 2026-10-01T04:08:36.194Z

Prior run's Step 2 subagent was killed mid-flight by host memory pressure. Found `SCAFFOLD.yaml` (63KB, valid YAML but completeness unverifiable) and `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (58KB, valid YAML, possibly truncated); `SCAFFOLD_CORNER_DESIGN.yaml` missing entirely. All partial outputs deleted; Step 2 redone from scratch below.


## Step 2 (attempt 2, completed) — 2026-10-01

Scaffold regenerated from scratch. Three files written:
- SCAFFOLD.yaml: 15 entities, 60 endpoints, 29 errors, 30 validations, 9 calculations, 8 state machines, 2 OCC concurrency rules.
- SCAFFOLD_DIFFICULTY_DESIGN.yaml: 9 rules × 2 instances = 18 instances.
- SCAFFOLD_CORNER_DESIGN.yaml: 22 instances across 9 sections (1 excluded_because stub).
Lint verdict: clean (60 endpoints, 15 entities, 18+21 instances, 428 calls scanned).

## Step 3: Copy Shared Files — 2026-10-01T04:33:30.711Z

Copied `./INSTRUCTION.md` → `tasks/task_3338_brokerage_franchise_brand_licensing_royalty_administration/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-01T04:44:54.779Z

Attempt 1 hit a transient model API error (model_not_found 404) mid-flight, leaving a truncated 173-line PRD.md; deleted and regenerated from scratch. Attempt 2 summary (verbatim):

All contracts pass. The PRD is complete.

**Output:** `workspace/PRD.md` — 285 lines.

**Section list:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 RBAC & role identity (incl. entity_backed vs opaque semantics), 2.2 Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Resource Identity/Versioning (incl. the three append-only entities without `updated_at`/`version`), 2.5 Money/Rates/Rounding (round-per-leg-then-sum pinned), 2.6 OCC on activate/amend, 2.7 Logical Clock + expiry sweep (pinned startup default 2026-09-01T00:00:00Z), 2.8 Nested path validation, 2.9 Validation priority ordering
- §3 Business Logic: 3.1 Brands/Markets/Brokerages, 3.2 Agreement terms & renewal, 3.3 Conversion & activation, 3.4 Agents & monthly reporting, 3.5 Royalty assessment (5-step pipeline + provisional variant + ad-fund accrual), 3.6 Ad fund ledger/councils/proposals/voting/execution, 3.7 Audits, 3.8 Defaults/suspension/termination, 3.9 De-identification/closure/wind-down cascades
- §4 Endpoint table (orchestrator-verified: 60 endpoint rows, matching SCAFFOLD.yaml's 60 endpoints — the subagent's "44" was a miscount), §5 Error catalogue (29 errors, 2 columns)

**Hard contract results (all PASS):**
- Contract 1 Field-Name Coverage: 68 required, 68 present, 0 missing (one initial miss — `category` — repaired in §3.9).
- Contract 2 Rule Coverage: all 30 validations matchable to error IDs in prose; both OCC rules expressed with endpoint framing + `expected_agreement_version` + `ERR_STALE_VERSION`/412; all 9 calculations expressed in precise prose; all state transitions with preconditions and cascades.
- Contract 3 §3 Path Purity: 381 backtick tokens scanned in §3, 0 path/method violations.

**Notable information-scattering decisions:**
- Royalty constants (50% rebate, 10000 bps denominator) embedded only in §3.5 narrative, not as named constants.
- OCC rule in §2.6, activation/amendment workflows consuming it in §3.2–3.3.
- `reported_by_role` variant-selection split across §3.4 (reporting) and §3.5 (assessment).
- Vote-safety rules split from council eligibility within §3.6; quorum arithmetic and auto-resolution separated by paragraphs.
- 60-day de-identification window introduced at termination (§3.8), advisory-not-gating semantics deferred to §3.9.
- §2.9 names every business validation in priority order without error codes for most, leaving code-to-condition pairing to §3 narratives.

## Step 5: Generate Unit Tests — 2026-10-01T05:00:18.148Z

Subagent summary (verbatim):

All 58 tests collect cleanly. Final summary:

**Files written**

test_helpers/ (task root):
- `test_helpers/types.py` — 13 status/type enums, 15 entity TypedDicts (append-only `AgentCountReport`/`GCIReport`/`AdFundLedgerEntry` omit `updated_at`/`version` per PRD §2.4)
- `test_helpers/api_client.py` — `ApiClient(GenericApiClient)` with all PRD endpoints
- `test_helpers/api_errors.py` — 29 error IDs + HTTP status map, registered via `set_error_http_status_map`
- `test_helpers/assertions.py` — per-entity assertions
- `test_helpers/factories.py` — payload factories (input fields only)
- `test_helpers/constants.py` — clock default, BPS denominator, REBATE_PCT=50, cure/de-identify windows, five task categories
- `test_helpers/test_users.py` — `TEST_USERS` + `make_franchisee_admin_headers(brokerage_id)` for the entity-backed role
- `test_helpers/fixtures.py` — composite fixtures: `setup_draft_agreement`, `setup_agreement_with_plan`, `setup_active_agreement`, `setup_assessed_period`, `setup_suspended_agreement`, `setup_deidentifying_agreement`, `setup_closed_agreement`, `setup_brand_with_seated_brokerages`, `setup_submitted_proposal`, `open_default`, `submit_gci_report`, `assess_period`, `cast_votes`
- `test_helpers/__init__.py` — barrel export (verified importable)

test_suite/: `conftest.py` + 11 test files (`test_01_royalty_calculation` … `test_11_conversion_readiness`).

**Test counts**
- Queue A (Difficulty): 17/17 instances, 33 tests — every instance ≥2 tests (verified programmatically against the yaml).
- Queue B (Corner): 20 non-stub instances, 25 tests — every non-stub ≥1 test. One stub (`calculations/brand_fund_balance_computed_read_matches_ledger`, `excluded_because` → `ad_fund_collect_minus_spend_balance_conserved`) not translated; its pointer resolves to a real queue-A instance.
- Total: 58 tests, all collected by pytest.

**Instances skipped**: None. All 17 difficulty instances and all 20 non-stub corner instances passed the PRD-first two-condition filter.

**Verification**
- `python3 -m py_compile` passes on all 19 generated `.py` files.
- Every one of the 58 tests carries exactly one `Design:` docstring line copied verbatim from the yaml `name:`; all tags resolve to real instances (machine-checked).
- Every quoted PRD citation in every docstring survives a whitespace-normalized literal match against `workspace/PRD.md` (58/58, 0 failures).
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no "scaffold" references in generated code comments.
- Notable literal derivations re-verified independently: tier-split rounding instance `63,300/84,399`, threshold-boundary `28,750,000`, provisional-vs-final cap case `0/18,000,000` with agreement counters `50,000,000/1,200,000,000`, quorum floor(5/2)+1=3 auto-approve, ad-fund suspension zero-accrual.

Orchestrator verification: py_compile re-run clean on all test files; 58 test functions / 58 Design tags confirmed by grep; `api_client.py` covers 60/60 unique PRD endpoints (subagent's "44" was a miscount — PRD table has 60 unique method+path rows).

## Step 6: Generate Implementation — 2026-10-01T08:57:21.288Z

Two prior attempts died to transient `model_not_found` API errors (k3-wave endpoint), each leaving partial `workspace/implementation/` output that was deleted. Third attempt (new model endpoint) completed. Subagent summary (verbatim):

All 60 routes registered, matching the SCAFFOLD §1.5 endpoint table exactly. Server stopped cleanly. Implementation complete.

**Files written** (all under `workspace/implementation/`): `start.sh` (7 lines, foreground launcher, `exec python3 app.py`), `requirements.txt` (flask>=3.0), `app.py` (48, Flask assembly, envelope-ified 404/405/500 handlers, 0.0.0.0:$PORT default 10000), `db.py` (94, empty in-memory stores, logical clock boots at exactly `2026-09-01T00:00:00Z`), `errors.py` (9, ApiError), `envelope.py` (72, meta/response_type/data envelope, limit/offset pagination default 10, 1..100), `helpers.py` (82, body/field validators, serializer strips `_`-internal keys), `auth.py` (48, X-User-Role ∈ {FranchisorOps, FranchiseeAdmin, BrandAuditor} → 401; X-User-ID required only for entity-backed FranchiseeAdmin; reported_by_role mapping), `services.py` (238, royalty 5-step pipeline with per-leg floor, cap before rebate, rebate `(high·(B−V)·50)//1_000_000`, provisional = raw, calendar-year counter reset, ad-fund accrual 0 + no ledger entry when SUSPENDED, SUSPENDED→ACTIVE resume, DEIDENTIFYING→CLOSED, Brokerage→TERMINATED + agent cascade, council eligibility, fund balance), `routes_core.py` (207, brands/markets/brokerages/agents), `routes_agreements.py` (352, agreements incl. OCC amend/activate, conversion plans), `routes_billing.py` (245, reports, royalty periods, default cases), `routes_funds.py` (226, councils, proposals/votes/execute), `routes_ops.py` (160, audits, de-identification, clock).

**Endpoint count: 60** (the §1.5 table's actual count; the `endpoint_count: 44` in complexity_profile is stale).

**Boot verification**: PORT=18777 boot in <3s; bare GET /franchise/brands → 401 with envelope; smoke verified stale-version ERR_STALE_VERSION, milestone→ready→activate flipping brokerage FRANCHISED, royalty math (G=120M, B=600, V=300, T=100M, cap=500k → due=200000, provisional=6600000, ad_fund=2400000 — hand-verified), suspend/resolve auto-resume, escalate→terminate→DEIDENTIFYING, 5-task verify→CLOSED→brokerage TERMINATED, council quorum auto-approve at exactly 2/3, ERR_NOT_COUNCIL_MEMBER/ERR_DUPLICATE_VOTE, execute debiting balance 100000→50000, clock regression ERR_CLOCK_REGRESSION, expiry sweep to EXPIRED. Killed exactly PID 2710793 afterward.

**Notable design decisions**: logical clock drives business timestamps, wall clock drives created_at/updated_at/meta; version starts at 1 and bumps on every mutation including cascades; activation business-check order follows PRD §3.3 (conversion-ready before territory conflict); report/assessment business-rule order follows scaffold priorities (duplicate → missing GCI report → agreement liveness; votes: duplicate → membership → segregation); duplicate brand_code/market_code → ERR_INVALID_REQUEST; expected_agreement_version missing/non-int → 400, present-but-wrong → 412; no seeding anywhere — stores start empty per the isolation contract.

Orchestrator verification: py_compile clean on all .py files; 60 route decorators counted; independent boot test on PORT=18779 — server booted, `GET /franchise/brands` returned a correct paginated envelope (`total_count: 0, has_more: false`), POST with a deliberately wrong field returned a proper `ERR_INVALID_REQUEST` envelope. Server killed by exact PID.

## Step 7: Run Tests and Iterate — 2026-10-01T09:01:51.579Z

Subagent summary (verbatim):

All verification checks pass:
- All 8 rounds: 58/58 passed, 0 failed, 0 errors
- Each results file contains 58 real test entries (not truncated/empty)
- Newest implementation source mtime (08:53:56) predates sweep results (09:01:07) — no post-sweep writes invalidate the run
- No test-suite edits were made by me; the sweep reflects the artifact as shipped by Steps 5/6

Summary:
- **Iterations run**: 1 (clean 8-round parallel sweep on first iteration — no fixes needed)
- **Tests deleted**: none
- **Fixes applied to `test_helpers/`**: none
- **Fixes applied to `test_suite/`**: none
- **Fixes applied to `implementation/`**: none

The task is stable: all 58 tests pass in all 8 concurrent rounds under `--isolation per-test-server`, so no flakiness signal exists to chase. Results evidence is preserved at `workspace/implementation/results.{1..8}.json`.

Orchestrator verification: independently parsed all 8 `results.{1..8}.json` files — each reports passed=58, total=58, failed=0, errors=0, with 58 entries per file.

## Step 8: Finalize PRD — SKIPPED — 2026-10-01T09:01:51.579Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced.

## Step 9: Complete PRD — 2026-10-01T09:19:00.880Z

Subagent summary (verbatim):

Line counts match (285 = 285), the tail (error catalogue) is intact, char delta is +3644 across exactly 21 revised paragraphs (42 diff lines), matching 19 edits (two edits each spanned two paragraphs).

**Source vs completed:** `workspace/PRD.md` (285 lines, 43732 chars) → `PRD_COMPLETED.md` (285 lines, 47376 chars; +3644 chars).

**Counts:** 17 ambiguity-pins, 4 mismatch-revisions.

**Changes:**
- §1 — revise — mismatch — "forty-four endpoints" → "sixty endpoints" (impl mounts 60 routes; §4 table itself has 60 rows) — implementation/*.py (@bp.route count)
- §2.1 — insert — ambiguity — ownership scoping applies only to the mutating endpoints (agent register/deactivate/reactivate, report submission, task completion); reads and milestone completion are unscoped — routes_core.py:171, routes_billing.py:56, routes_agreements.py:336
- §2.3 — insert — ambiguity — non-integer/out-of-range limit/offset → ERR_INVALID_REQUEST; created_at ties broken by insertion order; has_more = offset + returned < total_count — envelope.py:56-72, helpers.py:75-82
- §2.6 — insert — ambiguity — absent/non-integer expected_agreement_version → ERR_INVALID_REQUEST (400) — routes_agreements.py:41-50
- §2.7 — insert — ambiguity — clock-set returns 200 with data.current_utc; setting the current instant is accepted; business timestamps (activated_at, reported_at, settled_at, opened_at, cure_deadline, escalated_at, started_at, due_at) read the logical clock while created_at/updated_at read wall clock; the expiry sweep never transitions a Brokerage — routes_ops.py:140-160, services.py:30-48
- §2.9 — revise — mismatch — business-rule enumeration reordered so territory conflict follows conversion readiness (activation checks plan-readiness first); ownership/existence interleave pinned: path-brokerage ownership precedes existence, entity-derived ownership follows loading the resource — routes_agreements.py:222-233, routes_core.py:139-141/180-182, routes_billing.py:30-31, routes_ops.py:107-110
- §3.1 — insert — ambiguity — duplicate/malformed brand_code and duplicate market_code → ERR_INVALID_REQUEST — routes_core.py:26-31, 79-80
- §3.2 — insert — ambiguity — term_start/term_end accept any parseable ISO 8601 date or datetime; unparseable → ERR_INVALID_REQUEST — routes_agreements.py:53-59
- §3.2 — insert — ambiguity — nested per-brokerage agreement roster accepts a status filter — routes_agreements.py:157-162
- §3.3 — insert — ambiguity — at most one ConversionPlan per agreement; second create → ERR_INVALID_REQUEST; malformed milestones array/permutation → ERR_INVALID_REQUEST — routes_agreements.py:287-314
- §3.3 — revise — mismatch — milestone completion by "a FranchiseeAdmin" (impl performs no ownership check), not "the owning FranchiseeAdmin" — routes_agreements.py:335-352
- §3.3 — insert — ambiguity — activation with brand no longer ACTIVE → ERR_INVALID_STATE (error code previously unnamed) — routes_agreements.py:219-221
- §3.4 — insert — ambiguity — reactivating an agent under a PROSPECT brokerage → ERR_INVALID_STATE (only TERMINATED was pinned) — routes_core.py:196-204
- §3.4 — insert — ambiguity — period_month must be YYYY-MM with month 01–12, else ERR_INVALID_REQUEST — helpers.py:9, 47-51
- §3.5 — insert — ambiguity — "most recent prior period" pinned as latest by period_month, not by assessment order — services.py:149-154
- §3.6 — insert — ambiguity — council member ids must be distinct and seat_count odd/≥3, violations → ERR_INVALID_REQUEST; unseated outgoing → ERR_INVALID_REQUEST; incoming already seated on the same council → ERR_COUNCIL_INELIGIBLE_MEMBER — routes_funds.py:33-46, 83-92
- §3.6 — revise — ambiguity — vote rules evaluated in impl order (duplicate → membership → segregation), reversing the narrative's listing order; successful vote returns HTTP 201 — routes_funds.py:170-202
- §3.7 — insert — ambiguity — audit start checks SCHEDULED then agreement ACTIVE, each failing with ERR_INVALID_STATE — routes_ops.py:50-55
- §3.8 — insert — ambiguity — a recompute leaving open_cure_count unchanged is not a mutation; resolving an ESCALATED case does not bump the agreement version — services.py:69-75
- §3.9 — revise — mismatch — ERR_DEIDENTIFICATION_INCOMPLETE trigger is a five-category presence check on every verify call (before marking VERIFIED), not "a verify that would close the file without all five verified" — routes_ops.py:124-129

All other PRD passages (royalty five-step pipeline, rounding discipline, cap/rebate order, year-reset rule, ad-fund accrual incl. SUSPENDED pause, council quorum arithmetic, termination compound event and cascades, closure propagation, error catalogue, endpoint/role table) were verified line-by-line against implementation/ and already pinned behavior uniquely — no changes needed.

Orchestrator verification: `diff -q` confirms PRD_COMPLETED.md differs from PRD.md (not a silent no-op); 42 diff lines match the reported edit count; spot-checked the §1 "sixty endpoints" revision is present; 0 references to forbidden sources (implementation/scaffold/test_suite paths) leaked into the document. No implementation .py file is newer than the Step 7 sweep results (results.1.json @ 09:01), so Step 9 did not touch implementation/ and the clean 8-round sweep remains valid — no re-run needed.
