# Worklog — task_3471_free_admission_museum_complex_visitor_flow_collection

## Step 1: Create task directory — 2026-10-02T11:00:20.381Z

Pre-allocated task directory `./tasks/task_3471_free_admission_museum_complex_visitor_flow_collection/` verified to exist with `workspace/` inside (per command args; no new index computed, no other task_* directory created).

## Step 2: Generate scaffold — 2026-10-02T12:43:00.000Z

All three artifacts are generated, parse cleanly, and pass the linter. Summary:

**Files written** (in `/home/ubuntu/github/CodingPRD/tasks/task_3471_free_admission_museum_complex_visitor_flow_collection/`):
- `SCAFFOLD.yaml` — 1660 lines, YAML parse OK
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 979 lines, YAML parse OK
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1945 lines, YAML parse OK

**Counts**
- Endpoints in §1.5: **66** (57 business + clock + 9 single-resource GETs added to satisfy FK reverse-reachability)
- §1.8 difficulty instances: **18** (all 9 rules × exactly 2, all differentiation clauses honored — e.g. dual-variant on LoanAgreement premium vs FundAccount availability; rounding-order mode (b) vs circular-resolution mode (c); loan-window half-open adjacency vs buffer-expanded gallery overlap)
- §1.9 corner instances: **53** (43 active with full recipes + 10 `excluded_because` stubs citing §1.8 instances)
- 16 entities, 14 state machines, 15 calculations, 20 ordered validations, 40 error codes (all referenced beyond the catalog), 15 roles, 3 OCC concurrency rules

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (463 calls scanned, 0 violations)

**Domain check**: grep confirms the scaffold is museum-domain throughout (docent ×56, presale ×18, timed-entry ×17, courier ×15, screening ×13, deaccession ×9, indemnity ×5, repatriation ×4) — no foreign domain.

**Key design decisions and findings**
- Difficulty is density-driven per the "much harder than expert" instruction: segregation-of-duties keyed on X-User-ID, cyclic loan negotiation with OCC, a depth-3 deaccession cascade (review → object → loans → reports), committed-vs-settled fund gating, closed-vs-half-open-vs-buffered interval semantics on three different resources, and FIFO head-of-line-blocked waitlist promotion.
- Two dead-code traps caught and fixed during self-review (consistent with my memory notes): the deaccession decide guard originally blocked AGREED loans, which would have made the execute-time loan-cancellation cascade unreachable — amended so only ACTIVE loans block decide/execute while AGREED/negotiating loans ride the cascade; and the admit-time museum-closure check was fully shadowed by the close-day pass-expiry cascade — removed from the admit precondition.
- All formula-derived asserts were executed numerically before pinning (premium 1260000 / 750400 / 480000 / 6720 with the naive 6721 contrast, fund committed 580000000, member-price rounding 1999/2000/2001, docent ceil math).
- Fixture dates are weekday-verified (2026-09-07, 2026-10-05, 2026-10-12 are Mondays; 2026-10-06 is the Tuesday mismatch case).
- Caveat for downstream: 66 endpoints exceeds the expert band (20–32) deliberately per the difficulty instruction; per prior pipeline experience, Step 6 implementation generation should be run with the pre-constrained prompt (one file per message, per-domain modules, no-truncation, self-smoke-test).

Orchestrator verification: re-parsed all three YAMLs from disk — api_prefix `/campus`, 66 endpoints, 9 difficulty rules × 18 active instances, 9 corner sections × 43 active + 10 stubs; counts match the subagent's report.

## Step 3: Copy shared files — 2026-10-02T12:46:17Z

Copied `./INSTRUCTION.md` → `tasks/task_3471_free_admission_museum_complex_visitor_flow_collection/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T13:05:00.000Z

PRD generation complete and verified.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3471_free_admission_museum_complex_visitor_flow_collection/workspace/PRD.md` — **347 lines**, written in 7 sequential chunks (Write + quoted-heredoc appends), ending at §5 with no audit footer. The two withheld design-index files were never opened.

**Structure:** §1 introduction (2 paragraphs), §2 with 9 subsections (RBAC, verbatim §2.2 envelope, pagination, logical clock + quarter-hour grid, resource identity/paths, OCC, money/federal-trust separation, 20-step validation pipeline, cascades), §3 with 8 domain-grouped subsections (visitor grid, membership/ticketing, education, loans, condition reports, committee review, funds, research access), §4 endpoint table (4 columns), §5 error catalogue (2 columns).

**Coverage (greps vs SCAFFOLD.yaml):**
- Endpoints: **66/66** paths present (incl. unprefixed `/_clock/set_current_utc`)
- Error IDs: **40/40** present, all with trigger conditions in §1–§4 (none table-only)
- State values: **38/38** backticked; every transition of all 14 state machines expressed with preconditions + side effects
- Fields: **92/92** required identifiers (entity fields + endpoint inputs/query/path params + `id` + `screening_backlog_minutes`) in backticks

