# Worklog — task_3378_business_accreditation_complaint_mediation_rating_methodology

## Step 1: Create Task Directory — 2026-10-01T11:10:00.000Z

Task directory was pre-allocated by the command invocation; verified `./tasks/task_3378_business_accreditation_complaint_mediation_rating_methodology/workspace/` exists. No new index computed, no other task_* directory created. Difficulty directive from user: "Generate task much harder than expert level!" (for prd-bench-scaffold-generator only).

## Step 2: Generate Scaffold — 2026-10-01T12:55:00.000Z

Wrote SCAFFOLD.yaml (§1.0–§1.7), SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8: 9 rules × 2 = 18 instances), SCAFFOLD_CORNER_DESIGN.yaml (§1.9: 53 active + 6 excluded stubs across 9 sections). 40 endpoints (at cap), 12 entities, 10 state-machine entries (cyclic complaint rebuttal, cyclic application reapply, parallel Business dimensions), 7 calculations with 49 pinned constants, 12 validation priorities, 43 errors, 4 roles, 1 OCC concurrency rule (rating-dispute create on Business.version). Logical clock pinned at 2026-09-01T00:00:00Z via POST /_clock/set_current_utc. scaffold_lint.py: clean (796 calls scanned, 0 violations). All formula-derived assert literals recomputed by code; two literal bugs (hysteresis age band, 183-day age-gate boundary dates) caught and fixed pre-handoff. Difficulty directive "much harder than expert" applied via depth: hysteresis suspension/revocation loops, dual-variant rating + dues, depth-4 cascades, buffered vs half-open overlap geometries.

## Step 3: Copy Shared Files — 2026-10-01T12:59:00.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-10-01T13:30:00.000Z

Generation complete and all verification passed. Summary below.

### Output

`workspace/PRD.md` — **328 lines**, written in 6 sequential chunks and verified on disk (tail ends at the §5 error catalogue, no truncation, no audit footer).

### Section list

- **1. Introduction** (2 paragraphs)
- **2. Global Specifications** — 2.1 RBAC (with per-role `identity:` translations), 2.2 API Response Structure (byte-verbatim from section-2.2-response-structure.md, confirmed by containment check), 2.3 Pagination, 2.4 The Logical Clock and the Daily Close, 2.5 Common Resource Properties, 2.6 Nested Resource Retrieval, 2.7 Validation Cascade and Priority Order (all 12 priorities in prose), 2.8 Optimistic Concurrency Control, 2.9 Money/Integers/Rounding
- **3. Business Logic** — 3.1 Bureaus/Territories/Parties, 3.2 Accreditation Application Journey, 3.3 Dues/Invoicing/Payment Ledger, 3.4 Complaint Intake/Response Cycle, 3.5 Mediation and Arbitration, 3.6 Rating Methodology, 3.7 Publication/Suspension Scan/Disputes, 3.8 Advertising Review and Scam Surveillance (8 subsections, zero HTTP paths/methods)
- **4. Endpoint Definitions** — 40 rows (matches scaffold exactly), 4 columns
- **5. Error Code Catalogue** — 43 rows (matches scaffold exactly), 2 columns

### 10-literal grep self-check (12 checked, all found in prose sentences)

`2026-09-01T00:00:00Z`: 1; `730 days`: 1 (2 uses); `183 days`: 2; `365 days`: 4; `1209600` (14-day window in seconds): 1; `119946` (quarterly worked total): 1; `42500` (MICRO base): 1; `29987` (installment): 1; `240000` (LARGE base): 1; `30 minutes` (hearing buffer): 1; `1095 days` (rating window): 2; `10 days` (dispute window): 1. Orchestrator spot-check reproduced these counts.

### Hard Contract reports

- Field coverage: 113 required, 113 present, 0 missing; envelope/pattern/response-entry identifiers all present. PASS
- Rule coverage: 12-priority validation cascade as ordered 12-step prose; OCC 1/1; all 47 distinct states + transitions + side effects expressed (incl. last_unresolved_at non-refresh, refunds-never-revert, FILED zero-duration, OVERDUE self-loop, parallel-dimension independence); calculations 7/7 in precise prose with worked dues example; errors 43/43. PASS
- Path purity (§3, fence-stripped): 670 backtick tokens scanned, 0 HTTP paths/methods. PASS

