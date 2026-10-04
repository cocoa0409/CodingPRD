# Worklog — task_3487_election_night_vote_count_collection_race_calling

## Step 1: Create Task Directory — 2026-10-02T15:45:00.000Z

Task directory was pre-allocated by the caller: `./tasks/task_3487_election_night_vote_count_collection_race_calling/` with `workspace/` inside. Verified existence; no new index computed, no other task_* directory created. Orchestrator constraints in effect: one tool call per message (endpoint duplicates parallel calls); Steps 5 and 6 run strictly sequentially; PROCESS SAFETY and ISOLATION RULEs copied verbatim into subagent prompts.

## Step 2: Generate Scaffold — 2026-10-02T15:55:00.000Z

All three artifacts are complete, parse cleanly, and pass the full lint. Summary:

## Files delivered

| File | Lines | YAML parse | Key contents |
|---|---|---|---|
| `SCAFFOLD.yaml` | 1416 | OK | §1.0–§1.7 only (no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1176 | OK | `scaffold_difficulty_design` — **18 non-stub instances** (9 rules × 2) |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 2625 | OK | `scaffold_corner_design` — **71 non-stub instances** + 9 `excluded_because` stubs |

**SCAFFOLD.yaml stats**: 15 entities, 50 endpoints, 7 state machines, 6 calculations, 20 validations, 37 errors, 10 roles, 2 OCC concurrency rules.

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (50 endpoints, 15 entities, 18 §1.8 + 71 §1.9 instances, 1207 calls scanned, exit 0.)

## Design (beyond-expert calibration)

- **Archetype**: posture-driven gating (ElectionEvent posture SETUP→…→ARCHIVED gates every child op) + compliance/audit secondary; graph topology via a ContestCounty many-to-many junction; segregation-of-duties role model (call proposer can never publish their own call).
- **Rule coverage**: dual-variant calcs on two domains (outstanding-vote estimate historical-vs-survey; stringer reliability CAREER-vs-RECENT_FORM); combinatorial modes (a) multi-input strict-inequality certainty gate and (b) pinned round-per-delivery-then-sum invoice pricing; cyclic machines on Contest (CALLED→UNCALLED re-call cycle; two independent state dimensions), StringerAssignment (RELEASED→ACTIVE redeploy), CoverageDecision (DECLINED→PROPOSED); depth-3 cascade (recount OVERTURNED → call RETRACTED → contest UNCALLED → deliveries STALE + CALL_CREDIT) and depth-2 rollup cascade (accept → county complete → contest COMPLETE); priority conflicts (state vs business_safety; business_referential vs business_temporal); boundaries (certainty equality blocks; recount margin 0.005000 inclusive vs 0.0051 rejected); half-open stringer windows vs closed-interval aggregate hour budget; accept/void and publish/retract compensating invariants.
- **Audit work done beyond lint**: placeholder closure (0 unbound `${var}`), name uniqueness across both design files (98 total), grounds resolvability (all resolve), stub-ref validity, forbidden-vocabulary scan, and a mechanical posture/lock/tabulation replay over every chain — which caught and fixed 3 real broken chains (contest-lock prerequisites missing in 2 corner + 1 difficulty instances) plus one dead error code (`ERR_FEED_NOT_FOUND`, removed → 37 errors). `Contest.version` bump semantics were made explicit for rollup-mutating review decisions to keep the OCC arithmetic honest.
- Fixture clock discipline: logical clock default `2026-09-01T00:00:00Z` declared on `/_clock/set_current_utc`; all fixture dates (setup 2026-10-15, election day 2026-11-03, historical 2024-11-05 with explicit backward clock-set) are consistent with it.

One note for downstream: 50 endpoints exceeds the ~40 comfort threshold noted in pipeline memory — the impl-gen step should use the per-domain module split + one-file-per-message mitigation when it runs.

Orchestrator verification: files confirmed on disk (1416/1176/2625 lines), all three YAML-parse cleanly, SCAFFOLD.yaml has no design keys, endpoint count confirmed 50.

## Step 3: Copy Shared Files — 2026-10-02T17:00:30.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T17:10:00.000Z

Done. The PRD is generated, audited, and complete.

**Output:** `workspace/PRD.md` — 340 lines, ends cleanly at §5 with no audit footer.

**Section list:**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications: 2.1 Roles & RBAC (10 roles, entity-backed vs opaque identity prose), 2.2 Response Structure (byte-identical verbatim via `cat` of the canonical source file), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), 2.4 Logical Clock (startup 2026-09-01T00:00:00Z) & Common Resource Properties (incl. explicit `updated_at`/`version` absence on the 5 `common_fields: false` entities), 2.5 Posture machine (6 transitions + system-only reopen), 2.6 Nested path resolution (all 10 404s), 2.7 OCC (2 rules, `expected_contest_version`, `ERR_STALE_VERSION` 412), 2.8 Precision (6dp half-up; integer cents; round-then-sum), 2.9 Validation priority order (all 20 checks walked in order, incl. the priority-6 sub-order)
- §3 Business Logic (8 subsections): 3.1 event build-out, 3.2 coverage budget, 3.3 stringer roster/reliability/deployment, 3.4 vote intake + QC, 3.5 tabulation board/outstanding estimates, 3.6 decision desk/certainty standard, 3.7 recounts + reopen cascade, 3.8 delivery/licensing/invoicing
- §4 Endpoint table (4 columns, 50 rows), §5 Error catalogue (2 columns, 37 rows)