**Hard contract reports:**
- Contract 1 (Field-Name Coverage): PASS — 92 required, 92 present, 0 missing. (Note: a naive whole-file backtick regex mispaired on §2.2's fenced JSON blocks and false-reported 92 missing; re-ran with fenced-code stripping, twice, diff empty.)
- Contract 2 (Rule Coverage): PASS — 20 validations with priority order in §2.8 ("first failure wins"); 3 OCC rules each naming write capability, `expected_loan_version`/`expected_review_version`, error id, HTTP 412; 15 calculations fully expressed incl. pinned premium rounding order with both worked values (6,720 vs wrong 6,721; provisional 2,000,000 vs final 1,260,000) and the SETTLED-vs-COMMITTED worked example; sibling variants (PROVISIONAL/FINAL, FORWARD/REALIZED, both counter/accept directions, both execute kinds) at equal density.
- Contract 3 (§3 Path Purity): PASS — 469 backtick tokens scanned, 0 paths, 0 bare methods, 0 method+path combos.

**Interpretation decisions:**
1. Decimal rate constants rendered as English percentages per the no-pseudocode rule (0.006 → "0.6 percent", 0.20 → "twenty percent"); a literal grep for the decimals flags them, but translation is mandated.
2. CollectionReview has no `created_by` field yet submit must match "the creator's X-User-ID recorded at create" — PRD states the server records the creator's `X-User-ID` internally at creation.
3. `screening_backlog_minutes` named as a computed read-side field on museum reads (from the calculation's trigger note), FORWARD variant server-reported, REALIZED documented-only.
4. `ERR_PROGRAM_NOT_SCHEDULED` attached to reservation create, docent-assignment create, and docent confirm against a `CANCELLED` program, per the error catalog plus the confirm precondition.
5. Expenditure `review_id` null-otherwise rule made explicit in §3.7 (initially only the execute-side half was stated; patched before ship).

Orchestrator spot-check: re-verified from disk — 66/66 endpoint paths in PRD (0 missing), 40/40 error IDs, 38/38 distinct state names backticked, unprefixed `/_clock/set_current_utc` present.

## Step 5a: Generate test helpers — 2026-10-02T13:35:00.000Z

Stage 5a is complete. All deliverables are written, the package graph imports cleanly, and the PRD worked values verify exactly.

## Deliverables (10 files, 3029 lines)

| File | Lines | Contents |
|---|---|---|
| `test_helpers/types.py` | 417 | 15-role `UserRole` enum, 21 status/vocab enums, TypedDicts for all 16 entities (all `common_fields: true`; nullable fields `Optional`) |
| `test_helpers/constants.py` | 101 | All thresholds transcribed from PRD: clock default `2026-09-01T00:00:00Z`, slot grid (30 slots × 15 min from 10:00Z, grace 2), premium tiers (100M/400M at 0.6%/0.35%/0.15%, 12% courier, 0.8% provisional), courier min 100,000,000, indemnity min 500,000,000, member discount 20%, buffer 30 min, pagination 10/1/100, plus the PRD's verbatim worked values |
| `test_helpers/api_errors.py` | 109 | All 40 error ids with PRD §5 statuses; registers plain-string map with `set_error_http_status_map` |
| `test_helpers/api_client.py` | 276 | 66 endpoint methods + `set_clock_raw`; literal paths throughout |
| `test_helpers/assertions.py` | 416 | `assert_<entity>` × 16, `assert_common_fields`, `assert_fund_invariants`, `assert_created_at_ascending`, plus exact-arithmetic (`Fraction`) PRD computations: `expected_final_premium_cents` (pinned round-base-then-surcharge order), `expected_provisional_premium_cents`, `expected_member_price_cents`, `docents_required_for` (ceil) |
| `test_helpers/factories.py` | 304 | Input-only payload factories for all 16 creates + counter/decide/execute payloads; deterministic counter for unique codes/emails/names; review-kind pairing factories omit the null side |
| `test_helpers/test_users.py` | 163 | `make_<role>_headers(user_id)` for all 15 roles; TEST_USERS shared constants incl. second identities for Public/Curator/CommitteeChair/Scholar (SoD needs distinct ids); `NO_HEADERS` for 401 probes; entity-backed fallbacks marked unsafe for ownership calls |
| `test_helpers/fixtures.py` | 857 | Five tiers: clock helpers (`set_clock`, `reset_clock`, `slot_datetime`), entity creates, state progression (`create_agreed_loan`, `create_active_loan`, `create_closed_loan`, `setup_approved_deaccession_review`), hierarchy (`setup_exhibition_on_sale`, `setup_program_with_docents`, `setup_confirmed_reservation`), threshold (`setup_fund_with_committed_pressure`, `reserve_pass`/`purchase_ticket` families), terminal/review lifecycle (`create_approved_acquisition_review`, `execute_review`) |
| `test_helpers/__init__.py` | 257 | Barrel export: framework generics + all PRD-specific names |
| `test_suite/conftest.py` | 129 | Session-scoped `api` fixture + one fixture per role (15 + second identities) |

## Verification results

- **Package-graph check**: the mandated import line exits 0 (`PACKAGE GRAPH OK`); conftest.py also imports standalone.
- **PRD worked values all reproduce**: premium FINAL 1,260,000 / provisional 2,000,000 (declared 250M+courier), pinned rounding 6,720 (declared 1,000,075 — the 6,721 sum-then-round reading is distinguishable), 750,400 / 300,000 / 480,000 tier values, INDEMNITY → 0; member pricing 2500→2000, 2499→1999, 2501→2001; ceil(25/10)=3.
- **Error map**: 40 ids registered; `ERR_STALE_LOAN_VERSION`→412, `ERR_NOT_TRUST_FUND`→422 confirmed in the framework's live map.
- **Style**: zero "scaffold" mentions in generated code; no `test_*.py` files emitted (Stage 5b's scope).

## Trap resolutions

1. **Clock prefix**: `ApiClient.set_clock` posts to literal `/_clock/set_current_utc` (payload key `current_utc`, the field the scaffold's endpoint row declares); every other method carries the literal `/campus` prefix. No prefix-composition logic exists to misroute.
2. **Clock start vs fixture dates**: PRD §2.4 startup default is `2026-09-01T00:00:00Z`. All factory/fixture defaults sit after it (visit `2026-09-20`, Monday service/visit `2026-10-05`, loan window `[2026-10-01, 2027-01-01)`, presale `2026-09-05` / public `2026-09-10`). Fixtures never call `set_clock` implicitly — only via explicit `set_clock`/`reset_clock` or `setup_exhibition_on_sale(advance_clock_to=...)` — so the `clock_default_is_startup_default` corner instance (which must never set the clock) stays constructible.
3. **Constants**: every literal in constants.py traces to PRD prose; no placeholders.
4. **Status codes**: fixtures assert 201 for creates via `_created()` and 2xx for actions via `_ok()`; framework `validate_success(response, expected_status)` stays explicit for Stage 5b (no blanket 200 assumption baked into helpers).
5. **Roles/headers**: 15 roles; `Docent`/`Member` entity-backed builders take the entity id; `confirm_assignment(assignment)` threads `assignment["docent_id"]`; `purchase_ticket(member=...)` threads `member["id"]`; curator/chair ids are explicit parameters on review fixtures so SoD (keyed on `X-User-ID`) is satisfiable.
6. **Money**: integer cents everywhere; premium/member-price expected-value helpers use `Fraction` (binary floats misround `2499*0.8`).
7. **Black-box preconditions**: every fixture builds state purely through declared endpoints and returns response dicts carrying server-minted ids/versions (`decide_review` uses the snapshot's `version` for OCC; `cancel_pass`/`cancel_reservation` derive caller identity from the response's `created_by_user_id`).

## Ambiguities resolved

- **`screening_backlog_minutes`** is PRD-stated as exposed on museum reads but not guaranteed on write responses — declared `Optional` in the Museum TypedDict and asserted leniently (type-checked only when present).
- **Action endpoints with empty input** (`input: []`) send `payload={}` so strict JSON-body handlers don't 400 on a missing body.
- **Review field pairing**: acquisition/deaccession factories omit the must-be-null field entirely (natural client behavior for "carries X with a null Y") rather than sending explicit nulls.

Orchestrator spot-check: re-ran the package import check myself (exits 0); confirmed `set_clock` posts literal `/_clock/set_current_utc` unprefixed; spot-diffed constants.py against PRD prose (slot grid 30×15min from 10:00Z, grace 2, tiers 0.6%/0.35%/0.15% over 100M/400M, courier 12%, provisional 0.8%, buffer 30 min, member 20% — all match). Measured design indices myself for Stage 5b queue sizing: queue A = 18 active difficulty instances (9 rules × 2); queue B = 43 active corner instances + 10 `excluded_because` stubs (9 sections).

## Step 5b: Generate test suite — 2026-10-02T14:10:00.000Z

All checks pass. Final summary:

## Stage 5b complete — test suite generated

**Test files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3471_free_admission_museum_complex_visitor_flow_collection/test_suite/`, against the frozen Stage 5a helpers — nothing in `test_helpers/` or `conftest.py` was touched):

| File | Tests |
|---|---|
| test_01_museum_entry_passes.py | 10 |
| test_02_member_pricing_and_windows.py | 8 |
| test_03_ticket_lifecycle.py | 6 |
| test_04_education_programs.py | 9 |
| test_05_loans.py | 10 |
| test_06_collection_reviews.py | 8 |
| test_07_funds.py | 4 |
| test_08_research_and_auth.py | 6 |
| **Total** | **61** |

**Reconciliation arithmetic: 18 (queue A) + 43 (queue B) − 0 skips = 61 emitted.** All 18 difficulty instances and all 43 active corner instances were translated; the 10 `excluded_because` stubs were not.

**Skips:** none — every instance has verbatim PRD coverage and a uniquely-derivable core outcome.

**Relaxations (not skips; reported per the skill's silence-pattern rules):**
1. `Corner/calculations/indemnity_and_courier_term_gates` — L2 (INDEMNITY, 600M, no courier) violates both ERR_COURIER_REQUIRED and ERR_INDEMNITY_REQUIRES_COURIER, which PRD §2.8 leaves unordered inside item 17 → asserted via `validate_error_is_one_of([...])`. I also evaluated L4 before L3 so L4's `ERR_COURIER_REQUIRED` fires while no AGREED loan exists (the recipe's literal order would leave L4 exposed to an unordered terms-vs-overlap collision with L3's fresh AGREEMENT).
2. `Corner/errors/federal_fund_activity_separation` — asserted on the expenditure surface only (ACQUISITION→422, OPERATIONS→POSTED). The recipe's review-decide leg was dropped: PRD §3.6 enumerates the acquisition-decide gates (fund ACTIVE, committed sufficiency) without fund_type, so §2.7's activity-permission sentence does not uniquely derive a decide-time rejection (applies_to-scope pattern).
3. `Corner/validations/missing_auth_header_returns_401` — the recipe's "no Museum row created" sub-assertion was dropped as unobservable (PRD §4 declares no list-museums endpoint); the 401 `ERR_UNAUTHENTICATED` + error-envelope message are asserted.

**Trap checks:** creates asserted with explicit `validate_success(resp, 201)`; all clock moves go through the unprefixed `/_clock/set_current_utc` client method and every recipe's dates were verified reachable from the 2026-09-01T00:00:00Z startup default; slot-based clocks use `fixtures.slot_datetime` (slot 4 → 11:05Z, slot 5 → 11:20Z, slot 2 → 10:35Z); OCC payloads use exactly `expected_loan_version` / `expected_review_version` with 412 via the registered error map; SoD and entity-backed ownership use distinct second identities (`make_committee_chair_headers("cur-6")`, `make_docent_headers(d2["id"])`, `make_member_headers(m1["id"])`-vs-`m2["id"]`); all money assertions use the exact-arithmetic helpers/constants (`PREMIUM_ROUNDING_PINNED_CENTS=6720`, `PREMIUM_WORKED_FINAL_CENTS=1260000`, `FUND_WORKED_*`, `MEMBER_PRICE_WORKED`, `expected_final_premium_cents`) — 750400/300000/480000 asserted against the Fraction-based helper, never floats. Weekday pins verified against the PRD calendar (2026-09-07 and 2026-10-05 Mondays; 2026-10-06 Tuesday).

**AST tag audit output:**
```
tests found: 61
valid tags: 61 unique
missing (in index, no test): 0
bad/unknown tags: 0
```

**pytest --collect-only:** `61 tests collected in 0.35s` — 0 import/collection errors.

**Verbatim-citation spot check:** 15 distinctive ≥8-word substrings (including em-dash/backtick/worked-value sentences) all grep-hit PRD.md — 15 OK, 0 MISS.

**Helper gap noted (not fixed, per instructions):** there is no `cancel_education_program` fixture helper — tests call `api.cancel_education_program(...)` directly with coordinator headers. Everything else composed cleanly from the frozen fixtures.

Orchestrator verification: re-ran the AST tag audit independently — 61 tests, 61 valid unique tags, 0 missing, 0 bad, 0 extra. Re-ran `pytest --collect-only` independently — 61 collected, 0 errors.

## Step 6: Generate implementation — 2026-10-02T14:55:00.000Z

Implementation complete. Final report:

## Deliverable
`tasks/task_3471_free_admission_museum_complex_visitor_flow_collection/workspace/implementation/` — 26 files, 2953 lines total:

| File | Lines | Role |
|---|---|---|
| start.sh | 10 | Guarded-install launcher (`exec python3 app.py`, `$PORT`, `0.0.0.0`) |
| requirements.txt | 1 | flask only |
| app.py | 90 | App factory, unprefixed `POST /_clock/set_current_utc`, error handlers, blueprint registration |
| constants.py | 74 | Every constant, transcribed from PRD values |
| errors.py | 59 | `ApiError` + all 40 catalog ids with PRD §5 statuses |
| db.py | 108 | In-memory dict store (empty at boot, no seeding), logical clock, entity factory, `touch` |
| util.py | 162 | Strict date/datetime parsing, shape validators, pagination |
| envelope.py | 53 | PRD §2.2 envelope (meta/response_type/data; pagination in meta for lists) |
| middleware.py | 37 | Auth headers, role gate, 404 lookup |
| calc.py | 236 | All 15 calculations (pinned premium rounding, member price, fund SETTLED/COMMITTED, overlaps, reservation resolution, FIFO waitlist waterfall, FORWARD backlog) |
| serializers.py | 215 | Exact per-entity field sets; internal `_`-fields never serialized |
| routes_museums/passes/members/exhibitions/tickets | 95/168/55/121/137 | Visitor flow + ticketing domains |
| routes_programs/assignments/reservations | 136/124/121 | Education domain |
| routes_objects/loans/reports/reviews | 70/239/93/259 | Collections domain (OCC, negotiation, condition reports, committee review, execute cascades) |
| routes_funds/expenditures/research | 72/93/125 | Fiscal + research domains |

## Verification results
- **py_compile**: all 25 `.py` files pass. **Import check**: `python3 -c "import app"` succeeds — 66 business+clock routes registered (67 URL rules incl. Flask's static rule).
- **Smoke test** (dynamic port 44321, server PID 1678690): 401 no-auth → **401**; create museum → **201**; read-back → **200**; missing-field create → **400** (ERR_INVALID_REQUEST); create pass → **201**; cancel → **200**; second cancel → **409 ERR_INVALID_STATE** (state gate); `POST /_clock/set_current_utc` → **200**. Server killed by exact PID, confirmed dead.
- **Error-id live-site audit**: 40/40 catalog ids have at least one live raise site outside `errors.py` on the path the PRD names.
- **Constants audit**: no used-but-undefined constants, no duplicate definition sites.

## Interpretations chosen (PRD admitted multiple readings)
1. **All timestamps read the logical clock** (created_at/updated_at/meta timestamp) — required for deterministic member-lapse behavior; wall clock never consulted.
2. **Waitlist/list ordering** is `(created_at, insertion_seq)` — insertion seq (not the UUID) breaks ties under a frozen clock, since PRD forbids id tie-breaks.
3. **OCC (412) positioned immediately after transition legality** (priority 5), before fund-frozen(6)/SoD(7)/shape(9) — matches the §3.4/§3.6 narrative order ("carries expected_…; a stale version is rejected…") and the state-machine precondition order. Missing/non-integer `expected_*_version` → 400 at the shape stage.
4. **Resource-dependent ownership runs after path existence** (ownership can't be evaluated without the resource); header-only ownership (Member ticket purchase) at true priority 2.
5. **Member caller purchasing without `member_id` → 403** ("may purchase only with a member_id equal to their own X-User-ID").
6. **Admit on any date ≠ visit_date fails ERR_PASS_EXPIRED and flips the pass to EXPIRED**, including future dates (PRD: wrong-date attempts "fail the same slot comparison", whose failure mode includes the flip).
7. **Gallery buffer**: PRD self-contradicts (±30 min symmetric expansion vs. the pinned "gap of exactly thirty minutes is allowed"). Implemented so the pinned boundary holds — conflict iff `(a.start−30) < b.end and (b.start−30) < a.end` (equivalent to a 30-minute setup buffer before each session). A 30-min gap → 201; <30 → 409.
8. **Pagination**: non-integer or out-of-range limit (<1/>100)/offset (<0) → 400 ERR_INVALID_REQUEST (no clamping).
9. **Uniqueness** of museum_code/email/fund_code/accession_number enforced → 400 ERR_INVALID_REQUEST (no dedicated error id exists in the catalog).
10. Exhibition `member_presale_opens_at`/`public_sale_opens_at` and clock `current_utc` **echoed verbatim** as supplied; comparisons use parsed UTC.
11. close-day on an already-closed date does not duplicate the `closed_dates` entry (idempotent append); cascade still runs.
12. Loan `premium_cents` is null until accept; counter fields explicitly null are treated as not provided; merged window must keep end > start.
13. Condition-report filing allowed in any loan state (PRD restricts only decidability); decide on a loan outside AGREED/ACTIVE → 409 ERR_INVALID_STATE (no dedicated id).
14. Loan close reads the **most recently created** ACCEPTED RETURN report when several exist.
15. Deaccession approval moves the object to PENDING_DEACCESSION only from IN_COLLECTION/UNDER_CONSERVATION (other states unstated — left untouched).
16. Acquisition execute without `actual_cost_cents` falls back to `estimated_cost_cents`; the created object gets a server-minted accession number (`ACQ-<hex>`), `is_cultural_property` false; the auto-posted expenditure has `memo: null`, `review_id` set.
17. Fund set-status to the current state → 409 ERR_INVALID_STATE (no self-loop in the machine).
18. Reservation closure check uses the body's `museum_id`; no invented cross-check that `program.museum_id == museum_id`.
19. Cancelling a WAITLISTED reservation does **not** trigger promotion (PRD lists only confirmed-cancel and docent-confirm as triggers).
20. Docent double-booking counts ASSIGNED/CONFIRMED assignments on **other SCHEDULED** programs only (literal "another"); same-program re-assignment allowed.
21. Review creator stored internally (`_creator_user_id`), never serialized (not in the entity spec).
22. Member GET: Member role restricted to self (403 otherwise); required string fields enforce presence+type, empty strings accepted.

## PRD contradictions found
- **Gallery setup buffer** (§3.3 / scaffold calc): the symmetric `[start−30, end+30)` formula makes a 30-minute session gap a conflict, while both PRD and scaffold prose pin "a gap of exactly thirty minutes … is allowed". I honored the pinned boundary (see interpretation 7) — flagged here since tests derived from the raw formula would disagree.
- **Validation ordering**: §2.8's explicit pipeline (duplicate-pass 10 < closure 13 < group-size 16) contradicts the §3.1/§3.3 narrative order (flag/closure listed before duplicate; "hard validation first" for group-size vs day-mismatch). I followed §2.8 for checks it lists and the narratives only for unlisted checks (ERR_TIMED_PASS_NOT_USED_HERE after shape; ERR_PROGRAM_DAY_MISMATCH after ERR_GROUP_TOO_LARGE).
- **ERR_MUSEUM_CLOSED_ON_DATE on admit**: the error catalog lists admit, but validation 13's applies_to omits it and the close-day cascade makes it unreachable; wired as a dead check for safety.

Orchestrator verification: re-compiled all 25 .py files (pass), re-ran `python3 -c "import app"` (IMPORT OK), confirmed start.sh is a guarded-install foreground launcher, confirmed 0 references to test_suite/test_helpers/design-index files anywhere in implementation/.

## Step 7: Test-fix iteration loop — 2026-10-02T14:54:30.000Z

Clean exit achieved. All 8 `results.*.json` files persist in `workspace/implementation/` as required by the output contract.

## Summary

**Iterations run:** 2 (initial sweep → fixes → clean re-sweep)

**Sweep results:**
- Iteration 1: 58/61 in all 8 rounds — 3 deterministic failures, identical across rounds (no flakiness)
- Iteration 2: **61/61 in all 8 rounds — clean exit**

**Tests deleted:** none.

**Failures diagnosed (union across rounds = 3, all deterministic):**

1. `test_ticket_purchase_refund_conserves_quota` (receipts read 2000, expected 3000) and 2. `test_exhibition_close_cascades_refunds_and_receipts` (receipts read −2000, expected 0) — same root cause: `fund_receipts()` in `workspace/implementation/calc.py` computed receipts as Σ(PURCHASED/REDEEMED) − Σ(REFUNDED), making every refund swing receipts by −2×`price_paid_cents`. STEP 1a coverage: verbatim in PRD §3.2 ("debits the revenue fund's receipts by the `price_paid_cents`", stated for both manual refund and close cascade; "credits ... by the `price_paid_cents`" for purchase; §2.7 "refunds and the exhibition-close cascade debit them"). STEP 1b: the literal-minus-REFUNDED reading makes the observed debit per refund 2×price, contradicting the pinned debit amount — so the only reading consistent with all PRD sentences nets a refunded ticket to 0; unique derivability holds. STEP 2: both tests faithful. STEP 3: impl bug.

3. `test_gallery_buffer_expanded_overlap` (expected ERR_GALLERY_SCHEDULE_CONFLICT on an exactly-30-minute session gap; impl returned 201) — the pre-flagged PRD §3.3 self-contradiction. The test asserted the symmetric ±30-min formula's verdict on exactly the scenario the pinned sentence governs ("A gap of exactly thirty minutes between sessions is allowed — the expanded intervals touch but do not overlap"). Per the pre-arbitration, the pinned concrete boundary is the uniquely-derivable rule → STEP 2: test wrong.

**Fixes applied to `test_suite/`:**
- `test_04_education_programs.py::test_gallery_buffer_expanded_overlap` — conflict case changed to a 20-minute gap (start 680; expanded [570,690) ∩ [650,800) ≠ ∅ — uniquely derivable from the formula sentence under both faithful readings); allowed case changed to the exact 30-minute pinned boundary (start 690 → 201 SCHEDULED).

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:**
- `workspace/implementation/calc.py::fund_receipts` — removed the `REFUNDED → −price_paid_cents` term; a refunded ticket's purchase credit and refund debit cancel (net 0), matching PRD §3.2's pinned debit-amount semantics. Verified no currently-passing test relied on the minus-REFUNDED reading (all 8 receipts assertions in the suite are consistent with net-0).

Fix counts are tied 1-to-1 (test-side does not outnumber impl-side), so no unasserted-sibling-paths addendum is owed.

Orchestrator verification: re-read all 8 results files independently — each shows passed=61, failed=0, errors=0, total=61. Mtime check: no impl .py source file is newer than results.1.json (calc.py predates the clean sweep) — the green sweep covers the final code state.

## Step 8: Finalize PRD — 2026-10-02T15:10:00.000Z

Done. PRD_FINALIZED.md is written with exactly two single-line edits, each tracing to a step_7_diff item.

## Summary

**Line counts:** PRD.md 347 lines → PRD_FINALIZED.md 347 lines (0% delta; two in-place line replacements, nothing else touched).

**Changes:**
- **§2.7 (line 104)** — revise — removed "minus the amounts of tickets in `REFUNDED` status" from the receipts formula and appended the net-zero rule (each refund debit equals the ticket's `price_paid_cents` and cancels its purchase credit, so a `REFUNDED` ticket contributes nothing) — `implementation/calc.py:98-111` (`fund_receipts` sums only `PURCHASED`/`REDEEMED`).
- **§3.3 (line 171)** — revise — gallery occupation changed from "thirty minutes before its `start_minute` until thirty minutes after its `end_minute`" to "from thirty minutes before its `start_minute` until its `end_minute` … the buffer extends the session's start only, never its end", resolving the formula-vs-pinned-sentence contradiction toward the pinned sentence — `implementation/calc.py:74-94` (`gallery_conflict`: conflict iff `(a.start−30) < b.end and (b.start−30) < a.end`).

**Per-edit pre-edit search log:**

*Edit 1 — §2.7 receipts formula*
- (a) Subject: `TRUST` fund `receipts_cents` computation and all receipt-crediting/debiting mutations.
- (b) Paths enumerated: `calc.py:98-111` (`fund_receipts` — sole computation); `calc.py:114-131` (`settled_available`/`committed_available` consume it); `serializers.py:191` (fund read exposes it for any fund type); `routes_funds.py:45,53,72` (read paths via serializer); purchase `routes_tickets.py:65-76` (lands `PURCHASED` → +price in sum); manual refund `routes_tickets.py:105-117` (only `PURCHASED`→`REFUNDED`, so ticket leaves the sum → −price vs. prior value); redeem `routes_tickets.py:120-137` (`PURCHASED`→`REDEEMED`, both counted → receipts unchanged); close cascade `routes_exhibitions.py:116-119` (each `PURCHASED`→`REFUNDED` → −price each); exhibition creation `routes_exhibitions.py:47-48` (`ERR_NOT_TRUST_FUND` guarantees FEDERAL funds always read 0). No stored `receipts_cents` field is ever mutated anywhere (grep-confirmed).
- (c) Wording adjustment: kept the existing "purchases credit / refunds and close cascade debit" sentence verbatim (it is the pinned debit-amount semantics the impl fix honors — §2.9 line 133, §3.2 lines 161/163/165 all stay consistent since every `REFUNDED` ticket was necessarily `PURCHASED` first, making each debit exactly one `price_paid_cents`); scoped the clarification to "nets to zero" rather than asserting anything about FEDERAL-fund reads, which §3.7's "trust funds only" phrasing already covers.

*Edit 2 — §3.3 gallery buffer*
- (a) Subject: buffer-expanded gallery-interval conflict rule.
- (b) Paths enumerated: `calc.py:74-94` (`gallery_conflict` — sole conflict function; start-side-only buffer, `exclude_id` never used by callers, `SCHEDULED`-only filter left untouched as out-of-scope); `routes_programs.py:46-90` (sole caller — creation only; no program update endpoint exists); `routes_programs.py:116-136` (program cancel — does not exercise the check); `constants.py:35` (`SETUP_BUFFER_MINUTES = 30`); PRD-internal references §2.8 item 11 (line 120, "buffer-expanded gallery interval" inherits the §3.3 definition — verified consistent under the new meaning).
- (c) Wording adjustment: added the clause "the buffer extends the session's start only, never its end" so the revised interval `[start−30, end)` is unambiguous while keeping the pinned "gap of exactly thirty minutes is allowed" sentence verbatim and still deriving the 20-minute-gap conflict ([570,660) ∩ [650,740) ≠ ∅); "setup buffer" framing retained, which a start-side-only buffer naturally satisfies.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly the two reported single-line revisions (lines 104 and 171) and nothing else.

## Step 9: Complete PRD — 2026-10-02T15:35:00.000Z

All pins verified against the implementation. PRD_COMPLETED.md is complete.

## Summary

**Source vs output:** `PRD_FINALIZED.md` (347 lines, 58,354 chars) → `PRD_COMPLETED.md` (349 lines, 62,351 chars); delta +2 lines, +3,997 chars. The +2 lines are the single new paragraph inserted after §2.8 step 20; every other change is an in-place sentence revision/insert. File: `/home/ubuntu/github/CodingPRD/tasks/task_3471_free_admission_museum_complex_visitor_flow_collection/workspace/PRD_COMPLETED.md`.

**Counts:** 24 ambiguity-pins (22 diff hunks; two hunks each carry two pins), 0 mismatch-revisions, 0 IMPL BUGs. All 61 tests pass in all 8 recorded sweeps (`implementation/results.1-8.json`), and the walk found no site where the implementation violates a clear, self-consistent PRD rule — every divergence was PRD silence or a two-reading tension.

**Changes** (`{section} — {insert|revise} — {classification} — {what} — {impl site}`):

- §2.1 — insert — ambiguity — Member self-read ownership added to the ownership litany — `routes_members.py:53-54`
- §2.3 — insert — ambiguity — offset ≥ 0; non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` — `util.py:139-162`
- §2.3 — insert — ambiguity — list ties on identical `created_at` break by creation sequence; `has_more` = `offset` + page size < `total_count` — `db.py:103-108`, `envelope.py:37`
- §2.6 — insert — ambiguity — staleness check placed immediately after transition legality and before remaining request-shape checks; missing/non-integer expected version → `ERR_INVALID_REQUEST` at the shape stage — `routes_loans.py:110-113,160-161`, `routes_reviews.py:122-125,148-149`
- §2.8 step 9 — revise — ambiguity — unique-field collisions (`museum_code`, member `email`, `accession_number`, `fund_code`) folded into request shape → `ERR_INVALID_REQUEST` — `routes_museums.py:50-52`, `routes_members.py:31-33`, `routes_objects.py:34-36`, `routes_funds.py:33-35`
- §2.8 — insert (paragraph after step 20) — ambiguity — pipeline positions pinned for the five unlisted checks: `ERR_TIMED_PASS_NOT_USED_HERE` (after shape, before duplicate-pass), `ERR_NOT_TRUST_FUND` (after shape), `ERR_PROGRAM_NOT_SCHEDULED` (after body-FK existence at creation; after transition legality at confirmation), `ERR_PROGRAM_DAY_MISMATCH` (after shape; before docent eligibility at assignment, after group-size cap at reservation), condition-report parent-loan liveness (after shape, `ERR_INVALID_STATE`) — `routes_passes.py:34-45`, `routes_exhibitions.py:33-48`, `routes_assignments.py:31-43,117-119`, `routes_reservations.py:33-55`, `routes_reports.py:81-90`
- §3.1 — insert — ambiguity — re-closing an already-closed date succeeds without a duplicate `closed_dates` entry; version still increments — `routes_museums.py:83-94`
- §3.1 — revise — ambiguity — `holder_member_id` validated for existence but not ownership-checked at reservation time — `routes_passes.py:26-29`
- §3.1 — revise — ambiguity — wrong-date admission also flips the pass to `EXPIRED` before failing `ERR_PASS_EXPIRED` — `routes_passes.py:150-153`
- §3.2 — insert — ambiguity — `expires_on` month addition clamps the day to the target month's length — `util.py:47-53`, `routes_members.py:34`
- §3.2 — revise — ambiguity — redemption against a non-`ON_SALE` exhibition → `ERR_INVALID_STATE` — `routes_tickets.py:129-131`
- §3.3 — revise — ambiguity — docent duplicate gate counts only live (`ASSIGNED`/`CONFIRMED`) assignments; `RELEASED` does not block — `routes_assignments.py:54-66`
- §3.3 — revise — ambiguity — confirmation's program-not-scheduled precondition → `ERR_PROGRAM_NOT_SCHEDULED` — `routes_assignments.py:117-119`
- §3.3 — insert — ambiguity — reservation `museum_id` names the visit museum whose `closed_dates` govern; no cross-check against the program's museum — `routes_reservations.py:44-46`
- §3.3 — revise — ambiguity — waitlist residual `created_at` ties under a frozen clock break by creation sequence — `calc.py:209`
- §3.4 — revise — ambiguity — loan `declared_value_cents` at least 0 at proposal; `premium_cents` null until acceptance — `routes_loans.py:33,51`
- §3.4 — revise — ambiguity — wrong-side counter is a transition violation (`ERR_INVALID_STATE`, not an authorization error); counter-provided `declared_value_cents` still ≥ 0 — `routes_loans.py:102-109,122-123`
- §3.4 — revise — ambiguity — wrong-side accept is likewise `ERR_INVALID_STATE` — `routes_loans.py:153-158`
- §3.5 — revise — ambiguity — condition-report filing is not gated on the loan's state — `routes_reports.py:21-50`
- §3.5 — revise — ambiguity — deciding a report on a non-live loan → `ERR_INVALID_STATE` — `routes_reports.py:87-90`
- §3.5 — revise — ambiguity — when several `RETURN` reports stand `ACCEPTED`, the most recently filed governs the object's return state — `routes_loans.py:231-237`
- §3.6 — revise — ambiguity (tension: §2.8 step 6 "acquisition decision" vs §3.6 "rejection needs no further gate"; impl took §2.8's reading) — fund-`ACTIVE` gate applies to acquisition decisions of either outcome; approval additionally enforces activity permission (`ERR_FUND_ACTIVITY_NOT_PERMITTED`, so FEDERAL can never fund an acquisition) then committed sufficiency; rejection skips only the approval-specific gates — `routes_reviews.py:128-131,152-173`
- §3.6 — revise — ambiguity — execute: `actual_cost_cents` optional, defaulting to `estimated_cost_cents`, integer ≥ 1 when present; activity permission re-checked at execution; created object gets a server-minted `accession_number` and `is_cultural_property` false; posted expenditure's `memo` is null — `routes_reviews.py:194-230`
- §3.7 — revise — ambiguity — fund read reports `receipts_cents` on every fund (nonzero only for `TRUST`); set-status requesting the current status → `ERR_INVALID_STATE` — `serializers.py:189-194`, `routes_funds.py:65-66`

**IMPL BUGs:** none.

Notable adjudication detail: the §3.6 fund-frozen-on-rejection question was the only site where two PRD passages genuinely pulled apart (§2.8 step 6 says the fund must be `ACTIVE` "for acquisition decision"; §3.6's approval-scoped sentence plus "rejection needs no further gate" suggested outcome-scoping). Since one normative PRD passage supports the implementation's behavior, this was classified as ambiguity and pinned to the impl reading — the revision explicitly redefines "rejection needs no further gate" as "no approval-specific gate" rather than deleting any rule.

Orchestrator verification: `diff -q PRD_FINALIZED.md PRD_COMPLETED.md` confirms real edits (not a silent no-op); line counts 347→349 match the report; file ends intact at the §5 error catalogue. All 8 `results.*.json` still persist; 0 impl .py files are newer than the clean sweep — Steps 8/9 did not touch implementation/, so the green 8-round sweep still covers the shipped code. No Step 9b needed (no IMPL BUGs reported).

## Pipeline complete — 2026-10-02T15:36:00.000Z

Final state: 61/61 tests passing in all 8 parallel stability-sweep rounds; 0 tests deleted; PRD_COMPLETED.md is the final contract.