Additional hygiene: no fuzzy words, no pseudocode operators, all enum values + 12 grades present, endpoint table 40/40. The two difficulty-design files were never opened.

## Step 5a: Generate Test Helpers (split Step 5, part 1) — 2026-10-01T13:50:00.000Z

Step 5a is complete and verified. Summary:

### Files written (10)

- `test_helpers/__init__.py` (44) — barrel export: framework generics + all PRD-specific modules
- `test_helpers/types.py` (456) — `UserRole` + 27 domain enums, status-partition tuples (OPEN/CLOSED/OUTCOME/PENDING), 13 entity TypedDicts (all carry id/created_at/updated_at/version per PRD §2.5)
- `test_helpers/api_client.py` (207) — `ApiClient(GenericApiClient)` with exactly 40 endpoint methods (matches PRD §4), plus module-level singleton
- `test_helpers/api_errors.py` (116) — `ApiErrorId` enum (43 ids, matches PRD §5) + HTTP status map, registered via set_error_http_status_map at import
- `test_helpers/assertions.py` (311) — 13 assert_<entity>() validators + invariant checkers: invoice balance arithmetic, installment plan shape, snapshot total/score/grade arithmetic, scam-pattern row
- `test_helpers/factories.py` (288) — 19 payload factories, PRD-verbatim field names/enums; optional fields omitted when overridden with None; auto-unique emails/names/licenses
- `test_helpers/constants.py` (221) — all thresholds with `# PRD §x.y` group comments + derived helpers (expected_dues_amount_cents, expected_installments, expected_size_tier, expected_grade, Decimal round-half-up)
- `test_helpers/test_users.py` (57) — TEST_USERS (opaque roles canonical; entity-backed as non-ownership fallback) + make_business_rep_headers/make_consumer_headers per-instance builders
- `test_helpers/fixtures.py` (752) — 65 helpers across all 5 tiers: clock helpers (set_clock, iso_plus_days/minutes/seconds), atomic creators, setup_world, accreditation journey through setup_accredited_business, full complaint/mediation/arbitration lifecycle chains, rating/dispute, ad-review, scam-report, sweep-based expiry, accumulation targeting
- `test_suite/conftest.py` (61) — session-scoped api fixture + 4 role-header fixtures + 2 per-instance header-builder fixtures

### Verification results
- py_compile: all 10 files pass; import of the package from task root passes; no duplicate fixture defs (orchestrator re-verified both)
- Constants grep: all required literals present with PRD-sourced values — 2026-09-01T00:00:00Z (§2.4), 1209600 (§3.4), 42500/240000 (§3.3), 29987 (§3.3 worked example), 75/80 (§3.7), 183 (§3.2), 365 (§3.2/§3.8), 730 (§3.7), 1095 (§3.6), rebuttal cap 3 (REBUTTAL_MAX, §3.4), hearing buffer 30 (HEARING_ROOM_BUFFER_MINUTES, §3.5). PRD-side grep confirms each literal appears in PRD.md.
- Helper smoke test: derived dues/grade/tier functions reproduce every PRD worked example exactly (109566, 119946/[29987,29987,29987,29985], 40423 half-cent round-up, 40375/64600/109250 zero-fee prepaid, 119715/[29929,29929,29929,29928]) and the 90→A_MINUS / 89→B_PLUS boundary.

### Hand-off notes for Step 5b (carried into 5b prompt)
1. Party-response enum drift: design recipes send `response: "ACCEPT"/"DECLINE"`, but PRD §3.5 verbatim says the payload carries `ACCEPTED` or `DECLINED`. Frozen factories emit the PRD values; 5b must translate recipe payloads to ACCEPTED/DECLINED.
2. Success statuses explicit: creations return 201 (incl. ledger entries, complaint responses, snapshots, disputes, DENIED-application reset), transitions/reads 200 — always pass expected status to validate_success.
3. No single-invoice GET exists — use fixtures.get_invoice(business_id, invoice_id) (lists and matches by id); same for get_application.
4. Clock discipline: fixtures pin the clock via set_clock() and advance only via iso_plus_* + run_daily_close; setup_unanswered_complaint/expire_* leave the clock advanced, matching the design recipes' clock choreography.
5. Ownership threading mandatory: ownership-gated calls use make_business_rep_headers(business["id"]) / make_consumer_headers(consumer["id"]) — never shared TEST_USERS constants.