**Coverage audits (mechanical, YAML-parsed against the file):**
- Contract 1 — Field names: **89 required / 89 present / 0 missing** (entity fields + endpoint inputs + query params + path param `id` + `candidate_votes` entry keys; audited with code fences stripped after detecting fence-induced regex pairing inversion)
- Contract 3 — §3 path purity: **477 backtick tokens scanned, 0 violations** (no `/` tokens, no bare HTTP methods, no method+path)
- Errors: **37/37** present in §2/§3 prose and **37/37** in the §5 table
- Endpoints: **50/50** rows in §4
- State values: **32/32** present; enum/action values: **46/46**; roles: **10/10**; numeric constants (0.40, 0.25, 0.005, 999/4999, 1.0/0.6/0.35, 25/10/2, 365, 2026-09-01): all present
- Contract 2 (manual walk): all 7 state machines' transitions with preconditions+side effects, both OCC rules, all 6 calculations (incl. QC strict-threshold 0.400000 note, reliability CAREER/RECENT_FORM windows and the 75-vs-100 worked example, certainty single/multi-seat/BALLOT_MEASURE branches, invoice round-then-sum with the 1050-vs-1049 example), the 3-hop OVERTURNED cascade, and validation applies_to scopes are expressed in prose

**Design-file constraint:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced — only `SCAFFOLD.yaml`, the generator skill, and its verbatim §2.2 source file were read.

Orchestrator verification: PRD.md confirmed on disk at 340 lines, ends cleanly on the error-catalogue table, 80 `ERR_` token occurrences.

## Step 5 (split decision note) — 2026-10-02T17:15:00.000Z

Orchestrator measured both design indices directly from YAML (not from subagent report): 18 non-stub difficulty instances across 9 rules; 71 non-stub corner instances across 9 sections (12 sections listed, 3 all-stub). Total 89 non-stub — under the >100 full-fan-out threshold but large enough that Step 5 is split into 5a (helpers, frozen) then 5b (tests), sequential, per pipeline memory.

## Step 5a: Generate Test Helpers — 2026-10-02T17:35:00.000Z

Stage 1 is complete and verified. Final state:

| File | Lines | Contents |
|---|---|---|
| `test_helpers/types.py` | 414 | 25 enums (10 roles, postures, both Contest dimensions, all 7 state machines, tiers, content types); 15 entity TypedDicts — common_fields entities carry `id/created_at/updated_at/version`, the 5 append-only ones (ContestCounty, Candidate, FeedSource, ResultDelivery, MediaInvoice) omit `updated_at`/`version`; tabulation-board read shapes |
| `test_helpers/api_errors.py` | 92 | All 37 `ApiErrorId` values with PRD §5 HTTP statuses; registered via `set_error_http_status_map()` at import |
| `test_helpers/constants.py` | 79 | Clock literals, QC thresholds, recount threshold, reliability scoring params, fee/multiplier tables, pagination bounds |
| `test_helpers/api_client.py` | 236 | `ApiClient(GenericApiClient)` with all 50 PRD §4 endpoints (verified programmatically: 50/50 paths present) + `api_client` singleton |
| `test_helpers/assertions.py` | 317 | `assert_*` per entity (append-only asserts verify `updated_at`/`version` absence per PRD §2.4), `assert_contest_rollup_invariants`, `assert_stringer_score_bounds`, `assert_tabulation_board` (checks per-county `outstanding_est == max(historical_est, survey_est)`), `round_half_up_6dp`, `round_half_up_cents`, `expected_delivery_fee_cents` |
| `test_helpers/factories.py` | 297 | One payload factory per creatable resource; optional server-defaulted fields (`stringer_selection_mode`, `seats`, `is_incumbent`, `priority_tier`, survey/hist baselines, `stringer_id`, rationale/note) included only when explicitly passed; named county/customer presets matching the design recipes (Alameda, Contra Costa, Solano, Marin, Washoe NV, Sierra, Autauga, Big County, Exactshire; WireLite BASIC, Metro News PREMIUM) |
| `test_helpers/test_users.py` | 94 | `TEST_USERS` (11 keys incl. two analysts) + `make_<role>_headers(user_id)` for all 10 roles — mandatory builders for entity-backed Stringer/MediaCustomer, and `make_chief_headers("analyst-nina")` supports the segregation-of-duties probe |
| `test_helpers/fixtures.py` | 762 | Clock helpers, OCC-chained report/call flows, posture ladder, and composite universes (below) |
| `test_helpers/__init__.py` | 228 | Barrel: framework generics + all PRD-specific names (210 exported names resolve) |
| `test_suite/conftest.py` | 78 | Session `api` fixture + 11 role-header fixtures with entity-backed fallback warnings |

