# Worklog — task_3260_bug_bounty_program_scope_triage_award_administration

## Step 1: Create Task Directory — 2026-09-30T15:10:00.000Z

Pre-allocated task directory `./tasks/task_3260_bug_bounty_program_scope_triage_award_administration/` verified to exist with `workspace/` inside. No new index computed (per command args).

## Step 2: Generate Scaffold — 2026-09-30T15:44:00.000Z

All three files are on disk and lint-clean. Done.

**Summary**

Task: `task_3260_bug_bounty_program_scope_triage_award_administration` (bug bounty program scope, triage & award administration).

Files written:
- `/home/ubuntu/github/CodingPRD/tasks/task_3260_bug_bounty_program_scope_triage_award_administration/SCAFFOLD.yaml` — 839 lines. 9 entities (Program, ScopeAsset, ScopeVersion, Researcher, ProgramInvitation, Report, Award, DisclosureRequest, RemediationTicket), 8 state machines (cyclic: Report DUPLICATE↔TRIAGED revert loop, Award APPROVED↔BLOCKED penalty cycle, Researcher ACTIVE→SUSPENDED→ACTIVE clock sweep, DisclosureRequest 3-round negotiation cycle), 6 calculations (severity base-vs-environmental dual variant, bounty tiered formula with nested pool-cap min(), per-award withholding with pinned round-then-sum order, lifetime-vs-rolling180 reputation dual variant, SLA breach flags with strict `>` boundary, invitation/suspension expiry sweep), 14-priority validation stack, **42 endpoints** (just over the 40 cap — two extra single-GET reads added to satisfy lint's FK segment-derivation heuristic; all other operations consolidated), 28 error codes, 5 roles (Anonymous / Researcher entity-backed / Triager / ProgramAdmin / PlatformAdmin with propose→approve→pay segregation of duties), 1 OCC concurrency rule on `PATCH /api/programs/{id}`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1195 lines, **18 difficulty instances** (2 per each of the 9 §0.5 rules), all with structured `setup_api_calls` chains, literal-pinned asserts (e.g. withholding 2424+2448=4872 vs aggregate 4873; bounty capped at 2100000; reputation 250 exactly at tier boundary).
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1396 lines, **40 corner instances (31 active + 9 excluded stubs)** across sections entities / state_machines / calculations / validations / endpoints / errors / rbac / cross_cutting_complexity_layers / consistency_model.

Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (486 calls scanned.)

Notable design decisions made to satisfy constraints: blackouts folded into `Program.blackout_windows` (PATCH-validated closed intervals with ≥3600s gap) instead of a separate entity; conduct enforcement folded into `POST /api/researchers/{id}/conduct-actions` (WARNING/STRIKE/BAN/REVERSE_LAST) instead of a ConductCase entity; award VOID added as an explicit endpoint so the state machine's VOID terminal is reachable. Mid-generation fixes: allowed MARK_DUPLICATE from VALIDATED, relaxed invitation issuance to any program visibility (PRIVATE only gates submission), and converted two nested list endpoints to filtered-list form to satisfy lint check (f).

Orchestrator note: endpoint count is 42, marginally over the 40 cap; Step 6 subagent will be instructed to write files incrementally and verify each file lands on disk to mitigate the known impl-gen overshoot failure mode.

## Step 3: Copy Shared Files — 2026-09-30T15:45:00.000Z

Copied `./INSTRUCTION.md` → `./tasks/task_3260_bug_bounty_program_scope_triage_award_administration/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T15:52:00.000Z

PRD generation complete. Summary:

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3260_bug_bounty_program_scope_triage_award_administration/workspace/PRD.md` — 291 lines, ~46 KB.

**Section list:**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications — 2.1 RBAC + identity semantics, 2.2 Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Validation Order & Error Precedence (14-priority stack rendered as an explicit ordered list), 2.6 Monetary Values/Ledgers/Precision, 2.7 OCC, 2.8 Logical Clock & Sweeps, 2.9 Cascading Side Effects, 2.10 Status Code Conventions
- §3 Business Logic — 10 subsections: program posture, scope assets/versions, researchers/reputation/conduct, invitations, report intake, triage actions, validation/severity scoring, remediation cascade, awards/bounty math/withholding, coordinated disclosure
- §4 Endpoint Definitions — 4-column table, all 42 scaffold endpoints matched verbatim by path
- §5 Error Code Catalogue — 2-column table, all 28 error IDs matched verbatim with correct HTTP statuses

**Verbatim coverage confirmed by scripted diff:**
- All 9 entities' field names (97 required backticked identifiers incl. endpoint-only params like `expected_program_version`, `to_iso8601`, `document_type`, `mark_verified`, and clock-output fields `now`/`invitations_expired`/`researchers_reinstated`) — 0 missing
- All 42 endpoint paths in §4 — exact match against scaffold
- All 28 error IDs + statuses in §5 — exact match against scaffold
- All state values (`DRAFT/ACTIVE/PAUSED/CLOSED`, `NEW/TRIAGED/NEEDS_INFO/VALIDATED/RESOLVED/DUPLICATE/NOT_APPLICABLE/INFORMATIVE`, `PROPOSED/APPROVED/BLOCKED/PAID/VOID`, `REQUESTED/UNDER_NEGOTIATION/AGREED/PUBLISHED/DENIED`, `OPEN/IN_PROGRESS/FIXED/VERIFIED/WONT_FIX`, `PENDING/ACCEPTED/DECLINED/EXPIRED`, `ACTIVE/SUSPENDED/BANNED`) and enum values (`PUBLIC/PRIVATE`, `CRITICAL/HIGH/MEDIUM/LOW/NONE`, `NOVICE/ESTABLISHED/ELITE`, `MISSING/SUBMITTED/VERIFIED`, `BOUNTY/BONUS/RETEST`, `XSS/SQLI/CSRF/SSRF/AUTHZ/RCE/OTHER`, `SANCTIONED_COUNTRY/TAX_DOCUMENT`, `WARNING/STRIKE/BAN/REVERSE_LAST`) — 0 missing

**Contract reports:**
- Contract 1 (Field-Name Coverage): PASS — 97/97 required identifiers present in backticks
- Contract 2 (Rule Coverage): PASS — 14-priority validation ordering stated explicitly; OCC rule with `expected_program_version`/`ERR_STALE_VERSION`/412; all 6 calculations (severity_score weights + band thresholds, bounty severity bases + criticality multipliers + tier/first-report bonus + pool cap, per-award-then-sum withholding with 0/30/24 rates and 60000-cent threshold, reputation deltas incl. exact REOPEN compensation and inclusive 500/250 tier thresholds, strictly-greater SLA breach flags, 7-day invitation TTL and 14-days-per-strike suspension); all 8 state machines' transitions with preconditions and side effects; all cascade hops; sibling-branch symmetry (triage actions, withholding rate branches, severity bands) checked by 40+ targeted prose assertions
- Contract 3 (§3 Path Purity): PASS — 447 backticked tokens in §3, 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos

## Step 5: Generate Unit Tests — 2026-09-30T16:10:00.000Z

Everything is verified on disk. Final summary:

## Summary

**Task**: `task_3260_bug_bounty_program_scope_triage_award_administration` — test generation complete.

### Files written (19 total, 3,106 lines)

`test_helpers/` (988 lines):
- `test_helpers/types.py` (290) — 10 status enums, role enum, 10 entity TypedDicts (all entities carry the full common field set per PRD §2.4)
- `api_client.py` (149) — `ApiClient(GenericApiClient)` with 40 endpoint methods (one per PRD §4 row) plus singleton
- `api_errors.py` (70) — 28 `ApiErrorId` members + HTTP status map, registered with `set_error_http_status_map`
- `assertions.py` (119) — per-entity `assert_*` + `assert_pool_ledger_conserved` (reserved+paid+available == pool)
- `factories.py` (107), `constants.py` (56), `test_users.py` (19, includes mandatory `make_researcher_headers(user_id)` for the entity_backed Researcher role), `fixtures.py` (174 — composite helpers: `setup_active_program`, `create_validated_report`, `resolve_report`, `submit_tax_document`/`verify_tax_document`, `issue_invitation`, `set_clock`), `__init__.py` (30, barrel export)

`test_suite/` (2,118 lines): `conftest.py` + 16 numbered test files (`test_01`…`test_16`), 68 test functions total.

### Tests emitted per queue
- **Queue A (Difficulty): 36 tests covering all 18 instances, each with ≥2 tests.** Zero shortfalls.
- **Queue B (Corner): 32 tests covering all 31 non-stub instances, each with ≥1 test** (the disclosure instance got 2). Zero shortfalls.
- The 9 `excluded_because:` stubs were not translated; all 9 `difficulty_instance` cross-references resolve to real difficulty instances.

### Instances skipped
**None.** All 18 difficulty and 31 active corner instances passed the PRD-first two-condition filter (verbatim coverage + unique derivability). All threshold/boundary semantics (`>=` min_reputation, strictly-greater SLA breach, inclusive suspension reinstatement, half-open scope windows vs closed blackout intervals with 3600s gap, per-award-then-sum withholding) are stated verbatim in PRD prose.

One deviation from a literal YAML value, required by PRD fidelity: `award_approved_blocked_paid_cycle`'s distinguishing_aspect mislabels severity ("MEDIUM (6/5/4) → 6.4"); the PRD formula pins base = 5.3 → adjusted 6.4 (MEDIUM band) → bounty 330,000 → 24% withholding 79,200 / net 250,800, matching the YAML's own assert block. Tests use the PRD-derived values.

### Stage 2 tag audit result (re-run by me against the on-disk files)
- All 68 test functions carry exactly one `Design:` tag; no untagged, dual-tagged, or bogus tags; no stub tags emitted.
- Verbatim citation sweep: every quoted docstring span matches PRD.md literally (modulo whitespace) — ALL CITATIONS VERBATIM-CLEAN.
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no "scaffold" mentions in generated code.
- All 19 files byte-compile; the `test_helpers` barrel imports cleanly against the installed framework.

## Step 6: Generate Implementation — 2026-09-30T16:25:00.000Z

Implementation complete for task_3260 (bug bounty program administration), written to `/home/ubuntu/github/CodingPRD/tasks/task_3260_bug_bounty_program_scope_triage_award_administration/workspace/implementation/`.

## Files written (19 total, ~2100 lines)

Foundation:
- `requirements.txt` (1 line — flask), `start.sh` (executable, guarded pip install + `exec python3 app.py`)
- `app.py` (50) — Flask app, blueprint registration, ApiError/404/405/500 handlers, `0.0.0.0:$PORT` (default 10000)
- `clock.py` (41) — logical clock, fixed start at 2026-09-01T00:00:00Z, never wall-clock; ISO8601 parse/format with 3-digit millis
- `db.py` (16) — empty in-memory stores, reputation ledger (no seeding)
- `errors.py` (44) — all 28 scaffold error IDs with HTTP statuses
- `response.py` (43) — envelope: `meta{api_request_id,api_request_timestamp[,limit,offset,total_count,has_more]}`, `response_type`, `data{error_id,message}`
- `middleware.py` (31) — X-User-ID/X-User-Role auth, role check, researcher ownership
- `helpers.py` (91) — id minting, common fields (id/created_at/updated_at/version), field validation, pagination (limit default 10, 1–100)

Services:
- `services/reputation.py` (51) — lifetime/rolling180 (boundary-inclusive 180d), tier thresholds (ELITE ≥500, ESTABLISHED ≥250), severity resolution deltas
- `services/calculations.py` (72) — Decimal-based severity (round-half-up 1dp, ENV_FACTOR × exposure_modifier, banded severity_final), bounty (raw × crit mult, additive first-report+tier bonus, pool cap), withholding (0%/30%/24% per-award round-half-up)
- `services/cascades.py` (129) — clock sweep (invitation expiry strictly-past, suspension reinstate at-or-past, rolling recompute), conduct actions with exact REVERSE_LAST compensation via ledger tagging, standing recompute (2 strikes → SUSPENDED with ends_at = last strike + 14d × count; ≥3 or BAN → BANNED), invitation-decline cascades

Routes (all 42 endpoints from the scaffold table):
- `routes/programs.py` (210) — create/read/PATCH with OCC (`expected_program_version` → ERR_STALE_VERSION 412, blackout ≥3600s gap, pool floor), activate (scope-version-required), pause, close with invitation cascade
- `routes/assets.py` (82), `routes/scope_versions.py` (101, half-open non-overlap, adjacency allowed, per-program version_seq), `routes/researchers.py` (102, unique handle, tax submit/verify, conduct actions), `routes/invitations.py` (121), `routes/reports.py` (302, full triage machine + duplicate anchoring + reopen compensation + severity validation), `routes/awards.py` (215, bounty/bonus/retest rules, approve pool reservation, pay with sanctions→BLOCKED and tax→BLOCKED gates, BLOCKED retry only for cured TAX_DOCUMENT, void compensation), `routes/disclosure_requests.py` (155, COUNTER cap 3, AGREE default, PUBLISH gates: RESOLVED → timing before blackout), `routes/remediation_tickets.py` (133, VERIFY three-hop cascade), `routes/clock_routes.py` (34)

## Verification

Smoke boot on PORT=18743 succeeded; exercised end-to-end: program create/activate, asset + scope version, researcher register, report submit (NEW) → triage (TRIAGED) → validate (impact 9/exploit 8/scope 7 on HIGH asset → base 8.3, adjusted 9.1, CRITICAL, first-report true) → BOUNTY proposed 1,650,000 cents (1,000,000 × 1.5 + 10% first-report bonus) → approved (pool reserved) → pay blocked with ERR_TAX_DOC_REQUIRED → tax submit/verify → paid (0% withholding, US+VERIFIED) → remediation ticket START/FIX/VERIFY → report RESOLVED, researcher reputation 100→200, tier recomputed → clock set to 2027 sweeps cleanly. Server killed by exact PID (2881165); no other processes touched. Test suite was not read or run, per the isolation rule.

## Step 7: Run Tests and Iterate — 2026-09-30T16:32:00.000Z

All 8 rounds pass 68/68. Clean sweep achieved.

## Summary

- **Iterations run:** 2 (initial sweep: 60/68 in all 8 rounds, deterministic; post-fix sweep: 68/68 in all 8 rounds).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:**
  - `test_suite/test_14_corner_endpoints.py` — module-level helper `_setup_agreed_disclosure_with_blackout()` referenced the bare name `api` (a pytest fixture parameter), causing `NameError` in both `test_disclosure_negotiation_rounds_cap_at_three` and `test_disclosure_publish_timing_then_blackout_then_success`. Replaced with the imported `api_client` (the same object the `api` fixture returns). Test bug, not implementation bug — the request construction was fine, only the reference was broken.

- **Fixes applied to `implementation/`:**
  - `workspace/implementation/clock.py` — split timestamp rendering: `iso()`/`iso_now()` now emit the logical clock's canonical whole-second `Z` form (PRD §2.8: "The clock starts at exactly 2026-09-01T00:00:00Z"; clock-stamped fields like `submitted_at`, `response_due_at`, `resolved_at`, `suspension_ends_at` are "stamped from the logical clock" and the clock carries no sub-second precision). New `iso_ms()`/`iso_now_ms()` keep the three-fractional-digit form for the fields where PRD §2.2/§2.4 explicitly requires it (`api_request_timestamp`, `created_at`, `updated_at`). This fixed 5 tests: `test_ticket_verify_cascades_report_resolution`, `test_conduct_second_strike_suspends_researcher`, `test_sla_response_breach_at_exact_deadline_not_breached`, `test_clock_sweep_reinstates_suspended_researcher`, `test_report_read_reflects_logical_clock_immediately`.
  - `workspace/implementation/helpers.py` — `base_entity()`/`touch()` now use `iso_ms`/`iso_now_ms` so `created_at`/`updated_at` keep PRD's three-fractional-digit format after the clock.py change.
  - `workspace/implementation/routes/awards.py` (`pay_award`) — a `BLOCKED` award with `block_reason == "SANCTIONED_COUNTRY"` previously raised `ERR_INVALID_STATE` on retry. PRD §3.9 states retries traverse "the same payment path" with sanctions screened first and "no cure path for a sanctions block", so the retry must surface `ERR_SANCTIONED_COUNTRY` again. Reordered the retry gate accordingly. Fixed `test_sanctioned_country_pay_blocked_no_recovery`.

- **No PRD-silent tests found; no assertions weakened; no implementation checks removed.** All 68 tests now pass in every one of the 8 parallel rounds.

Orchestrator verification: independently re-read all 8 `results.{i}.json` (each passed 68/68, failed 0) and confirmed via mtimes that all implementation edits (16:26–16:27) predate the final sweep's results files (16:29–16:30) — the clean sweep ran against the fixed implementation.

## Step 8: Finalize PRD — 2026-09-30T16:38:00.000Z

Both edits committed cleanly. The test_suite fix in `<step_7_diff>` (the `api` → `api_client` NameError in test_14) is a pure test bug, not a PRD silence or impl mismatch — no PRD edit needed for it.

## Summary

**Line counts:** PRD.md = 291 lines; PRD_FINALIZED.md = 291 lines; 0% line-count delta (2 lines modified in place, no insertions/deletions of lines).

**Changes:**
- **§2.8** — revise — pins that every business timestamp the server stores and returns (clock-stamped fields like `submitted_at`, `response_due_at`, `resolved_at`, `suspension_ends_at`, plus client-echoed instants like `effective_from`/`proposed_publish_at`, and the clock endpoint's `now`) renders in whole-second `Z` ISO 8601 form with no fractional component, and that the three-fractional-digit format applies only to `api_request_timestamp`, `created_at`, `updated_at` — `implementation/clock.py:19-39` (`_fmt_z`/`_fmt_ms` split), `implementation/helpers.py:17-25`, `implementation/response.py:16-19`.
- **§3.9** — revise — pins that retrying a `BLOCKED` award whose `block_reason` is `SANCTIONED_COUNTRY` fails again with `ERR_SANCTIONED_COUNTRY` (not `ERR_INVALID_STATE`), the award stays `BLOCKED`, and the pool reservation is retained — `implementation/routes/awards.py:163-182`.

**Per-edit pre-edit search log:**

1. **§2.8 timestamp-format edit**
   - (a) Subject: rendering format of all logical-clock-derived/business timestamps.
   - (b) Paths enumerated: grep for `iso_now|iso_ms|iso(` across all of `implementation/` — `routes/reports.py` (submitted_at, response_due_at, first_response_at, triaged_at, validated_at, resolution_due_at), `routes/invitations.py:64-65` (issued_at, expires_at), `routes/remediation_tickets.py:58,123,126` (due_at, verified_at, resolved_at), `routes/awards.py:104,147,199` (proposed_at, approved_at, paid_at), `routes/scope_versions.py:70-71` (effective_from, effective_to), `routes/disclosure_requests.py:55,112-123` (proposed_publish_at, agreed_publish_at), `services/cascades.py:82,122` (applied_at, suspension_ends_at), `routes/clock_routes.py:30` (`now`), `helpers.py:17-25` (created_at/updated_at via `iso_ms`), `response.py:17-19` (`api_request_timestamp` from wall clock with 3 fractional digits). Also verified `strftime("%Y-%m-%dT%H:%M:%SZ")` truncates fractional seconds for client-supplied instants.
   - (c) Wording adjustment: initial draft said "timestamp the server derives from this logical clock," which under-covered client-echoed fields (`effective_from`, `proposed_publish_at`, `agreed_publish_at`); revised to "business timestamp the server stores and returns — fields stamped or computed from the logical clock, or echoed from client-supplied instants" and added an explicit carve-out sentence limiting the three-fractional-digit rule to the three fields §2.2/§2.4 already pin, so no existing PRD sentence is contradicted.

2. **§3.9 sanctions-retry edit**
   - (a) Subject: pay-endpoint behavior on a `BLOCKED` award retry.
   - (b) Paths enumerated: full read of `implementation/routes/awards.py::pay_award` (lines 152-205) — PROPOSED gate (ERR_AWARD_NOT_PAYABLE), non-APPROVED/non-BLOCKED gate (ERR_INVALID_STATE), BLOCKED+SANCTIONED branch (re-raises ERR_SANCTIONED_COUNTRY before any mutation, so no `touch` and reservation untouched), BLOCKED+TAX_DOCUMENT cure path (falls through to the shared sanctions/tax gates and ledger settlement), and the fall-through sanctions gate that still blocks an APPROVED award. Cross-checked `test_sanctioned_country_pay_blocked_no_recovery` which asserts ERR_SANCTIONED_COUNTRY on retry plus `bounty_reserved_cents` unchanged.
   - (c) Wording adjustment: added "the award remains `BLOCKED` with its pool reservation retained" to match the no-mutation branch; kept the existing tax-cure sentence verbatim so the cure path is unaffected.

**No edit made for** the `test_suite/test_14` `api` → `api_client` fix — it is a pure test-fixture bug (NameError), not a PRD silence or impl/PRD mismatch.

## Step 9: Complete PRD — 2026-09-30T16:48:00.000Z

All edits complete. The file remains 291 lines (all changes are in-paragraph revisions). Final summary:

## Summary

**Source**: `PRD_FINALIZED.md` → `PRD_COMPLETED.md` at `/home/ubuntu/github/CodingPRD/tasks/task_3260_bug_bounty_program_scope_triage_award_administration/workspace/PRD_COMPLETED.md`
- Line counts: 291 → 291 (no new paragraphs/sections; all inline inserts/revisions)
- Char delta: 47,450 → 52,662 (+5,212 chars)

**Counts**: 23 ambiguity-pins, 1 mismatch-revision (24 changes total).

**Changes** (one bullet each):

- §2.3 Pagination — insert — ambiguity — malformed/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST`; `has_more` formula pinned; same-instant ties keep creation order — implementation/helpers.py:70-91, response.py:27-34
- §2.4 Common properties — insert — ambiguity — `version` starts at 1, `created_at`==`updated_at` at creation; unmatched routes/methods → `ERR_NOT_FOUND` (404) envelope — helpers.py:13-21, app.py:34-41
- §2.6 Pool ledger — insert — ambiguity — program responses expose derived `available_pool_cents` — serializers.py:11-16
- §2.8 Clock — insert — ambiguity — malformed `to_iso8601` → `ERR_INVALID_REQUEST`; clock may be set to any instant, including earlier — clock_routes.py:22-26
- §3.1 Posture lifecycle — insert — ambiguity — activate/pause/close from an illegal posture, and close preconditions, all rejected with `ERR_INVALID_STATE` — programs.py:170-171, 183-184, 194-206
- §3.1 Program update — insert — ambiguity — `visibility` immutable on PATCH (`ERR_INVALID_REQUEST`); check order pinned (CLOSED → stale-version → blackout-overlap → pool floor); blackout validation applies at create too; closed-interval endpoint equality counts as overlap; malformed window → `ERR_INVALID_REQUEST` — programs.py:38-65, 132-153
- §3.2 Assets — insert — ambiguity — invalid `criticality` → `ERR_INVALID_REQUEST`; retiring non-`ACTIVE` asset → `ERR_INVALID_STATE` — assets.py:35-36, 78-79
- §3.2 Scope versions — insert — ambiguity — `effective_to` must be strictly after `effective_from`; malformed instants → `ERR_INVALID_REQUEST`; `safe_harbor_text` optional/null; `version_seq` starts at 1 — scope_versions.py:36-44, 62-74
- §3.3 Registration — insert — ambiguity — duplicate `handle` → `ERR_INVALID_REQUEST` — researchers.py:37-39
- §3.3 Conduct — revise — ambiguity — conduct actions may be filed on a `BANNED` researcher (log entry and delta still recorded); suspension end = most recent unreversed strike's `applied_at` + 14 days × strike count; `REVERSE_LAST` decrements `strike_count` for a reversed `STRIKE` and is a successful no-op when no unreversed entry exists — cascades.py:46-129
- §3.3 Tax documents — insert — ambiguity — missing `document_type` → `ERR_INVALID_REQUEST`; `Researcher` passing `mark_verified` → `ERR_FORBIDDEN`; verifying while `MISSING` → `ERR_INVALID_REQUEST` — researchers.py:74-86
- §3.4 Invitation issuance — revise — mismatch — a `SUSPENDED` researcher is also refused issuance, with `ERR_RESEARCHER_BANNED` (PRD named only `BANNED`) — invitations.py:49-52
- §3.4 Invitation respond — insert — ambiguity — expiry check leaves the invitation `EXPIRED`; responding to an `ACCEPTED`/`DECLINED` invitation → `ERR_INVALID_STATE` — invitations.py:111-118
- §3.5 Report submission — insert — ambiguity — invalid `vulnerability_class` → `ERR_INVALID_REQUEST`; `X-User-ID` not matching any registered researcher → `ERR_NOT_FOUND` — reports.py:68-72
- §3.6 Triage duplicate/reopen — insert — ambiguity — `MARK_DUPLICATE` sets `first_response_at` if null and refreshes `triaged_at`; `REOPEN` refreshes `triaged_at` — reports.py:201-205, 230-232
- §3.7 Severity — revise — ambiguity — environmental score multiplies the already-rounded `severity_score_base` (not the unrounded blend) — calculations.py:34-37
- §3.9 Award creation — insert — ambiguity — initial `block_reason` null, `withheld_cents`/`net_paid_cents` zero, `approved_at`/`paid_at` null; `capped_by_pool` always false for `BONUS`/`RETEST` — awards.py:92-107
- §3.9 Award types — insert — ambiguity — `BOUNTY` on wrong-status or `NONE`-severity report → `ERR_INVALID_STATE`; `BONUS` amount must be an integer and imposes no report-status requirement; second non-`VOID` `RETEST` → `ERR_INVALID_STATE` — awards.py:57-90
- §3.9 Approve — insert — ambiguity — approving from non-`PROPOSED` → `ERR_INVALID_STATE`; pool check is a strict-greater breach (equality passes) — awards.py:138-143
- §3.9 Pay — insert — ambiguity — paying a `PAID` or `VOID` award → `ERR_INVALID_STATE` — awards.py:156-159
- §3.9 Void — insert — ambiguity — voiding from a status other than `PROPOSED`/`APPROVED` → `ERR_INVALID_STATE` — awards.py:212-213
- §3.10 Disclosure create — insert — ambiguity — malformed `proposed_publish_at` → `ERR_INVALID_REQUEST`; `agreed_publish_at` born null; multiple disclosure requests per report allowed — disclosure_requests.py:45-57
- §3.10 Disclosure respond — insert — ambiguity — `COUNTER` carrying `agreed_publish_at` replaces `proposed_publish_at`; `DENY`/`PUBLISH` attempted by a `Researcher` → `ERR_FORBIDDEN`; `AGREE`/`DENY` source states pinned to `REQUESTED`/`UNDER_NEGOTIATION`; responses on terminal requests → `ERR_INVALID_STATE` — disclosure_requests.py:96-135
- §4 Endpoint table — insert — ambiguity — reports list filters enumerated (`program_id`, `researcher_id`, `asset_id`, `status`, `duplicate_of_id`, `scope_version_id`) — reports.py:144-148