## Step 5b: Generate Test Suite (split Step 5, part 2) — 2026-10-01T14:45:00.000Z

Step 5b complete. All artifacts verified.

### Summary

**Files written: 18 test files, 3587 lines, 89 tests** in `test_suite/` (nothing in `test_helpers/` or `conftest.py` touched).

**Grouping plan (as stated up front):** Queue A got one file per difficulty rule (`test_10`–`test_18`); Queue B got section-grouped files (`test_20` entities, `test_21`/`test_22` state machines split complaint-med-arb vs application-invoice-dispute, `test_23`/`test_24` calculations split plain vs suspension-scan, `test_25` validations, `test_26` roles, `test_27` endpoints+errors, `test_28` complexity+consistency).

**AST tag audit (real `ast` parse, not grep):**
- 89 test functions, 71 distinct `Design:` tags; every tag is the docstring's last line; 0 untagged, 0 dual-tagged, 0 tags failing to resolve to an index instance. (Orchestrator spot-check: 71 unique tags via grep, 89 collected.)
- Queue A (Difficulty): **18/18 instances covered with exactly 2 tests each** (36 tests).
- Queue B (Corner): **53/53 non-stub instances covered with 1 test each** (53 tests).
- 6 `excluded_because` stubs correctly not translated; all 6 cross-references resolve to real difficulty instances.
- **Skips: none.** Every non-stub instance passed the PRD-first two-condition filter.
- PRD citation sweep: every `PRD §x.y: "..."` quote in every docstring survives a whitespace-normalized literal grep of `workspace/PRD.md` (102-quote pool pre-verified; one `CONSUMER_REBUTTAL`→`CONSUMER_REBUTED` typo caught by the audit and fixed).

**Collection:** `python3 -m pytest test_suite/ --collect-only -q` → **89 tests collected**, no import errors (orchestrator re-verified: 89 in 0.22s).

**Adjudications made (design vs PRD; PRD won):**
1. **Grade literal contradiction in `Difficulty/non_linear_state_machine/business_parallel_dimensions_move_independently`:** the recipe asserts grade C_PLUS at score 67, but PRD §3.6's inclusive floors put 67 at C (C_PLUS starts at 70). Asserted `score == 67, grade == "C"`.
2. **Timestamp literals relaxed to parsed-instant comparison** (parse_iso(a) == parse_iso(b) / timedelta arithmetic): PRD §2.4 pins the clock value while §2.5 demands three fractional digits on `created_at`, so exact-string equality is not uniquely derivable. Applied to `created_at`, `filed_at`, deadlines, `decided_at`, `voided_at`, `published_at`, `window_start_at`, `due_date`, `referred_at`.
3. **`version == 1` literals relaxed:** PRD §2.5 pins +1-per-mutation but never the initial value. Bureau defaults test uses the frozen helper's `version >= 1`; the extra-fields test asserts `version != 99` (client value overridden — the actual rule under test). The OCC test threads captured versions only.
4. **Recipe enum translation** per hand-off note: `ACCEPT`/`DECLINE` → `ACCEPTED`/`DECLINED` everywhere.
5. **All success codes explicit** per hand-off: creations `validate_success(resp, 201)`, transitions/reads 200; errors via `validate_error` with the registered status map.

**Hand-off notes for Step 7:** no single-GET endpoints exist for invoices/applications/cases/reviews/disputes/snapshots — tests read them via list-and-match-by-id; the 401 test passes `headers={}` to omit auth headers entirely; `GET /scam-patterns` data is read as `validate_success(resp, 200)["patterns"]` (object envelope with a `patterns` array, not a bare list).

## Step 6: Generate Implementation — 2026-10-01T15:40:00.000Z

Implementation complete and fully verified. Final report:

### Module list (workspace/implementation/, 2796 total lines)

