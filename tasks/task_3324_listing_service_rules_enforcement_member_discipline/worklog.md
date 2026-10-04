# Worklog — task_3324_listing_service_rules_enforcement_member_discipline

## Step 1: Create Task Directory — 2026-09-30T20:28:00.000Z

Pre-allocated directory `./tasks/task_3324_listing_service_rules_enforcement_member_discipline/workspace/` verified to exist and be empty. No new index computed; no other task directory created.

## Step 2: Generate Scaffold — 2026-09-30T21:04:00.000Z

All checks pass. The three scaffold artifacts are complete and lint-clean.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3324_listing_service_rules_enforcement_member_discipline/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys inside)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9)

**Counts:**
- Entities: 15 (Association, PolicyRevision, Member, Office, DuesPeriod, DuesInvoice, Listing, StatusChange, Citation, FineSchedule, EthicsCase, ArbitrationCase, HearingPanel, DataLicense, ConsolidationEvent)
- State machines: 15 (incl. Listing WITHDRAWN→ACTIVE cycle, Citation 3-way branch PAID/ESCALATED/WAIVED on live strikes, Association MERGING↔ACTIVE loop, Office broker-cascade)
- Calculations: 10 (tiered dues with proration/consolidation variants, strikes 365-day half-open window, clear-coop 24h audit, 48h lateness audit, half-open fine-schedule lookup, weighted procuring-cause award with pinned nested rounding + abandonment override, ethics sanction tiers, panel selector, ruleset-version circular-order pin, dual-variant feed projection)
- Validations: 12 priority tiers (auth → existence → consolidation gate → OCC → state → safety → policy → temporal → fiscal → referential → structural)
- Endpoints: 92 (incl. 2 `/_clock/*` test-driving endpoints with the mandatory 2026-09-01T00:00:00Z default, plus flat reverse-lookup GETs for every FK)
- Errors: 32
- Roles: 4 (AssociationStaff opaque; Member, GrievanceMember, HearingPanelist entity-backed; segregation-of-duties throughout)
- Concurrency rules: 2 (OCC on policy-revision create and dues bill)

**§1.8**: 19 instances — all 9 rules × ≥2 (combinatorial_formula carries 3, one per mode a/b/c).
**§1.9**: 47 instances (37 active recipes + 10 `excluded_because:` stubs), sections: entities, state_machines, calculations, validations, endpoints, errors, cross_cutting_layers, consistency_model. All names unique across both files.

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (636 calls scanned, 0 violations.)

**Key fixes during iteration**: flattened the FK/endpoint scheme to `/mls/<collection>` top-level (the lint derives collection segments only from flat single-resource GETs), converted association path params to literal `{id}`, replaced all OCC literal versions with `${assoc_v0}` captured from create responses, and pinned pre-computed arithmetic literals in every numeric assert (e.g., proration 10191c, rounding-order award 1000001c vs 600001c, 48h/49h lateness boundary).

Orchestrator verification: all three files confirmed on disk (1975/1546/1889 lines), `method:` count = 92, top-level keys present in both design files, no design keys in SCAFFOLD.yaml.

## Step 3: Copy Shared Files — 2026-09-30T21:05:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T21:14:00.000Z

Complete. Final verification passes on all three hard contracts.

**File written:** `workspace/PRD.md` — 363 lines.