## Import check
`compileall` clean on both trees; `import test_helpers` and `import test_suite.conftest` succeed; `isinstance(api_client, ApiClient)` is True; 37 errors registered; `expected_delivery_fee_cents("VOTE_UPDATE","BASIC")==350` and `("CALL","PREMIUM")==4999` (matches PRD §3.8's pinned 3×350=1050 example); `round_half_up_6dp(1/3999)==0.00025` (matches the margin-precision corner).

## Public helper API for Stage 2
- Clock: `set_clock(iso)`, `reset_clock_to_setup()`, `move_clock_to_election_day(event_date=ELECTION_DAY)`
- Creators: `create_event/create_county/create_contest/patch_contest/link_county/create_candidate/create_feed_source/create_stringer/create_assignment(event_id, county_id, stringer_id=None, window_start, window_end)/check_in_assignment(asg_id, stringer_id)/assignment_action(asg_id, action)/create_customer/create_wirelite_basic/create_metro_news_premium`
- Reads: `get_event/get_contest/get_contest_version/get_stringer/get_tabulation/list_customer_deliveries/list_contest_deliveries`
- Posture: `advance_posture(event_id, target)`, `advance_to_candidates_locked/live/tabulation/certification/archived` (LIVE sets the election-day clock first)
- Reports: `submit_feed_report(contest_id, county_id, precincts, votes)` / `submit_stringer_report(..., stringer_id, ...)` (both re-read the OCC version); `accept_report/reject_report/void_report/resubmit_report(report_id, precincts, votes, headers)`; `submit_report_sequence(contest_id, specs)`
- Calls/recounts/coverage/invoices: `propose_call(contest_id, winner_id, analyst_id)`, `publish_call/retract_call(call_id, chief_id)`, `file_recount/activate_recount/dismiss_recount/resolve_recount(case_id, outcome, note)`, `propose_coverage/review_coverage/revise_coverage`, `generate_invoice(customer_id, period="2026-11", headers=None)`
- Composites: `setup_standard_universe(advance_to="SETUP"|"CANDIDATES_LOCKED"|"LIVE", link_alameda, link_contra_costa, with_contra_costa, extra_counties, extra_candidates, seats, with_feed, customers=("basic","premium"))`; `setup_universe_with_reports(report_specs, advance_to="TABULATION", ...)`; `setup_complete_contest(alameda_votes, contra_costa_votes, link_contra_costa=True)`; `setup_margin_threshold_contest()` (margin exactly 0.005); `setup_proposed_call` / `setup_published_call`; `setup_active_recount_after_certification()` (stops at ACTIVE recount, posture auto-reopened — RESOLVE left to the test); `create_stringer_with_no_show_history()` (2024-11-05 event reached only via explicit backward clock set to 2024-11-06); `setup_active_assignment(county_key)` (stringer checked in, report-ready)
- Role headers: `TEST_USERS["<role>_headers"]` + `make_<role>_headers(user_id)` for all 10 roles

## PRD-vs-scaffold constant adjudication
No discrepancies found — every constant was diffed against PRD prose and they agree: QC 0.40/0.25 strict (§3.4), recount margin 0.005 inclusive (§3.7), reliability 100 start / −25 / −10 / +2 / clamp [0,100] / 365-day recent window (§3.3), fees 999/4999 with multipliers 1.0/0.6/0.35 and round-then-sum pinning (§3.8), clock startup 2026-09-01T00:00:00Z (§2.4), pagination 10/1/100 (§2.3). No dead constants carried.

One design fix applied during authoring: `setup_active_recount_after_certification` originally built on default contest totals (margin 0.171), which would have made the recount filing fail; it now builds on `setup_margin_threshold_contest` (margin exactly 0.005), matching the cascade recipe.

Orchestrator verification: 10 helper files + conftest.py confirmed on disk (2597 lines total); `import test_helpers` succeeds with 219 exported names.

## Step 5b: Generate Test Suite — 2026-10-02T18:05:00.000Z

Stage 2 is complete. Summary:

## Deliverables — 13 test files, 89 tests, zero skips

**Difficulty queue (18 tests, one per instance):**
- `test_difficulty_dual_variant_and_formula.py` — 4 (outstanding-estimate variants diverge, reliability CAREER/RECENT_FORM diverge, multi-input certainty gate, per-line invoice rounding 1050≠1049)
- `test_difficulty_state_and_cascade.py` — 4 (call-dimension cycle holds tabulation COMPLETE, assignment RELEASE→REDEPLOY loop, recount-overturn 3-hop cascade, accept-driven county→contest completion)
- `test_difficulty_boundaries_and_dependencies.py` — 6 (certainty equality fails, recount margin 0.005 fileable / 0.0051 rejected, CERTIFICATION gated on every contest, ACTIVE recount blocks publish, state-beats-certainty pair, cross-event-beats-overlap pair)
- `test_difficulty_overlap_and_invariants.py` — 4 (half-open overlap + touching adjacency, closed-interval budget 450 rejected / 400 approved, accept→void restores totals exactly, publish→retract nets invoice to 999)

**Corner queue (71 tests):**
- `test_corner_entities_core.py` — 10 · `test_corner_entities_intake_and_uniqueness.py` — 6
- `test_corner_state_machines_posture_reports.py` — 9 · `test_corner_state_machines_calls_coverage.py` — 10
- `test_corner_calculations.py` — 7 · `test_corner_validations.py` — 11
- `test_corner_endpoints_errors.py` — 5 (3 endpoints + 2 errors) · `test_corner_rbac.py` — 5 · `test_corner_cross_cutting.py` — 8 (7 cross-cutting + 1 consistency)

## Audits (both real, both clean)
- **AST tag audit** (parsed both YAMLs, AST-walked every test): 89 non-stub instances (18 difficulty + 71 corner; 9 `excluded_because` stubs correctly untranslated), 89 test functions, **89 matched tags, 0 orphan tags, 0 duplicate tags, 0 untagged, 0 missing**.
- **PRD verbatim citation pass**: 153 quoted spans ≥8 words extracted from docstrings, all literally present in `workspace/PRD.md` after whitespace normalization (0 paraphrases).
- **`pytest --collect-only`**: **89 collected, 0 import/collection errors** (PYTHONPATH=task dir, no server bound).

## Skips
None. Every non-stub instance passed the PRD-first two-condition filter.

## In-test adaptations (frozen layer untouched)
1. **Version pins relaxed to relative form**: PRD says version "increments by one on every mutation" but never states the initial value, so version assertions are `v0 + k` against the observed creation version rather than pinning `== 1` (unique-derivability).
2. **`candidate_totals` entry shape never asserted**: PRD names the field but not its entry keys, and no frozen helper commits to one; per-candidate claims are pinned arithmetically via PRD-stated fields (`total_votes` + `margin_pct` uniquely determine the top-two split).
3. **Pagination page membership asserted as set-union** across pages (fixtures create rows at the same logical instant; `created_at` ties make page order non-derivable).
4. **`created_at` clock proof** uses a `2026-10-15T00:00:00` prefix (PRD pins logical-clock stamping and 3-fractional-digit ISO format but not the exact zero-padding rendering).
5. **No point-read endpoint exists** for RaceCall/StringerAssignment/RecountCase, so tiny module-local helpers (`_list_call`, `_get_assignment`, `_list_recount_case`) compose the frozen client's list endpoints — noted as a Stage-1 gap, worked around per instructions.
6. **Error-path probes** call `api.*` directly with factory-built payloads (the frozen `submit_*`/`create_*` fixture wrappers are success-path `_ok` by design); all success creates pass `expected_status=201` explicitly.

Orchestrator verification: 13 test_*.py files confirmed on disk; independent `pytest --collect-only` reports **89 tests collected, 0 errors**.

## Step 6: Generate Implementation — 2026-10-02T18:45:00.000Z

All verification complete. Final summary:

### File tree (line counts) — `workspace/implementation/`

| file | lines | role |
|---|---|---|
| start.sh | 10 | guarded install (`if ! python3 -c "import flask"`), `exec python3 app.py`, reads `$PORT` (default 10000), binds 0.0.0.0, foreground |
| requirements.txt | 1 | flask>=3.0 |
| app.py | 57 | Flask bootstrap, blueprint registration, ApiError/404/405/Exception handlers |
| store.py | 32 | in-memory dicts (15 tables) + insertion-seq counter; **no seeding** |
| clock.py | 23 | logical clock, starts exactly 2026-09-01T00:00:00Z |
| errors.py | 56 | all 37 catalog error ids + HTTP statuses |
| envelope.py | 81 | `{meta, response_type, data}` envelope, pagination meta (limit/offset/total_count/has_more), created_at+seq sort |
| auth.py | 51 | X-User-ID/X-User-Role extraction (401/403), JSON body helper |
| util.py | 97 | ISO datetime/date parsing, 3-fractional-digit timestamps, Decimal 6dp half-up, money rounding |
| loaders.py | 98 | per-segment 404 resolvers, posture gate, versioned record factory, touch() |
| serializers.py | 221 | one serializer per entity; versioned vs id+created_at-only split per PRD §2.4 |
| services_rollup.py | 159 | tabulation_rollup, outstanding_vote_estimate, county computed fields |
| services_rules.py | 184 | qc_deviation_check (0.40/0.25 strict, Decimal), call_certainty_evaluation (single/multi-seat/ballot), stringer_reliability_score (CAREER/RECENT_FORM), overlap + auto-selector |
| services_delivery.py | 92 | fee pinning (round-half-up per delivery), VOTE_UPDATE/CALL fan-out, CALL_CREDIT compensation, invoice aggregation |
| routes_events.py | 167 | clock endpoint, event create/read, posture ladder + all five transition preconditions |
| routes_counties.py | 79 | county CRUD, uniqueness |
| routes_contests.py | 197 | contests, PATCH, county-links, candidates |
| routes_feeds.py | 61 | feed sources |
| routes_stringers.py | 197 | roster, assignments, check-in, status-actions |
| routes_reports.py | 345 | vote-report intake (full §2.9 guard order), review decisions, resubmit, tabulation board |
| routes_calls.py | 163 | proposal, PUBLISH (posture→recount-block→already-called→state→SoD→certainty), RETRACT |
| routes_recounts.py | 123 | filing (margin ≤ 0.005 inclusive), ACTIVATE (drives CERTIFICATION→TABULATION reopen), DISMISS, RESOLVE + OVERTURNED 3-hop cascade |
| routes_coverage.py | 168 | coverage decisions, closed-interval budget check on APPROVE/FUND, revise loop |
| routes_media.py | 136 | customers, deliveries feed + license gate, invoices (duplicate guard) |

### Verification output
- `python3 -m compileall .` → OK; `import app` in a fresh process → OK, exactly **50 routes** registered (matches the 50-endpoint table).
- Check-wiring grep: all **37/37 ERR_ ids** have ≥1 raise site; all **21 guard/service functions** have ≥1 call site (none defined-but-dead).
- Smoke test 1 (dynamic port 33187/42309/…, own PID killed each run): **53/53 PASS** — full vertical slice (event → counties → contest → links → candidates → feed → posture ladder with clock gate → stringer deploy/check-in → report → OCC 412 → accept → board → propose → SoD 403 → publish → CALLED → deliveries (599/599/2999 cents) → invoice (3 rows, 4197 cents) → duplicate-invoice 409 → recount file/activate/resolve-OVERTURNED → cascade to UNCALLED + CALL→STALE + CALL_CREDIT(−2999) → CERTIFICATION → second recount ACTIVATE reopens to TABULATION + contest COMPLETE→REPORTING → VOID compensation restores pre-acceptance totals).
- Smoke test 2: **48/48 PASS** — reliability aging (no-show → CAREER 75; RECENT_FORM ages out to 100 against a 2026 event), auto-select ranking + created_at tie-break, touching-window allowed / overlap 409 / empty-pool 422, cross-event 422, PRIMARY lock gate + closed-interval budget (boundary-day intersection 422, disjoint OK), decline→revise loop, QC thresholds (deviation 1.0 FLAGGED, exactly 0.400000 RECEIVED, swing 0.5 FLAGGED, null-hist swing null), reject→resubmit cycle, multi-seat certainty (rank ≤ seats), strict-equality failure (100 > 95+5 is false), ballot-measure single-seat rule with seats=2, active-recount publish block 409, already-published 409, margin-exceeded 422, pagination meta + limit=0 400, PATCH version bump.
- All smoke server PIDs (started via `$!` equivalent — subprocess handle) were terminated; no stray processes; no broad kill patterns used.

### Interpretation ledger (PRD admits multiple readings; choices made)
1. **§2.4 initial `version`** → starts at **1** on creation; `updated_at == created_at` at creation. PRD never pins the initial value.
2. **§2.4 `api_request_timestamp`** → stamped from the **logical clock** (PRD: "no part of this system reads wall-clock time"), formatted with 3 fractional digits.
3. **§2.4 created_at ties** → an internal monotonic `_seq` (never serialized) breaks created_at ties wherever the spec orders by created_at (latest-accepted selection, candidate ranking, selector, list sort) — spec says "never id".
4. **§2.5 posture gates** → applied **only** where PRD/scaffold name them; REJECT, VOID, call RETRACT, recount ACTIVATE/DISMISS/RESOLVE, coverage review/revise, customer/stringer creation carry **no** posture gate (scaffold lists `preconditions: []`). Not inventing gates.
5. **§2.5 posture-transitions** → missing `target_posture` → 400; value outside the posture enum → 400; valid enum but not the declared next (incl. CERTIFICATION→TABULATION, which is system-only) → 409 ERR_INVALID_STATE.
6. **§2.6 payload-id references** (not path segments): nonexistent `county_id` on county-links/assignments → 404 ERR_COUNTY_NOT_FOUND; nonexistent `contest_id` on coverage → 404 ERR_CONTEST_NOT_FOUND; nonexistent `stringer_id` on assignment → 404. **Exception:** vote-report `county_id` nonexistent → 422 ERR_COUNTY_NOT_IN_CONTEST (PRD §3.4 names that error for the linkage check, and a nonexistent county is not linked).
7. **§2.9 priority-3 vs 4** → MediaCustomer ownership (403) evaluated **before** customer existence (404), per the numbered order; for check-in/resubmit the assignment/report must load first (can't compare ownership of nothing), so 404 precedes ownership there.
8. **RBAC matrix channel scoping** → Stringer may only file/resubmit STRINGER reports, FeedOperator only FEED reports; cross-channel → 403 ERR_UNAUTHORIZED_ROLE (matrix annotates the shared op per source).
9. **§3.1 county-link state match** ("every linked county shares the contest's state_code") → **enforced** as 400 ERR_INVALID_REQUEST; the catalog pins no specific error for it. (Flagged: prose rule without a catalog error_id.)
10. **§3.1** `county_fips` 5-digit format and `state_code` 2-letter format → **not** pattern-enforced (only non-blank), no error id exists; `historical_dem_share` range [0,1] **is** enforced (400) since PRD states "a fraction between 0 and 1"; `survey_turnout_estimate` any integer.
11. **§3.6 publish sub-order** within priority 6 → recount-active checked **before** already-called (both precede generic ERR_INVALID_STATE), matching the scaffold's listed order.
12. **§3.6 certainty "have any votes"** → candidate total > 0; multi-seat `V_next` = total of the candidate at rank seats+1 in the full ranking.
13. **§3.4 swing with multiple DEM candidates** → their votes are summed for `reported_dem_share` (PRD says "the contest's DEM candidate", singular).
14. **§2.7 version advancers** → exactly the listed six writes bump Contest.version. Recount-reopen COMPLETE→REPORTING does **not** bump contest version (not listed); the automatic CERTIFICATION→TABULATION posture reopen **does** bump event version ("every successful transition increments the event's version"). Retracting a PROPOSED call does not bump.
15. **§3.5 tabulation_status movement** → REPORTING↔COMPLETE transitions fire only on the event-driven recomputes (ACCEPT/VOID), never on read; a recount-reopened REPORTING contest stays REPORTING until the next ACCEPT re-completes it (otherwise read-recompute instantly undoes the reopen). Read-time recompute refreshes numeric rollup fields without bumping version.
16. **§3.3 reliability accept-then-void** → such a report counts in **both** accepted_report_count ("reaching ACCEPTED") and voided_report_count; score net −8. Scores derived on read/selection from a per-event incident log; GET evaluates RECENT_FORM against max assignment event_date, else 2026-09-01.
17. **§3.2 FUND budget re-check** → the decision under review is excluded from the "already APPROVED/FUNDED" sum (its hours enter once via "plus this decision's own hours").
18. **§3.7 filing/dismissal `note`** → accepted but **dropped** (RecountCase has only `resolution_note`, and PRD says dismissal leaves it null).
19. **§3.8 license gate** → keyed on the **path customer's** tier regardless of caller (admin querying a BASIC customer's feed with content_type=CALL also gets 403).
20. **§3.8 retract compensation** → one CALL_CREDIT per flipped still-SENT CALL delivery (fee = exact negation), status SENT.
21. **Tabulation board sub-shapes** (PRD names fields, not entry shapes) → `candidate_totals`: [{candidate_id, candidate_name, party, votes, rank}] ranked; `outstanding_detail`: [{county_id, precincts_reported, votes_reported, historical_estimate, survey_estimate, outstanding_estimate}].
22. **Filters with out-of-enum values** (status/content_type/etc.) → 400 ERR_INVALID_REQUEST; pagination limit outside [1,100] or non-integer → 400.
23. **Empty PATCH /contests/{id}** (neither field) → allowed, still bumps version (an edit was requested; PRD doesn't define rejection).

Deliverable is self-contained, boots clean per-test under `--isolation per-test-server`, and stores nothing across restarts.

Orchestrator verification: 24 files / 2803 lines on disk; independent `compileall` OK; `import app` registers exactly 50 routes; no seeding (only a docstring mention).

## Step 7: Test-Fix Iteration Loop — 2026-10-02T19:10:00.000Z

All 8 rounds pass 89/89, and no source file under `implementation/`, `test_helpers/`, or `test_suite/` is newer than the results files — the sweep was the last write.

## Summary

**Iterations run:** 2 sweeps (initial: 86/89 × 8 rounds, same 3 deterministic failures every round; final: 89/89 × 8 rounds, clean).

**Tests deleted:** none.

**Fixes applied to test_helpers/:**
- `test_helpers/assertions.py` — `assert_tabulation_board`: removed per-entry `historical_est`/`survey_est`/`outstanding_est` key assertions. PRD §3.5 pins only "the per-county `outstanding_detail`" and the max-of-two-variants semantics, never the entry JSON keys — COMPUTED-FIELD SILENCE, non-unique derivability (scaffold calc identifiers vs impl's `historical_estimate` naming are both faithful). Kept the pinned top-level shape and `county_id` validation.
- `test_helpers/types.py` — `OutstandingDetail` TypedDict trimmed to `county_id` (typing-only mirror of the helper change).

**Fixes applied to test_suite/:**
- `test_difficulty_dual_variant_and_formula.py::test_outstanding_estimate_historical_vs_survey_diverge` — replaced unpinned per-entry value assertions with a discriminating contest-level one: added Solano (`survey_turnout_estimate=9000`, unreported) so the pinned contest `outstanding_estimate == 18000` witnesses the per-county max() composition in both directions (historical-only would give 12000, survey-only 14000).
- `test_corner_validations.py::test_feed_report_without_state_coverage_rejected` — the fixture built a PRD-illegal precondition: linking NV Washoe into the CA contest violates §3.1's verbatim "every linked county shares the contest's `state_code`" (impl's 400 was correct, not a bug). Rebuilt legally: NV contest in the same event with Washoe linked and two candidates, advanced to LIVE; the FEED report then reaches collection authority and gets `ERR_FEED_COVERAGE_MISSING` since the event's only feed covers CA. §3.4's pinned guard order (membership before collection authority) makes this the only reachable shape for the rule.

**Fixes applied to implementation/:** none — the implementation was PRD-faithful on all three failures.

**Sibling unasserted paths noticed (for Step 8/9):**
- `outstanding_detail` entry key names are now entirely unasserted (PRD-silent); the survey-null→historical fallback is exercised only via Contra Costa's contribution to the contest total, not per-entry.
- `ERR_FEED_COVERAGE_MISSING` is asserted only in the "feed exists but covers another state" shape; the "no feed source at all" shape (`with_feed=False`) is unasserted.
- `candidate_totals` entry shape remains unasserted (known generation-time adaptation).

**Contract confirmation:** `results.1..8.json` on disk are from the final all-pass sweep (89/89 × 8), and nothing under `implementation/`, `test_helpers/`, or `test_suite/` was modified after that sweep started (verified via `find -newer` on source files, excluding `__pycache__`).

Orchestrator verification: all 8 results.*.json independently parsed — 89/89 passed, 0 failed in every round; `find -newer` against the oldest results file over all three source trees (excluding __pycache__) returns empty. Step 8 is NOT skipped: Step 7 took 2 iterations and made test_suite/ + test_helpers/ fixes (0 implementation/ fixes, 0 deletions).

## Step 8: Finalize PRD — 2026-10-02T19:20:00.000Z

Done. The final diff is a single inline revision in §3.5.

**Line counts:** PRD.md = 340 lines, PRD_FINALIZED.md = 340 lines (0% line-count delta — the change extends one existing line inline; `diff -q` confirms the files differ only at line 201).

### Changes (1 edit covering 2 subjects)

- **§3.5 — revise** — Extended the board-read sentence to pin the entry JSON shapes PRD left silent: each `candidate_totals` entry carries `candidate_id`, `candidate_name`, `party`, `votes`, `rank` (one-based); each `outstanding_detail` entry carries `county_id`, `precincts_reported`, `votes_reported`, `historical_estimate`, `survey_estimate`, `outstanding_estimate`, with the detail list sorted by `county_id` — `implementation/routes_reports.py:321-344`, `implementation/services_rollup.py:107-115`.

### Per-edit pre-edit search log (NO-NEW-MISMATCH RULE)

- **(a) Subject:** `candidate_totals` entry JSON shape. **(b) Paths enumerated:** `services_rollup.py:80` (internal tuple form, never serialized), `services_rollup.py:36-41` (`candidate_ranking` — ranked list spans all contest candidates), `routes_reports.py:321-329` (sole public serialization, in `GET /contests/{id}/tabulation`), `services_rules.py:62-63` (certainty evaluation consumes internal tuples only), `serializers.py:82-83` (canonical candidate keys `candidate_name`/`party` match), `routes_contests.py:63` + `routes_counties.py` (no `candidate_totals` surface). **(c) Wording adjustment:** described entry fields only — no claim about which candidates are included or list ordering (already pinned by existing "ranked `candidate_totals`" prose), avoiding a new universal.
- **(a) Subject:** `outstanding_detail` entry JSON shape and ordering. **(b) Paths enumerated:** `services_rollup.py:88-116` (`compute_outstanding` — sole builder; keys as pinned; `detail.sort(key=lambda d: d["county_id"])`; zero-fallbacks at lines 95-96), `services_rollup.py:83`, `routes_reports.py:344` (sole public surface). Grep over the full `implementation/` tree confirmed no other endpoint returns `outstanding_detail`. **(c) Wording adjustment:** deferred variant semantics to the existing formula prose ("exactly as computed above") rather than restating it, so the survey-null→historical fallback (impl lines 101-104) stays pinned in exactly one place.

### Zero-edit verdicts for remaining step_7_diff items

- **`test_difficulty_dual_variant_and_formula.py` fix** — the discriminating contest-level assertion (`outstanding_estimate == 18000` witnessing per-county `max()` composition) was already pinned verbatim in §3.5 ("The county's outstanding figure is the larger of the two variants, and the contest's `outstanding_estimate` is the sum of those per-county figures"); only the per-entry key names were silent, covered by the edit above. No additional edit.
- **`test_corner_validations.py` fixture rebuild** — pure fixture bug; PRD was already right: §3.1 pins "every linked county shares the contest's `state_code`" and §2.9/§3.4 pin membership (priority 11) before collection authority (priority 12). Zero edits.
- **`ERR_FEED_COVERAGE_MISSING` no-feed shape (sibling note)** — test-coverage gap, not PRD silence: §3.4's "without coverage it is rejected" covers both shapes, and impl's `feed_covers(...) is None` check (`routes_reports.py:114`) rejects identically whether no feed exists or feeds exist without the state. Zero edits.
- **Survey-null fallback exercised only at contest level (sibling note)** — test-coverage note; the fallback is already pinned in §3.5 prose. Zero edits.

Output: `workspace/PRD_FINALIZED.md`

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` confirms exactly one changed line (201), the §3.5 board-read sentence extension; both files 340 lines.

## Step 9: Complete PRD — 2026-10-02T19:40:00.000Z

Done. PRD_COMPLETED.md is written at `workspace/PRD_COMPLETED.md`.

**Stats:** PRD_FINALIZED.md 340 lines / 58,556 chars → PRD_COMPLETED.md 347 lines / 67,060 chars (char-delta +8,504). No new sections; all pins are in-paragraph inserts.

**Counts:** 30 ambiguity-pins, 0 mismatch-revisions, 0 IMPL BUGs.

**Changes (all inserts, all ambiguity):**
- §2.1 — ownership-vs-existence ordering: field-comparison ownership (check-in, resubmit) resolves the resource first (404 precedes 403); path-id ownership (media routes) precedes existence — `routes_stringers.py:142-145`, `routes_reports.py:258-272`, `routes_media.py:24-32,60-64`
- §2.2 — `api_request_id` = `req_` + 32 hex chars; `api_request_timestamp` reads the logical clock — `envelope.py:16-20`
- §2.2 — absent/malformed JSON body reads as `{}`, non-object body → `ERR_INVALID_REQUEST` — `auth.py:43-51`
- §2.2 — out-of-catalog envelope errors for unmatched path/method/500 (`ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED`/`ERR_INTERNAL`) — `app.py:36-53`
- §2.3 — pagination validation (`ERR_INVALID_REQUEST` for bad limit/offset), `created_at` ties break by creation order, `has_more` = offset+page < total, enum filter values validated (id filters unvalidated) — `envelope.py:47-81`, `routes_contests.py:75-84`, `routes_reports.py:164-171`
- §2.4 — clock endpoint answers 200 `{"current_utc": ...}`, unparseable → 400 — `routes_events.py:35-44`
- §2.4 — `version` starts at 1, `updated_at` == `created_at` at creation — `loaders.py:88-92`
- §2.5 — automatic reopen also increments event version — `routes_recounts.py:61-62`
- §2.5 — ungated operations admitted in every posture: REJECT/VOID, RETRACT, coverage review/revise, recount ACTIVATE/DISMISS/RESOLVE, coordinator RELEASE/NO_SHOW/REDEPLOY — `routes_reports.py:239-251`, `routes_calls.py:149-162`, `routes_coverage.py:112-167`, `routes_recounts.py:73-122`, `routes_stringers.py:158-196`
- §2.5 — missing/out-of-range `target_posture` → `ERR_INVALID_REQUEST` ahead of the declared-next check — `routes_events.py:92-96`
- §2.6 — payload-id resolution: county-link/assignment `county_id` → `ERR_COUNTY_NOT_FOUND`, coverage `contest_id` → `ERR_CONTEST_NOT_FOUND`, named `stringer_id` → `ERR_STRINGER_NOT_FOUND`; vote-report `county_id` → `ERR_COUNTY_NOT_IN_CONTEST`, proposal `winner_candidate_id` → `ERR_CANDIDATE_NOT_IN_CCONTEST` — `routes_contests.py:123-125`, `routes_coverage.py:58-60`, `routes_stringers.py:65-67,82`, `routes_reports.py:53-59`, `routes_calls.py:44-55`
- §2.7 — `expected_contest_version` must be an integer (else `ERR_INVALID_REQUEST` at the OCC position) — `routes_reports.py:72-82`, `routes_calls.py:35-42`
- §2.7 — version-advancing list exhaustive: recount-driven reopen and read-time recompute never advance contest version/`updated_at` — `routes_recounts.py:67-70`, `services_rollup.py:119-138`
- §2.9 — the twenty checks are exhaustive; "five-digit"/"two-letter" adjectives are descriptive (fields need only be non-blank); null reads as omitted for the four defaulted fields — adjudicated: §2.9 declares itself the complete check list, so enforcing the adjectives would contradict it (impl reading at least as faithful)
- §3.1 — `survey_turnout_estimate` any integer incl. non-positive; `historical_dem_share` echoed as float — `routes_counties.py:41-46,62`
- §3.1 — contest edit increments version even when no field changes — `routes_contests.py:101-109` (unconditional `touch`)
- §3.1 — linked-county state mismatch → `ERR_INVALID_REQUEST`, after cross-event, before duplicate-link — `routes_contests.py:126-136`
- §3.2 — budget sum excludes the decision under review (hours counted once; matters on FUND from APPROVED) — `routes_coverage.py:26-46`
- §3.2 — `rationale` must be a string — `routes_coverage.py:73-75`
- §3.2 — no-op revision admitted, returns DECLINED → PROPOSED — `routes_coverage.py:139-167`
- §3.3 — scores derivable from recorded outcomes (observationally equal to the three recompute moments) — `services_rules.py:90-124`, `routes_stringers.py:44,183-185`, `routes_reports.py:199-213`
- §3.3 — assignment creation sub-order (fields → county 404 → cross-event → window; named-stringer 404 ahead of overlap) — `routes_stringers.py:62-93`
- §3.3 — `stringer_id: null` reads as omitted — `routes_stringers.py:79-94`
- §3.3 — REDEPLOY re-checks the clock only, not overlap — `routes_stringers.py:187-195`
- §3.4 — channel exclusivity (`Stringer`+FEED / `FeedOperator`+STRINGER → `ERR_UNAUTHORIZED_ROLE` pre-path); invalid `source` → `ERR_INVALID_REQUEST` at the authority position — `routes_reports.py:89-96,119-120`
- §3.4 — membership details: unresolvable `county_id` is a membership failure; candidate membership judged over object-shaped entries only — `routes_reports.py:50-69,102-104`
- §3.4 — multi-DEM contests sum DEM votes in the swing check — `services_rules.py:36-50`
- §3.4 — collection authority consults status + stringer/county/event triple only, never the window — `services_rules.py:166-175`
- §3.4 — resubmission: no OCC, no authority/membership re-check, cross-channel → `ERR_UNAUTHORIZED_ROLE`, bumps report version only — `routes_reports.py:255-312`
- §3.5 — latest-accepted final tie-break by creation order — `services_rollup.py:21-33`
- §3.5 — read-time recompute refreshes the four numeric fields only; never moves `tabulation_status`, version, or `updated_at` — `services_rollup.py:119-138`, `serializers.py:52-54`
- §3.5 — county `COMPLETE` = at least one linked contest's latest accepted report covers `expected_precincts` — `services_rollup.py:142-164`
- §3.6 — retraction admitted in every posture; `reason` must be a string; PROPOSED retraction bumps the call's version only — `routes_calls.py:149-162`
- §3.7 — filing note accepted but not persisted (case carries only `resolution_note`) — `routes_recounts.py:26-47`
- §3.7 — dismissal/resolution note validated as string but dismissal note not persisted; RESOLVE checks ACTIVE before validating `outcome` — `routes_recounts.py:83-106`
- §3.7 — activation in TABULATION leaves `tabulation_status` untouched; reopen rides the posture reopen and leaves contest version/`updated_at` untouched — `routes_recounts.py:58-71,87-93`
- §3.8 — one `CALL_CREDIT` per flipped `CALL` delivery (two SENT CALLs → two credits) — `services_delivery.py:67-79`
- §3.8 — malformed `period` (incl. month 00/13) → `ERR_INVALID_REQUEST`; empty period yields `delivery_count` 0 / `total_fee_cents` 0 — `routes_media.py:21,101-127`, `services_delivery.py:82-92`

**IMPL BUGs:** none. Specifically hunted per the amendment:
- (a) All five prose uniqueness declarations carry catalog error_ids and all five are enforced with store scans (`routes_counties.py:49-51`, `routes_feeds.py:42-44`, `routes_contests.py:134-136,178-180`, `routes_media.py:112-117`).
- (b) No PRD-required check is defined-but-uncalled or shadowed; the only uncalled-looking prose ("five-digit", "two-letter") is adjudicated descriptive given §2.9's self-declared exhaustive 20-check list.
- (d) Filing/dismissal "accepts an optional note" is tolerated-not-persisted prose (the dismissal sentence itself denies storage via "leaving resolution_note null"), impl-consistent; retraction `reason` and resolution `note` are genuinely persisted.

**Nullable-field crash-path enumeration:**

| Nullable field (PRD) | Read sites | Guarded? |
|---|---|---|
| `county.survey_turnout_estimate` | `services_rollup.py:101` | yes — `is not None` branch, falls back to historical |
| `county.historical_dem_share` | `services_rules.py:36,48` | yes — `is not None` gate before swing computation |
| `report.submitted_by_stringer_id` | `routes_reports.py:201-205,262`; `serializers.py:135` | yes — `sid is None` early-return; equality filter; echo |
| `report.accepted_at` | `services_rollup.py:30`; `serializers.py:145` | yes — only ACCEPTED reports enter the tuple compare; serializer null-guarded |
| `call.published_by` / `published_at` / `retract_reason` | `serializers.py:156-159`; `routes_calls.py:130` | yes — SoD reads `proposed_by` (always set); serializer null-guarded |
| `recount.resolution_note` | `serializers.py:170` | yes — plain echo, null-safe |
| `coverage.rationale` | `serializers.py:183` | yes — plain echo |
| `contest.called_candidate_id` | `serializers.py:63`; `routes_calls.py:146` | yes — echo; assigned only on publish |
| `reliability_events[].event_id` (indirect null risk) | `services_rules.py:99,115-118` | yes — events never deleted; read path additionally filters `event_id in db["events"]` |
| `certainty ranked[seats]` | `services_rules.py:82` | yes — reachable only when `with_votes >= seats+1`, which bounds `len(ranked) > seats` |

No reachable 500s found on legal state combinations; every PRD-nullable read is guarded.

Orchestrator verification: PRD_COMPLETED.md confirmed on disk at 347 lines; no source file under implementation/, test_helpers/, or test_suite/ is newer than the final sweep's results files — Step 9 edited only workspace/*.md, so the 89/89 × 8 sweep remains valid. No Step 9b needed (0 IMPL BUGs reported). Pipeline complete.