- `constants.py` (180) — every pinned literal from PRD prose (clock start, dues bases 42500/68000/115000/240000, 0.95/1.04 plan multipliers, 183/365/730/1095-day gates, 1209600s response window, 75/80 hysteresis, rebuttal cap 3, 30-min hearing buffer, 12 grade floors, all enums)
- `errors.py` (73) — ApiError + complete 43-error catalog with PRD §5 HTTP statuses
- `db.py` (157) — in-memory dict stores (12 entity kinds), logical clock, entity factory (id/created_at/updated_at/version), ISO8601 millis-Z serialization, _seq tie-breaker
- `web.py` (212) — envelope (meta/response_type/data, pagination fields in meta), auth (X-User-ID/X-User-Role, 401/403), pagination (limit default 10, min 1, max 100, offset 0), schema validators
- `domain.py` (475) — size tiers, live-derived counters, dues pricing (Decimal + ROUND_HALF_UP at the two pinned points), rating_score (8 deduction components, both variants), snapshot generation, provisional regen, latest-published selection, the 4-sweep daily close with suspension scan
- `routes_core.py` (210) — bureaus, run_daily_close, consumers, businesses, clock (7 endpoints)
- `routes_accreditation.py` (372) — applications create/reapply/list/submit/decision, invoices list + ledger entries (6)
- `routes_complaints.py` (255) — complaints CRUD, forward, responses, reopen (6)
- `routes_escalation.py` (339) — mediation (5) + arbitration (4)
- `routes_rating.py` (195) — snapshots compute/list, disputes file/appeal/list (5)
- `routes_surveillance.py` (237) — advertising reviews (3), scam reports (3), scam-patterns (1)
- `app.py` (80) — Flask assembly, ApiError + 404/405/500 handlers
- `start.sh` (10) — guarded pip install (no-op once flask present), exec python3 app.py, PORT env, 0.0.0.0
- `requirements.txt` (1) — flask>=2.2,<4

### Verification results (orchestrator spot-checked: 12 modules compile, exactly 40 route decorators, start.sh guarded+exec)

- Endpoint count: 40/40 — @bp.route grep confirms exactly 40 unique routes, matching the scaffold table.
- py_compile: OK on all 12 modules.
- Boot smoke test: OK — fresh process boots in <3s, store starts empty (total_count: 0), clock reads exactly 2026-09-01T00:00:00Z; killed by exact PID afterward. Ran 5 scenario suites (~90 assertions) covering: 401/403 auth paths, territory exclusivity, ERR_TERRITORY_UNCOVERED, ownership 403s, age gate at 183 days, reapply cooling, the PRD worked dues example (115333 subtotal → QUARTERLY 119946 with [29987, 29987, 29987, 29985]; ANNUAL_PREPAID at 64600 and 249600), payment/refund state machine incl. PAID→REFUNDED and PARTIALLY_PAID→ISSUED, overpay/over-refund 422s, OVERDUE→VOID→EXPIRED cascade, the 365-day void gate (ERR_OUTSTANDING_DUES_BALANCE), auto-unanswered sweep with inclusive deadline boundary, mediation offer/party/schedule/conclude, mediator half-open overlap (adjacency allowed), hearing 30-min buffer (adjacency conflicts), arbitration lineage + decision, rating math (score 63/75/84/88/94 verified component-by-component), OVERRULED dispute recomputation with excluded_complaint_id + superseded_by_id, OCC 412, full suspension lifecycle (hysteresis at 75, SUSPENDED at 63, reinstate at 88, REVOKED on second suspension, REVOKED terminal), scam pattern flag, pagination meta.
- Constants cross-check: OK — every threshold/window/amount/weight greps to PRD prose.
- Dead-code grep: OK — every domain/web helper has ≥1 callsite outside its definition; one superseded helper (list_response) found and removed.

### Key fidelity decisions (from PRD prose, where ambiguous)

- `last_unresolved_at` stamps on first entry into UNRESOLVED only; mediation decline/expiry never refreshes it (PRD §3.4/§3.5 explicit).
- Provisional regen fires exactly where the workflow sections note it (verdicts, auto-unanswered, reopen, mediation concludes, arbitration decision, ad open/conclude, scam publish, sweep-driven counter changes) — not on filing/forward/mediation-offer, per §3.6's "the workflows … each note where this fires."
- `Business.version` bumps on every mutation per PRD §2.5; OCC applies only to rating-dispute filing (expected_business_version, ERR_STALE_VERSION 412).
- REFUND on OVERDUE mutates balances without leaving OVERDUE (no defined transition); PAID+REFUND→REFUNDED only on full net refund; REFUNDED/VOID reject all entries with ERR_INVOICE_INVALID_STATE.
- `current_utc` echoes in second precision when the set value lands on a whole second; all entity/system timestamps use the pinned 3-fractional-digit format.

## Step 7: Run Tests and Iterate — 2026-10-01T16:05:00.000Z