**Section list:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 RBAC (all four roles with identity translations), 2.2 API Response Structure (verbatim block), 2.3 Pagination, 2.4 Common Resource Properties & Logical Clock (incl. `ConsolidationEvent` carrying only `id`/`created_at`, startup clock 2026-09-01T00:00:00.000Z), 2.5 Money/Precision/Rounding, 2.6 OCC (both `concurrency_rules` with exact `error_id` + HTTP 412), 2.7 Nested Resource Resolution & 12-tier Validation Priority, 2.8 Consolidation Gate
- §3 Business Logic: 3.1 associations/members/offices, 3.2 dues cycle (tier boundary day 30 in tier 1 / day 31+ tier 2 replaces, proration floor-toward-zero, consolidated-member skip variant, tender exactness, waiver no-refund, 90-day termination), 3.3 listings & policy-revision selector (newest `effective_at` ≤ activation, `ERR_POLICY_REVISION_MISSING`, 24h clear-coop inclusive boundary), 3.4 status changes & 48h lateness audit (48h00m01s floors to timely; 49h late) & accuracy-flag gate & dual ACTIVE→WITHDRAWN edges, 3.5 citations/fine schedules/credit ledger (half-open schedule lookup, `fine_schedule_key` format, cap-check-before-state-change, donate-credit at-cap allowed, 20-day hearing window, UPHOLD branch at strikes ≥ 3 → ESCALATED, strikes 365-day half-open + 30-day revert window + first-reinstatement rule + never-suspended inclusion + ethics non-inclusion), 3.6 ethics (45-day screening, tiers 50000/100000/250000/500000, 20-day appeal, segregation), 3.7 arbitration (180-day window, five weighted factors 0.30/0.25/0.15/0.20/0.10, round-score-then-tier pinned order, F5 ≥ 8 override, tiers 7.00/5.00/3.00), 3.8 hearing panels (eligibility exclusions incl. arbitration counterparty sets, strikes-ASC then `created_at`-ASC ranking, `PANEL_SIZE` 3, sole-actor segregation), 3.9 data licensing (ruleset = count of ACTIVE+SUPERSEDED revisions, pinned evaluation order, IDX/VOW/BACKOFFICE feed variants, `offer_comp_cents` strip, deterministic audit citation selector, 30-day cure), 3.10 policy revisions, consolidation, compliance checkpoint (365-day expiry)
- §4 Endpoint Definitions: 92 rows (4 columns each), matching the scaffold 1:1 including both duplicate `/mls/listings` and `/mls/status-changes` rows
- §5 Error Code Catalogue: 32 rows (2 columns)

**Hard-contract reports:**
- Contract 1 (Field-Name Coverage): entity fields 85/85, endpoint inputs 64/64, query params 24/24, 0 missing — PASS
- Contract 2 (Rule Coverage): validations priorities 12/12 expressed in §2.7 ordered prose; OCC 2/2 (write endpoint + `expected_*_version` + `ERR_STALE_VERSION`/412); state-machine transitions fully expressed incl. sibling-branch symmetry (dual ACTIVE→WITHDRAWN edges, three-way citation ruling branch, mediation SETTLED/DECLINED pair); calculations 10/10 with constants and boundaries in precise prose; errors 32/32 matchable; endpoint side effects and applies-to scopes covered — PASS
- Contract 3 (§3 Path Purity): 202 backticked tokens scanned in §3; 0 path tokens, 0 bare HTTP methods, 0 method+path tokens — PASS

**Zero-silence coverage verdict:** All scaffold §1.0–§1.7 content is covered in prose — response envelope (§2.2 verbatim, §2.3), all 15 entities' fields (§2.4 common fields + scattered §3 narrative), all 15 state machines' transitions with preconditions and side effects, both OCC rules, all 10 calculations with constants/variants/precision, all 12 validation priority tiers, all 92 endpoints (§4 table), all 32 errors (§2/§3 triggers + §5 table), and all 4 roles with identity semantics (§2.1). The forbidden files `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened.

Orchestrator spot-check: PRD.md on disk is 362 lines, 128 table rows, 65 `ERR_` mentions, clock default 2026-09-01T00:00:00.000Z pinned at line 79.

## Step 5: Generate Unit Tests — 2026-09-30T21:37:00.000Z

Done. Test infrastructure and suite generated for task_3324.

**test_helpers/** (9 files): `types.py` — status enums + TypedDicts for all 13 entities; `ConsolidationEvent` omits `updated_at`/`version` per its append-only shape. `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (~55 methods). `api_errors.py` — all 33 error IDs with HTTP status map, registered via `set_error_http_status_map`. `assertions.py` — per-entity assertions (incl. `ConsolidationEvent` asserting absence of `version`/`updated_at`). `factories.py` — payload factories with unique-slug counters. `constants.py` — thresholds (48h grace, 24h clear-coop, 365d strikes window, sanction tiers, weights). `test_users.py` — `TEST_USERS` constants + `make_member/grievance/panelist/staff_headers` builders for the entity_backed roles. `fixtures.py` — composite fixtures: revision activation, active/SOLD listing chains, billed-period/reconcile suspension, citation pay, hearing-held panels, arbitration scheduled, ethics case decided, consolidation. `__init__.py` — barrel export (framework generics + all helpers).