All 8 rounds pass 88/88, results files are in place, and `ERR_OUTSTANDING_DUES_BALANCE` retains positive coverage in `test_25_corner_validations.py`. The loop is complete. (Orchestrator verified: results.1–8.json all show passed 88 / total 88 / failed 0; deleted test absent from test_14.)

**Iterations run:** 2 (sweep 1: 1 consistent failure across all 8 rounds; fix applied; sweep 2: all 8 rounds 88/88 clean).

**Tests deleted (1):**
- `test_outstanding_dues_surfaces_once_advertising_is_clear` (test_suite/test_14_difficulty_priority_pair_validation_conflict.py) — **unique-derivability collapse (two-reader divergence)** on PRD §3.2's gate sentence "The business must have no advertising review in `UNDER_REVIEW` or `REFERRED_TO_REGULATOR`". Reading A (scan AdvertisingReview entities; referred conclusion is terminal per §3.8's "concluding from any other state is rejected", so the gate blocks permanently) and Reading B (read the business's `advertising_compliance_status`, which §3.8 returns to `CLEAR` after a fresh CLEARED conclusion) are both PRD-consistent and diverge exactly on this test's scenario. §3.8's return-to-CLEAR clause is explicitly motivated by the §3.6 rating deduction ("Either conclusion regenerates the business's provisional rating..."), so Reading A strands no PRD machinery. The scaffold rule that drove generation — `validations[priority=8]` / "no AdvertisingReview of the business in {UNDER_REVIEW, REFERRED_TO_REGULATOR}" (SCAFFOLD.yaml) — is the entity-scan reading; the design recipe (SCAFFOLD_DIFFICULTY_DESIGN.yaml `approve_adverse_ad_review_beats_outstanding_dues`) specifies only the still-referred trigger, which the surviving sibling test covers. The shipped implementation matches Reading A and stays.

**Fixes applied to `test_suite/`:** test_14_difficulty_priority_pair_validation_conflict.py — deleted the one test method above plus its now-unused `conclude_advertising_review` import (the file's remaining `api.conclude_advertising_review` call is the client method, unaffected).

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful under the entity-scan reading; no code changed.

**Sibling unasserted implementation paths (test-side fixes outnumber impl-side):**
- `routes_accreditation.py` `decide_application` lines 208-213: the advertising gate's behavior when a concluded-`REFERRED_TO_REGULATOR` review exists but the business's `advertising_compliance_status` has returned to `CLEAR` — no test now pins either outcome for this state combination (permanent block under the shipped reading).
- Positive coverage of `ERR_OUTSTANDING_DUES_BALANCE` survives only via test_25_corner_validations.py; the priority-interaction direction "fiscal gate surfaces after advertising clears" is no longer exercised anywhere.

All 8 `results.{1..8}.json` files from the clean sweep remain in `workspace/implementation/` as output evidence.

## Step 8: Finalize PRD — 2026-10-01T16:25:00.000Z

Done. Verification passes: `diff -q` confirms the files differ (edit landed at line 146), and all `implementation/` source mtimes predate this session — nothing under `implementation/`, `test_suite/`, or `test_helpers/` was touched. (Orchestrator re-verified: single-line diff at §3.2 line 146 containing exactly the inserted pinning sentence; all implementation .py mtimes ≤ 15:34, predating Step 8.)

**Line counts / delta:** PRD.md 328 lines vs PRD_FINALIZED.md 328 lines — 0.0% line-count delta (one sentence inserted inline within the §3.2 paragraph; single-line diff).

**Changes (1 edit, covering both step_7_diff items — the deleted test and the sibling unasserted path are the same gate sentence):**

- §3.2 (Accreditation decision compliance gates) — insert — appended one pinning sentence after the advertising-gate sentence: "This gate inspects the business's advertising-review records, not its `advertising_compliance_status`: a review concluded `REFERRED_TO_REGULATOR` never leaves that terminal state (§3.8), so it keeps blocking approval even after the business's compliance status has returned to `CLEAR`." This pins the entity-scan reading (Reading A) of the formerly ambiguous sentence "The business must have no advertising review in `UNDER_REVIEW` or `REFERRED_TO_REGULATOR`" — `implementation/routes_accreditation.py:208-213` (decide_application scans `db.STORE.advertising_reviews` for the two states, never reads the business field). It also covers the sibling unasserted path (approval permanently blocked by a terminal referred review after status returns to CLEAR) at the same site.

**Per-edit pre-edit search log:**

- Edit 1 (§3.2 advertising gate pin):
  - (a) Subject: what the APPROVE advertising gate reads (AdvertisingReview entity records vs the business's `advertising_compliance_status` field), and the gate's behavior when a terminal `REFERRED_TO_REGULATOR` record coexists with a `CLEAR` business status.
  - (b) Impl paths enumerated and read/grepped: `routes_accreditation.py:206-234` (the gate — read in full; entity scan, lines 208-213); `routes_surveillance.py:50-70` (open review; sticky referral), `routes_surveillance.py:85-119` (conclude — line 94 from-state check makes REFERRED terminal; lines 104-110 return business to CLEAR ignoring terminal referred records), `routes_surveillance.py:125-136` (list/filter); `domain.py:272-276` (rating `advertising_deduction` reads the business status field — 15/5/0 points); `routes_core.py:152` (init CLEAR); `errors.py:49` (error message entity-phrased, consistent); `constants.py:129`; `routes_escalation.py`, `routes_complaints.py`, `routes_rating.py` (grep: no advertising-state references — the suspension scan and rating routes never touch this gate). PRD restatements checked: §2.5 line 110, §3.8 lines 225/227, error table line 309.
  - (c) Wording adjustment: scoped the pin with "This gate inspects ... not its `advertising_compliance_status`" so the claim does not extend to `domain.py:272-276`, which legitimately reads the business status field for the rating deduction (a returned-to-CLEAR business with a terminal referred record correctly gets 0 deduction yet remains approval-blocked — the wording describes the gate only); anchored terminality to §3.8's existing conclude-from-state rule instead of inventing a new transition rule.

**No other edits made:** the remaining step_7_diff items are informational (no impl fix was applied; no test_helper fix; surviving ERR_OUTSTANDING_DUES_BALANCE coverage is a coverage observation, not a PRD silence). No implementation bugs found worth reporting beyond what step 7 already documented.

## Step 9: Complete PRD — 2026-10-01T16:55:00.000Z

Done. `PRD_COMPLETED.md` is written, verified different from the source, and nothing else was touched (newest implementation source mtime 15:34, newest test mtime 15:47 — both predate this session; only `PRD_COMPLETED.md` was created). (Orchestrator re-verified: `diff -q` shows files differ; all 8 results.*.json intact; newest impl source 15:34 predates sweep results 15:50, so the green sweep remains valid — no re-run needed.)

**Files**: PRD_FINALIZED.md (328 lines, 61,376 chars) → PRD_COMPLETED.md (328 lines, 65,150 chars; +3,774 chars, 17 paragraphs revised in place, line count unchanged). Sweep 8 cross-confirmed green (88/88, results.8.json).

**Counts**: 18 ambiguity-pins, 4 mismatch-revisions (22 logical changes across 18 edit operations in 17 paragraphs).

**Ambiguity-pins** (section — what changed — impl cite):
- §2.3 — insert — out-of-range limit/offset are clamped (not rejected); non-integer values get ERR_INVALID_REQUEST; created_at ties break by creation order — web.py:96-138
- §2.4 — insert — current_utc renders at second precision on whole seconds, else three fractional digits — db.py:89-97, routes_core.py:208-210
- §2.5 — insert — version starts at 1 at creation — db.py:103-115
- §2.7 item 5 — revise — explicit null counts as missing; required string fields must be non-empty — web.py:154-164
- §3.2 — insert — ERR_APPLICATION_ALREADY_ACTIVE guards creation only; a reapplication reset is permitted while another application is live — routes_accreditation.py:80-110
- §3.2 — insert — an application_id not naming an application of the same business (nonexistent or another business's) → ERR_APPLICATION_NOT_FOUND — routes_accreditation.py:71-75
- §3.3 — insert — ledger kind binds role: PAYMENT only by BusinessRep, REFUND only by BureauAdmin, cross-role → ERR_UNAUTHORIZED — routes_accreditation.py:306-309
- §3.3 — insert — full payment when business already ACCREDITED or REVOKED leaves status unchanged and does not bump version; the application still advances — routes_accreditation.py:334-345
- §3.3 — insert — response carries the updated invoice with 201; ledger entries are not a separately persisted/readable resource — routes_accreditation.py:372, db.py:12-25
- §3.3 — insert — a refund against an OVERDUE invoice recomputes the balance but leaves it OVERDUE, even at full net-paid — routes_accreditation.py:351-363
- §3.4 — insert — response kind binds role: BUSINESS_RESPONSE only by BusinessRep, CONSUMER_* only by Consumer, mismatch → ERR_UNAUTHORIZED — routes_complaints.py:150-153
- §3.4 — insert — reopen preserves the responses history and rebuttal_count (a complaint at 3 rebuttals admits no more after reopening) — routes_complaints.py:243-251
- §3.6 — insert — Feb 29 founding observes its anniversary on Feb 28 in non-leap years — domain.py:199-210
- §3.6 + §3.7 — insert — latest-published selection: remaining ties (equal published_at and created_at) break in favor of the snapshot written later — domain.py:357-367
- §3.7 — insert — the scan refreshes suspension_count_24m in place; version increments only when the scan changes accreditation_status — domain.py:444-475
- §3.8 — insert — opening a review regenerates the provisional and bumps the business version even when the status does not change (second concurrent review, sticky REFERRED_TO_REGULATOR) — routes_surveillance.py:68-73
- §3.8 — insert — scam-pattern rows identical on count and legal_name keep business creation order — routes_surveillance.py:230-234

**Mismatch-revisions**:
- §2.7 item 3 — revise — on discriminator-gated operations (complaint-response kind, ledger-entry kind, mediation party), body schema and the discriminator-selected role binding are evaluated ahead of the priority-3 ownership check (the global cascade as written predicts ownership first) — routes_complaints.py:140-158, routes_accreditation.py:296-312, routes_escalation.py:103-127
- §3.2 — revise — the reapplication reset answers 201 Created (not 200 as §4's transition rule would predict), carrying the reset application — routes_accreditation.py:102
- §3.5 — revise — PRD said cross-side party answers draw ERR_FORBIDDEN_OWNERSHIP; impl splits: party not matching the caller's role → ERR_UNAUTHORIZED, entity mismatch on the named side → ERR_FORBIDDEN_OWNERSHIP — routes_escalation.py:112-121
- §3.6 — revise — "regenerates whenever any complaint counter / advertising status / scam count changes" was falsified by intake, mediation offer, and decline (counters move, no snapshot); revised to regeneration at exactly the noted points, with an explicit non-firing list — routes_complaints.py:60-86 (no regen on file), routes_escalation.py:53-83,128-145 (no regen on offer/party answers), domain.py:373-476 (sweeps)

**DEAD CODE**: one finding, of the unsatisfiable-condition kind rather than a never-called helper. The suspension-scan branch "SUSPENDED business, latest published score < 75, trailing suspension count >= 2 → REVOKED" (implementation/domain.py:469-475; required by PRD §3.7 "A SUSPENDED business whose latest published score remains below 75 while its trailing suspension count reaches 2 is revoked outright") is evaluated on every daily close but can never fire: a second in-window suspension is appended only in the ACCREDITED branch, which revokes immediately when the count reaches 2 (domain.py:457-465), so a business still SUSPENDED always has count <= 1. The check is faithfully implemented per PRD; its unreachability follows from the state machine itself. PRD sentence left unchanged (the check exists and runs); orchestrator adjudication: PRD and impl are aligned (both carry the eager revocation on second suspension AND the evaluated-but-unreachable SUSPENDED-branch check), so this is a benign semantic property of the state machine, not a PRD/impl divergence — no action taken.

Also sampled and found already-aligned (no change): all 40 routes vs §4, error catalogue vs §5, dues arithmetic incl. the 115333-cent worked example, inclusive window/cooling/deadline boundaries (183d, 30d, 14d, 7d, 10d, 30d-reopen, 15d-void, 365d, 730d, 1095d), half-open mediator overlap vs 30-minute hearing buffer, the §3.2 advertising-gate entity-scan sentence (already pinned by finalization; untouched), FILED zero-duration dispute creation, OCC ordering (6 before 9 before 10), and response codes for all other operations.

## Pipeline Complete — 2026-10-01T17:00:00.000Z

All 9 steps done. Final state: 88/88 tests passing across all 8 parallel stability rounds (per-test-server isolation); PRD.md → PRD_FINALIZED.md (1 pin) → PRD_COMPLETED.md (22 pins/revisions); implementation untouched since the clean sweep.