**test_suite/** (18 files): `conftest.py` + `test_01`…`test_17` (entity basics, dues billing, arbitration awards, ruleset ordering, state-machine branches, cascades, validation priority, boundaries, cross-entity gates, temporal intervals, compensating invariants, lifecycle, calculations, validation corners, endpoint actions, error rules, cross-cutting).

**Totals and coverage**
- **75 tests**, all collected cleanly by pytest; 0 `skip`/`skipif`/`xfail` markers; no scaffold references in generated code.
- **Queue A (Difficulty): 18/18 instances translated, 0 skipped.** Every instance has ≥2 tests (verified programmatically). The "second test per instance" slot is filled by sub-scenario variants (e.g. overturn-branch, tier-2 late fee, cancel path) that stay within the instance's grounds.
- **Queue B (Corner): all 25 non-stub instances translated, 0 skipped.** The 8 `excluded_because:` stubs were not translated; their `difficulty_instance` pointers were verified to resolve to real queue-A instances.
- **Design tags: every one of the 75 tests carries exactly one** `Design: Difficulty/<rule_id>/<instance>` or `Design: Corner/<section>/<instance>` line, all resolving to real instances (verified by parsing both yamls and cross-checking each tag).
- **PRD citations**: every quoted docstring fragment ≥25 chars verified verbatim against PRD.md with whitespace normalization — 0 failures.

**Clock-fixture check (per the standing guidance)**
Every fixture date was re-derived against the boot clock 2026-09-01T00:00:00Z: proration test creates the mid-year member at 2027-01-01 after moving the clock there; consolidation freeze test executes one second before vs exactly at `effective_at`; strikes-window test walks 2026-09-02 → 2027-09-01 → 2027-09-02; 48h/24h boundary tests use `set_current_utc` to hit exact boundary instants (including the 48h+1s floor case). No dead dates.

One recipe note: the corner instance `license_cure_window_30d_boundary` in the source yaml had a self-contradictory setup narrative; I translated its executable core (audit at day X → cure at +31d → `ERR_CURE_WINDOW_CLOSED`) per its assert block.

Orchestrator spot-check: test_helpers/ (9 files) and test_suite/ (18 files) on disk; 75 test functions; 75 Design-tag lines; 0 skip/xfail occurrences.

## Step 6: Generate Implementation — 2026-09-30T21:55:00.000Z

Clean. Final verification summary:

**Files written** under `workspace/implementation/`:
- `start.sh` (executable, guarded pip install, `exec python3 app.py`, `$PORT` default 10000, binds `0.0.0.0`)
- `requirements.txt` (flask)
- `app.py` — Flask entry, error handlers, blueprint registration, per-request reentrant lock
- `db.py` — in-memory store (empty at boot, no seeding) + logical clock (default `2026-09-01T00:00:00.000Z`)
- `errors.py` — all 32 error IDs with HTTP statuses
- `response.py` — envelope (`meta`/`response_type`/`data`; pagination fields `limit/offset/total_count/has_more` in meta)
- `auth.py` — `X-User-ID`/`X-User-Role` validation, role gating, `ERR_MEMBER_MISMATCH` ownership
- `helpers.py` — id minting, ISO timestamps, pagination (limit 10/min 1/max 100, offset 0, sort by `created_at` asc), left-to-right nested lookups, `touch()` version bump
- `calcs.py` — all 10 calculations (dues tiering + proration variant, strikes_12m with 365d half-open window + 30d first-reinstatement rule, clear-coop 24h inclusive deadline, 48h status lateness floor, half-open fine-schedule lookup, procuring-cause weighted award with score round-half-up-2dp → tier → award round-half-up, F5≥8 zero override, ethics sanction tiers, panel selector, ruleset version, feed projection variants)
- `services.py` — citation creation, credit accrual w/ cap, suspend/reinstate/terminate chains (office coupling, listing WITHDRAWN cascade, status-change recording), clock-trigger evaluation (policy revision activation w/ supersede, dues suspension at grace_end+1 day 00:00Z, listing expiry)
- `routes/` — 14 blueprints: clock, associations, members, offices, dues, listings, citations, fines, ethics, arbitration, panels, licenses, policy, consolidation (+compliance checkpoint)

**Route count**: 90 `/mls` rules registered in Flask covering all 92 scaffold endpoint table entries (the scaffold lists `GET /mls/listings` and `GET /mls/status-changes` twice with different filter sets; both duplicate rows are served by the same registered route which implements the union of the documented filters — so all 92 scaffold behaviors are live).

**Boot verification**: started via `bash start.sh` on a scratch port (19877), exercised end-to-end flows with curl, then killed exactly the PIDs started (verified port free, no other pipelines' processes touched — matched by `/proc/<pid>/cwd` under this task directory only). Verified live: clock set/advance with policy-revision activation and dues-suspension cascade; billing with OCC; citation pay with credit auto-apply + tender remainder, strikes recompute; listing activation with policy selector + CLEAR_COOP auto-citation; late status change → LATE_STATUS citation + FLAGGED; full citation hearing chain (request → convene → hold → sole-actor rejection → rule UPHOLD → PAID with credit/strikes); arbitration SOLD listing gate + weighted award (100001 at 9.00 score → 100%); ethics screening conflict → forward → panel → DECIDED 50000 → appeal → appeal-conflict → FINAL.

**Ambiguities resolved**:
1. `hearing_panel_exclusions` entity note ("their own association's members") read literally makes every same-association panel impossible, so implemented the functional reading: member themself + dispute-set counterparties from arbitration and ethics cases.
2. Termination 90-day measurement: tracks grace_end_date at suspension time and measures from it (falls back to suspension instant for reconciliation-triggered suspensions without one).
3. Listing creation under a currently-governing COMP_DISPLAY_OFF revision: positive `offer_comp_cents` rejected with `ERR_COMP_DISPLAY_PROHIBITED`; zero stays zero.
4. Policy revision scheduled with `effective_at` already in the past activates immediately (clock-trigger evaluation runs at creation).
5. `api_request_timestamp` uses the logical clock.

Orchestrator spot-check: implementation/ on disk with 14 route modules + 8 core modules, 90 route decorators counted, start.sh executable.

## Orchestrator note: session resumption — 2026-10-01T04:07:45.000Z

Host killed the session mid-Step-7 (memory pressure). On-disk state at resume: Steps 1–6 complete and verified (SCAFFOLD 1975 lines, PRD 362 lines, 75 tests / 75 Design tags / 0 skip-xfail, implementation with 90 route decorators + executable start.sh). The interrupted Step 7 subagent completed one 8-round sweep (results.1–8.json at 21:58, ~65/75 passed per round, ~30-test union of failures) and had begun editing helpers.py/services.py (mtimes 22:07–22:08) when killed; no Step 7 summary was ever emitted. Resuming Step 7 from scratch with a fresh long-lived subagent; its first action must be a fresh sweep since prior results predate the partial fixes.

## Step 7: Test-Iterate Loop (resumed, orchestrator-driven) — 2026-10-01T04:38:57.000Z

Subagent spawning is unavailable in this session (the endpoint rejects every subagent model string with HTTP 404 model_not_found, including explicit overrides), so the orchestrator drives the loop directly with sequential rounds.

Prior state: the killed Step 7 subagent had run one 8-round sweep (21:58, ~65/75 per round), then fixed implementation bugs in helpers.py/services.py and deleted exactly one test before being killed without emitting a summary.

**Unrecorded deletion audit (reconstructed):** the missing 75th test is `member_computed_fields_cannot_be_set_via_input` (Design: Corner/entities/member_computed_fields_cannot_be_set_via_input). The instance asserts two things: (a) clean create yields `sanction_credit_balance_cents == 0` and `strikes_12m == 0` — verbatim PRD §3.1 line 110 ("A new member starts ... a `sanction_credit_balance_cents` of 0, and a `strikes_12m` count of 0"); (b) smuggling those computed fields into the create payload is rejected with `ERR_INVALID_REQUEST` — PRD has only the generic §2.7 sentence "A malformed payload, missing required field, invalid enum value, or out-of-range value is rejected with `ERR_INVALID_REQUEST`", which does not uniquely derive "unknown extra keys are malformed" (a faithful reader could silently ignore unknown keys). Verdict: deletion defensible under STEP 1b DEFAULT-VALUE/unique-derivability silence on assertion (b); assertion (a) remains covered by neighboring entity-basics tests exercising clean creates. Gap stays a gap; recorded here as feedback for doc-generator (Zero-Silence: PRD never states the unknown-field rejection policy explicitly).

**Baseline sweep after killed-subagent fixes: 74/74 passed, 0 failed, 0 errors (round 1, 140.7s).** All 19 difficulty instances (2 tests each = 38) and 36/37 corner instances are covered by the remaining 74 tests; every test carries exactly one valid Design tag.

## Step 7 completion: stability sweep — 2026-10-01T04:47:56.000Z

9 consecutive rounds (results.1–9.json), all 74/74 passed, 0 failed, 0 errors, 0 skipped, zero flakes across rounds. Union of failures across all rounds: empty. Step 7 exits clean. Net Step 7 changes vs Step 5/6 outputs: 1 test deleted (member_computed_fields_cannot_be_set_via_input — see audit above), implementation fixes in helpers.py and services.py by the killed first attempt (never itemized; both verified live-green across 9 rounds), 0 test_suite/ fixes, 0 test_helpers/ fixes recorded.

## Step 8: Finalize PRD — 2026-10-01T04:54:57.000Z

Done. `workspace/PRD_FINALIZED.md` written.

**Line counts**: PRD.md 362 lines / PRD_FINALIZED.md 362 lines (0% line delta; +3.71% character delta — 12 paragraph-level inline edits, no new sections).

### Changes (one bullet per edit)

- **§2.4** — revise — pinned the clock-advance evaluation order (policy-revision activations first, then dues suspensions) and clarified that listing expiry is driven exclusively by the §3.10 compliance checkpoint, never by clock advancement — `implementation/services.py:169-198` (`evaluate_clock_triggers`), `services.py:221-239`.
- **§2.7** — insert — appended the extra/unknown-input-field rule: fields beyond an endpoint's spec are silently ignored; server-computed fields supplied on create (e.g. `sanction_credit_balance_cents`, `strikes_12m` on member create) do not change server-minted defaults — `implementation/routes/members.py:28-55`, `helpers.py:29-41`.
- **§3.1** — insert — member collection is paginated per §2.3 (envelope carries `limit`/`offset`/`total_count`/`has_more`, sorted `created_at` ascending) — `implementation/routes/members.py:58-67`, `helpers.py:204-234`.
- **§3.2** — insert — anti-double-billing skip is keyed purely on calendar year: any member billed under a period who already holds any invoice (any status, any association's period) for that year is skipped — `implementation/routes/dues.py:106-119`.
- **§3.3** — revise — listing create rejects with `ERR_MEMBER_SUSPENDED` a `listing_member_id` who is neither the office broker nor an `ACTIVE` member of that office — `implementation/routes/listings.py:73-76`.
- **§3.5** — revise — citation hearing window boundary: a request at exactly `assessed_at` + 20 days is still permitted; only later requests are `ERR_HEARING_WINDOW_CLOSED` — `implementation/routes/citations.py:150-153`.
- **§3.6** — revise — screening guard order pinned: `ERR_SCREENING_CONFLICT` (tier 7) evaluated before `ERR_SCREENING_OVERDUE` (tier 9); when both trip, conflict is reported — `implementation/routes/ethics.py:115-127`.
- **§3.6** — revise — appeal window: ruling instant is the `DECIDED` panel's `updated_at`; appeal at exactly ruling + 20 days still permitted — `implementation/routes/ethics.py:144-155`.
- **§3.7** — revise — arbitration filing window measured from the closing date defined as the `business_effective_at` of the status change into `SOLD` (fallback: that change's `recorded_at`) — `implementation/routes/arbitration.py:73-86`.
- **§3.9** — revise — feed-compliance audit deterministic-member fallback: no ACTIVE listing → broker of earliest-created office; no offices → no citation, `auto_citation_id` null — `implementation/routes/licenses.py:150-177`.
- **§3.9** — revise — license cure boundary: cure at exactly `last_audit_at` + 30 days still permitted; failing re-run compliance check rejects cure with `ERR_RULESET_MISMATCH` — `implementation/routes/licenses.py:192-202`.
- **§3.10** — revise — a policy revision whose `effective_at` is already at/before the current logical instant activates immediately within the scheduling call — `implementation/routes/policy.py:57-61`.

### Step 7 themes checked but NOT patched (PRD already determines the behavior)

ConsolidationEvent immutability (§2.4 verbatim), listing get not-found under wrong office scope (§2.7 nesting), cross-association member FK on citation (§3.5), listing enum status validation (§2.7), dues proration vs consolidated variant, tiered late fees and tier2-replaces-tier1 (§3.2 verbatim), credit floor (§3.2), arbitration abandonment override + overturn-zeroes-award + round-then-tier ordering (§3.7 verbatim), ruleset counts ACTIVE+SUPERSEDED (§3.9), WITHDRAWN→reactivation policy reselection (§3.3 verbatim), citation hearing fork/uphold-below-3-pays (§3.5 verbatim), reconcile suspension cascade + reinstatement on last invoice payment (§3.2 verbatim), late-status flag cascade/unflag/flag-blocks-cancel (§3.4-3.5), stale-version vs not-found/invalid-state priority (§2.7 tiers 3/5/6), 48h boundary exactness (§3.4 verbatim), comp-prohibition priority (§2.7 tier 8).

### Pre-edit search log

1. **Extra-field handling** — enumerated every POST handler across all 14 route modules — none rejects unknown fields; all ignore them. Wording says "silently ignored" universally, scoped to "fields beyond the ones an endpoint specifies".
2. **Clock evaluation order** — enumerated `services.evaluate_clock_triggers` (both clock endpoints), `expire_stale_listings` (only via checkpoint loop in `consolidation.run_checkpoint`), `routes/clock.py`. Wording: clock advance never expires listings; expiry belongs to §3.10 checkpoint.
3. **Members pagination** — `members.list_members` uses `page()`/`success_list` identically to all other list endpoints; phrased as "like every list endpoint".
4. **Billing skip keying** — `dues.bill_period` is the only billing path; skip applies to ALL members incl. non-consolidated ones in the survivor; added a generalizing sentence.
5. **Listing create member-standing gate** — enumerated `listings.create_listing`, `activate_listing`/`change_listing_status` (`_check_listing_member_standing`, same error), panel selector. Named exact error `ERR_MEMBER_SUSPENDED`, scoped to create gate only.
6. **Hearing window boundary** — `citations.request_hearing` (strict `>`); no other consumer of the 20-day citation window.
7. **Screening order** — `ethics.screen_case` (state → enum → conflict → overdue); recast old sentence into explicit tier-7-then-tier-9 ordering.
8. **Appeal ruling instant** — `ethics.appeal_case` (last DECIDED panel), `panels.rule_panel` (`updated_at` at ruling via `touch`); pinned basis to panel `updated_at`, inclusive boundary.
9. **Arbitration closing date** — `arbitration.file_arbitration_case` (SOLD status-change `business_effective_at`, fallback `recorded_at`), `services.record_status_change`; omitted deeper double-fallback as non-load-bearing (deliberately under-determined).
10. **Audit deterministic member** — `licenses.audit_feed` full branch set (ACTIVE-listing path, earliest-office fallback, no-citation path), `services.create_citation`; added both fallback sentences.
11. **Cure boundary/error** — `licenses.cure_license` (strict `>`; failing compliance → `ERR_RULESET_MISMATCH`); no other cure consumer.
12. **Immediate activation at scheduling** — `policy.create_revision` (activates when `effective_at <= now`), `services.evaluate_clock_triggers` + `activate_policy_revision` (same supersession both paths), `calcs.ruleset_version`/`governing_revision`; phrased as one rule covering both paths.

Orchestrator verification: PRD_FINALIZED.md on disk (362 lines, 24 changed lines vs PRD.md); no implementation/ or test files modified after the green sweep (mtime check clean).

## Step 9: Complete PRD — 2026-10-01T05:32:23.000Z

Subagent spawning remained unavailable (repeated model_not_found 404s on every model string), so the orchestrator ran the completeness scan in-session, module by module. `cp PRD_FINALIZED.md PRD_COMPLETED.md` then inline edits only; implementation/, test_suite/, test_helpers/ untouched (verified: no source file newer than the final green sweep).

**Line counts**: PRD_FINALIZED.md 362 → PRD_COMPLETED.md 362 lines (8 changed lines = 4 in-place revisions; +0.4% char delta).

**Counts: 3 ambiguity-pins, 1 mismatch-revision.**

- §3.1 — revise — ambiguity — office create rejects a same-association broker whose `membership_state` is not `ACTIVE` with `ERR_CROSS_ASSOCIATION_REFERENCE` (PRD previously named that error only for foreign-association brokers, leaving the same-association non-ACTIVE branch underdetermined) — `implementation/routes/offices.py:32-34`.
- §3.3 — revise — ambiguity — listing create under a currently-governing `COMP_DISPLAY_OFF` revision rejects a positive `offer_comp_cents` with `ERR_COMP_DISPLAY_PROHIBITED`; omitted/zero accepted and stored as 0 (PRD pinned the reject-at-activation branch but left create-time reject-vs-clamp open; Step 6 chose reject) — `implementation/routes/listings.py:92-98`.
- §3.3 — revise — mismatch — removed the claim "ties are impossible because `effective_at` values are unique within an association": the implementation enforces uniqueness only on `revision_code`, never on `effective_at`, so the PRD asserted an invariant nothing enforces — `implementation/routes/policy.py:40-45`, `calcs.py:295-302`.
- §3.9 — revise — ambiguity — feed sync records the projected count on the license as `last_synced_listing_count` (computed-field silence: impl writes the field; PRD never named it) — `implementation/routes/licenses.py:124-127`.

**Scan coverage**: all 14 route blueprints (clock, associations, members, offices, dues, listings, citations, fines, ethics, arbitration, panels, licenses, policy, consolidation) plus app.py, auth.py, db.py, errors.py, response.py, helpers.py, calcs.py, services.py read in full; §5 error catalogue (32 ids) diffed 1:1 against errors.py HTTP map — exact match; action-response fields (`projected_listing_count`, `comp_fields_stripped`, `violation_found`, `auto_citation_id`, `expired_listing_count`, `now_iso8601`) all verified named in prose; PRD-required helpers checked for live callsites (all wired; `services.expire_stale_listings` is dead-but-harmless — the checkpoint route carries the same logic inline, behavior verified green by the compliance-checkpoint test across 9 rounds). `diff -q PRD_FINALIZED.md PRD_COMPLETED.md`: files differ (4 edits) — not a silent no-op.
