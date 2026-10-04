# Worklog — task_3277_child_device_monitoring_alerts_parent_escalation

## Step 1: Create task directory — 2026-09-30T16:41:00.000Z

Pre-allocated task directory `./tasks/task_3277_child_device_monitoring_alerts_parent_escalation/` with `workspace/` verified to exist; used as-is per command args (no new index computed, no other task_* directory created).

## Step 3: Copy shared files — 2026-09-30T17:21:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 5: Generate unit tests — 2026-09-30T18:05:00.000Z
Orchestrator verified on disk: test_helpers/ (9 modules + __init__), test_suite/ (13 test files + conftest), 77 `Design:` tags total, all files compile, zero skip/xfail markers. Verbatim subagent summary:

All done. Summary of what was generated for task_3277_child_device_monitoring_alerts_parent_escalation:

**Files written**

`test_helpers/` (9 files, absolute paths under `/home/ubuntu/github/CodingPRD/tasks/task_3277_child_device_monitoring_alerts_parent_escalation/test_helpers/`):
- `types.py` — 14 entity TypedDicts + 20 status/role enums (all entities carry the full common field set per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (32 methods)
- `api_errors.py` — all 24 error IDs with HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` helpers; `assert_connection` additionally refuses `credential_token` in serialized responses
- `factories.py` — payload factories for all creatable entities
- `constants.py` — domain thresholds (score cap 100, severity mins 85/60/30, excerpt caps 140/70, pricing 999/1999/2999, device limits 2/5/10, 14-day strike window, 24h SLA, 5-minute grant pad)
- `test_users.py` — shared headers for the opaque `PlatformAdmin` role plus per-instance builders `make_parent_headers` / `make_school_admin_headers` / `make_device_agent_headers` for the three entity-backed roles
- `fixtures.py` — composite helpers: `create_family` (family + auto-created primary parent), `setup_monitoring_pipeline`, `setup_alert`, `setup_severe_alert_with_case`, `setup_active_district_link`, `report_bypass_events`, `create_grant`, `set_clock`, etc., all identity-threaded with entity-backed headers
- `__init__.py` — barrel export

`test_suite/` (13 test files + `conftest.py`), 77 tests total:
- test_01 family onboarding (2), test_02 children (6), test_03 connections (5), test_04 devices (10), test_05 content/risk scoring (5), test_06 severity/excerpts (3), test_07 alert workflow (9), test_08 escalation cases (8), test_09 bypass/posture (7), test_10 windows/grants (7), test_11 subscription/proration + OCC (4), test_12 RBAC/scope (8), test_13 envelope/pagination (3)

**Coverage audit (mechanically verified with a script against both yamls)**
- 18/18 difficulty instances translated, each with >=2 tests (2 tags per instance; the third-test cases land where a difficulty and a corner instance share a recipe)
- 41/41 active corner instances translated, each with >=1 test
- 6 `excluded_because` stubs NOT translated; their cross-references all resolve to real difficulty instances (the space-separated `"rule_id / name"` format in the yaml is cosmetic)
- Every emitted test carries exactly one `Design:` tag (AST audit), all 77 tags resolve to real instances, no skip/xfail markers anywhere, all files compile
- Verbatim PRD citations spot-checked with `grep -F` against `workspace/PRD.md` (9 distinctive phrases, all matched)

**Skips / weakening decisions**
- No instances were skipped outright. Two were translated in relaxed form to satisfy the two-reader rule: `error_district_suspended_blocks_consent` (PRD declares no district-suspension endpoint, so the suspended-district leg cannot be exercised through the API — the test asserts the consented baseline plus `consented_at` stamping, cited to the §3.13 consent rule), and `scope_violation_beats_state_returns_403` (asserts scope fires rather than hard-coding which check fires first).
- No concurrency race tests were emitted (PRD §2.6 explicitly scopes OCC to the two guarded endpoints only); both OCC instances were translated as sequential stale-version tests per the silence-pattern rule.

## Step 6: Generate implementation — 2026-09-30T18:35:00.000Z

Orchestrator verified on disk: workspace/implementation/ contains start.sh (bash syntax OK), requirements.txt, app.py, db.py, errors.py, response.py, middleware.py, calculations.py, services.py, and routes/ (9 modules); all Python files parse. Verbatim subagent summary:

Done. Implementation complete and verified.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3277_child_device_monitoring_alerts_parent_escalation/workspace/implementation/`):

- `start.sh` — guarded install (`if ! python3 -c "import flask"`), `exec python3 app.py`, PORT/0.0.0.0
- `requirements.txt` — flask>=3.0,<4.0
- `app.py` — entry point, blueprint registration, ApiError + 404/405 handlers
- `db.py` — in-memory Store (14 collections, starts empty) + logical Clock (default `2026-09-01T00:00:00Z`, never wall-clock), ISO8601 parse/format with 3 fractional digits
- `errors.py` — all 24 catalog error IDs with exact HTTP statuses
- `response.py` — envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), list meta (`limit`/`offset`/`total_count`/`has_more`), pagination parsing (default 10, min 1, max 100)
- `middleware.py` — auth (X-User-ID/X-User-Role, 4 roles), role gating, Parent cross-family scope, SchoolAdmin district scope + severity visibility, DeviceAgent identity
- `calculations.py` — risk scoring (both variants, Decimal ROUND_HALF_UP), severity classification (base level + age/sensitivity deltas + category floor, clamp 1-4), excerpt truncation (140/70 cap, cut at last space + U+2026), proration (per-day rounded first, then × remaining days), strike window (14d inclusive), device limits, age bands, crisis codes
- `services.py` — entity factory, serializers (credential_token never serialized), counter/posture/grant/overdue recomputation, clock-advance sweep
- `routes/families.py`, `children.py`, `connections.py`, `devices.py`, `content.py`, `escalations.py`, `districts.py`, `clock.py`

**Endpoints implemented: all 42** from the scaffold endpoint table.

**Verification:** booted on port 18723/18724 and smoke-tested (not the pytest suite): family+primary-parent creation with billing period, child age-band derivation, OCC 412 on stale versions for both guarded writes, connection consent cycle incl. re-consent and duplicate detection, device limit enforcement, unpair terminal state, bypass strikes → BYPASS_WATCH → LOCKDOWN with grant cancellation, clock-advance auto-heal to NORMAL, full SEVERE flow (alert + escalation case + district link pending_legal_report + 24h due date + overdue flag), legal report role restriction and obligation count, CRISIS close blocked while report pending, SEVERE resolve guard, IMMEDIATE vs DIGEST feed, SchoolAdmin severity/district scoping, cross-family 403, window overlap with adjacency allowed, padded grant conflict, proration (990 cents verified: (100−67)×30), excerpt caps, suspension gating, auth/not-found errors, pagination meta.

**PRD interpretation decisions:**
- Same-state `to_status` on family/window/connection transitions → `ERR_INVALID_STATE` (not a listed edge).
- DeviceAgent scoping for content ingest: `X-User-ID` must be a Device of the connection's child (PRD pins the identity match only for bypass reporting).
- SchoolAdmin identity validity for link creation is implicit in `X-User-ID == district_id`.
- Counter recomputation bumps `updated_at` but not `version` (only scaffold-declared transitions increment version).
- Non-existence of the parent identity on scoped endpoints → `ERR_CROSS_FAMILY_ACCESS`.

## Step 7: Run tests and iterate — 2026-09-30T19:15:00.000Z

Orchestrator independently verified on disk: all 8 `results.{i}.json` files show passed=77 total=77 failed=0; all results files are newer than every .py in test_suite/, test_helpers/, and workspace/implementation/ (no post-sweep writes); 77 Design tags intact; zero skip/xfail markers. Verbatim subagent summary:

Clean 8-round parallel sweep: 77/77 in all 8 rounds.

**Summary**

- Iterations run: 3 sweeps (initial diagnostic sweep → fix round 1 → fix round 2 → final clean sweep).
- Tests deleted: none. All 9 initially failing tests traced to PRD-verbatim rules; the failures were test-artifact bugs, not coverage gaps.
- Fixes applied to `test_helpers/`:
  - `fixtures.py` `setup_alert()` — now forwards extra kwargs (e.g. `direction`) to `ingest_content`; `test_alert_resolve_reopen_count_conservation` passed `direction="OUTBOUND"`, which raised `TypeError` (PRD §3.5 declares `direction` a request field, so the helper dropping it was a factory bug).
  - `fixtures.py` `report_bypass_events()` — event `detected_at` values were generated at +0/+5/+10 minutes after the default clock (`2026-09-01T00:00:00Z`), which is the future relative to the logical clock and correctly rejected per PRD line 83/§3.11. Events are now spaced backwards, ending exactly at the default clock (inclusive-edge semantics preserved; the 14-day-boundary test that consumes this helper still passes).
- Fixes applied to `test_suite/`:
  - `test_06_severity_and_excerpts.py::test_excerpt_truncation_word_boundary_and_teen_cap` — child B (OLDER_TEEN + LENIENT + BULLYING weight 40) classifies as LOW after the PRD §3.6 leniency adjustment, so no alert exists to hold an excerpt (PRD §3.7: alerts are created only at MODERATE+). Raised child B's signal weight to 60 → HIGH base → LENIENT −1 → MODERATE; the cap-70 truncation assertion is unchanged and still pins the PRD formula.
  - `test_07_alerts_workflow.py` (3 sites) — `occurred_at` values of `2026-09-01T00:05/10Z` are in the future relative to the default logical clock; changed to `2026-09-01T00:00:00Z` (not in the future; feed assertions unaffected since the feed sorts by server-minted `created_at`, not `occurred_at`).
  - `test_07_alerts_workflow.py::test_alerts_filtered_by_status` — asserted `alert_status=RESOLVED` returns the resolved alert, contradicting PRD §3.9 "Both variants exclude `RESOLVED` alerts entirely". Rewrote to assert the RESOLVED filter yields an empty feed and added a DELIVERED-status narrowing check to keep positive coverage of the `alert_status` parameter.
  - `test_08_escalation_cases.py::test_severe_alert_escalation_district_cascade` — asserted the deadline string exactly `"2026-09-02T00:00:00Z"`, but PRD pins three-fractional-digit formatting only for envelope/entity `created_at`/`updated_at` (lines 48/81); for `legal_report_due_at` it pins only "exactly 24 hours after the case's `created_at`" and "second-exact" arithmetic (lines §3.8/87) — a format-string assertion was not uniquely derivable. Now asserts ISO8601 validity plus parsed-instant equality `due == created_at + 24h`, which is the verbatim PRD rule.
- Fixes applied to `implementation/`: none. Every failure was a test-side inconsistency with the PRD; the implementation (including its strict future-timestamp rejection and RESOLVED-exclusion feed) was PRD-faithful throughout.

## Step 8: Finalize PRD — 2026-09-30T19:40:00.000Z

Step 8 ran (Step 7 had 2 test_helpers + 5 test_suite fix sites, so the skip condition did not apply). Orchestrator verified on disk: PRD_FINALIZED.md exists, 298 lines, and `diff` against PRD.md shows exactly one inline revision at line 81 (§2.4 timestamp-format sentence). Verbatim subagent summary:

Done. PRD_FINALIZED.md is written with exactly one inline revision.

**Line counts:** PRD.md = 298 lines, PRD_FINALIZED.md = 298 lines (0% line-count delta; one sentence appended inline to an existing line, ~10% character delta on that line only).

**Changes (one edit total):**
- §2.4 — revise — appended a sentence pinning that every server-emitted timestamp (server-computed fields like `billing_period_start`, `billing_period_end`, `consented_at`, `legal_report_due_at`, `legal_report_filed_at`, and echoed client instants like `occurred_at`, `detected_at`, `start_at`, `end_at`) is serialized in ISO 8601 UTC with three fractional digits and a `Z` suffix — implementation/db.py:42-48 (`fmt_iso`), with all write sites normalizing through it (implementation/routes/content.py:78,126; routes/devices.py:178,235-236; routes/districts.py:135; routes/escalations.py:143; routes/families.py:58-59; routes/clock.py:23).

**Why only one edit:** of the six step_7_diff items, five trace to behavior the PRD already uniquely determines (§3.5 `direction` field, §2.4/§3.11 no-future-timestamp rejection, §3.6 severity adjustments + MODERATE+ alert creation, §3.9 RESOLVED-excluded-entirely feed semantics) — those were pure test/fixture bugs fixed toward the PRD, so no PRD patch is warranted. Only the test_08 deadline-format weakening revealed a genuine PRD silence (impl formats `legal_report_due_at` via `fmt_iso`; PRD previously pinned the 24h arithmetic but not the wire format).

**Per-edit pre-edit search log:**
- (a) Subject: serialization format of all timestamp fields emitted in responses (triggered by the `legal_report_due_at` format fix).
- (b) Paths enumerated and read/grepped: `implementation/db.py` (`fmt_iso`, `parse_iso`); every `fmt_iso` callsite across `services.py` (created_at/updated_at mint/bump), `response.py` (envelope `api_request_timestamp`), `routes/clock.py`, `routes/content.py` (occurred_at echo, due_at), `routes/districts.py` (consented_at), `routes/escalations.py` (legal_report_filed_at), `routes/devices.py` (detected_at echo, grant start_at/end_at), `routes/families.py` (billing period); plus all serializer functions in `services.py` to confirm no timestamp field bypasses `fmt_iso` (all read stored, pre-normalized values).
- (c) Wording adjustment: initial draft considered naming only `legal_report_due_at`; widened to a universal statement covering all emitted timestamps after the enumeration showed every emitted timestamp goes through the single `fmt_iso` formatter, so the universal claim is consistent with every enumerated path (and matches §2.2's existing three-fractional-digit requirement on `api_request_timestamp`). No enumerated path is mis-described.

The "context only" interpretation decisions listed in the diff summary (same-state → ERR_INVALID_STATE, DeviceAgent/SchoolAdmin identity bindings, counter recomputation version semantics, unknown-parent → ERR_CROSS_FAMILY_ACCESS) were not touched, per instructions, since no step_7_diff fix item leads to them.

## Step 9: Complete PRD — 2026-09-30T20:00:00.000Z

Step 9 ran from PRD_FINALIZED.md (which existed). Orchestrator verified on disk: PRD_COMPLETED.md exists, 298 lines / 47,671 chars (+5,136 chars vs FINALIZED, all in-paragraph edits); `find` confirms no .py file in test_suite/, test_helpers/, or workspace/implementation/ is newer than the clean-sweep results files — the 77/77 × 8-round sweep remains valid. Verbatim subagent summary:

Done. Summary:

**Files:** `workspace/PRD_FINALIZED.md` (298 lines, 42,535 chars) → `PRD_COMPLETED.md` (298 lines, 47,671 chars); char delta +5,136, no lines added or removed (all edits are in-paragraph).

**Counts:** 17 ambiguity-pins, 1 mismatch-revision (the acknowledge-side-effect broadening; several other edits mix both but were classified by dominant character).

**Changes:**
- §2.1 Parent bullet — insert — ambiguity — unresolved/inactive ParentMember identity: scoped endpoints → ERR_CROSS_FAMILY_ACCESS, `/api/alerts` and `/api/escalation-cases` lists → ERR_FORBIDDEN_ROLE — middleware.py:46-56, routes/content.py:200-205, routes/escalations.py:61-65
- §2.1 SchoolAdmin bullet — insert — ambiguity — X-User-ID must equal path district id on district read/list/create-link → ERR_CROSS_DISTRICT_ACCESS — routes/districts.py:53-54,63-64,92-93
- §2.1 DeviceAgent bullet — insert — ambiguity — ingest identity = a Device of the connection's child; both identity mismatches → ERR_FORBIDDEN_ROLE — routes/content.py:31-34, routes/devices.py:160-161
- §2.3 — insert — ambiguity — non-integer/out-of-range limit/offset → ERR_INVALID_REQUEST; created_at ties broken by id in sort direction — response.py:45-66, services.py:372-378
- §2.4 — insert — ambiguity — clock set accepts any instant (forward or backward), missing/unparsable to_iso8601 → ERR_INVALID_REQUEST, response data `{"now": ...}` — routes/clock.py:12-23
- §2.6 — insert — ambiguity — expected-version fields non-optional integers; missing/non-integer → ERR_INVALID_REQUEST — routes/families.py:110-114, routes/children.py:90-94
- §2.8 — insert — ambiguity — counter/derived-field recomputation refreshes updated_at without incrementing version — services.py:29-31 (bump), 269-368
- §3.2 — insert — ambiguity — archive cascade increments each revoked connection's version; archived-terminal covers any passing child update — routes/children.py:96-97,124-131
- §3.2 — insert — ambiguity — connection create, filter-rule create, and device pair on archived child → ERR_CHILD_ARCHIVED; non-ARCHIVED profile_status in update → ERR_INVALID_STATE — routes/children.py:155-156,207-208,264-265,105-110
- §3.4 — insert — ambiguity — same-state to_status → ERR_INVALID_STATE; unrecognized to_status → ERR_INVALID_REQUEST; convention applies to all state ops — routes/connections.py:61-66, routes/families.py:91-94, routes/devices.py:135-139, routes/districts.py:112-121
- §3.5 — insert — ambiguity — ingest validation ordering: connection existence, then DeviceAgent identity, then payload, then connection-active/family-suspended — routes/content.py:24-65
- §3.8 — insert — ambiguity — escalation case list supports alert_id/child_profile_id/case_status filters; invalid case_status → ERR_INVALID_REQUEST; scope by filtering with cross-scope error on explicit child filter — routes/escalations.py:50-92
- §3.9 — revise — mismatch — case advance to GUIDANCE_ISSUED happens on any acknowledge transition (including REOPENED→ACKNOWLEDGED) while case is OPEN, not only from DELIVERED — routes/content.py:274-278
- §3.9 — insert — ambiguity — invalid variant/alert_status → ERR_INVALID_REQUEST; feed tiebreak by id descending; list scope enforced by filtering; explicit out-of-scope child_profile_id → cross-scope error — routes/content.py:187-247
- §3.10 — insert — ambiguity — window creation requires device PAIRED → ERR_DEVICE_NOT_PAIRED — routes/devices.py:84-85
- §3.12 — insert — ambiguity — grant creation requires PAIRED (checked before LOCKDOWN); grants re-evaluated against the clock immediately at creation so response may be ACTIVE/EXPIRED — routes/devices.py:207-210,241
- §3.13 — insert — ambiguity — link creation permitted against archived child; no duplicate-link prevention; identity pin cross-referenced — routes/districts.py:58-84
- §3.14 — insert — ambiguity — same-tier change permitted with zero charge; remaining days floored at zero past period end — routes/families.py:115-129, calculations.py:97-103
- §3.15 — insert — ambiguity — same-state family to_status → ERR_INVALID_STATE — routes/families.py:93-94

## Step 4: Generate PRD — 2026-09-30T17:30:00.000Z

Orchestrator verified `workspace/PRD.md` exists (298 lines). Verbatim subagent summary:

All checks pass. The PRD is complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3277_child_device_monitoring_alerts_parent_escalation/workspace/PRD.md` — 298 lines.

**Sections:**
- §1 Introduction (3 paragraphs, domain context angle)
- §2 Global Specifications: 2.1 Roles & RBAC (4 roles, identity prose, scope errors), 2.2 Response Structure (verbatim fixed block), 2.3 Pagination (limit 10/1/100, offset 0, created_at ascending, meta fields), 2.4 Common Properties & Logical Clock (UUID id, ISO 8601 3-fractional-digit timestamps, version, 2026-09-01 clock seed), 2.5 Precision & Rounding, 2.6 OCC (both rules with `expected_child_version`/`expected_family_version`, `ERR_STALE_VERSION` 412), 2.7 Nested Retrieval (left-to-right), 2.8 Derived Counters & Reconciliation, 2.9 Privacy Surface (excerpts not logs, `credential_token` write-only)
- §3 Business Logic: 15 subsections covering onboarding, child tuning/archival, device pairing/limits, connection consent lifecycle, content ingestion & risk scoring (both variants, constants 100/0.05/5), severity classification (thresholds 85/60/30, floors, age/sensitivity deltas, tie-breaking), excerpt truncation (140/70 caps), escalation cases & legal reporting (resource codes, 24h SLA, earliest `consented_at`, overdue), alert lifecycle & feed variants, screen-time windows & filters, bypass/posture/lockdown (14-day inclusive window, thresholds 1/3, grant cancellation), access grants (5-minute padded conflict), districts/links, subscription proration (pinned rounding order, 999/1999/2999, 30-day period), family suspension
- §4 Endpoint table (42 endpoints, 4 columns only)
- §5 Error catalogue (24 errors, 2 columns only)

**Contract reports:**

```
Field coverage check:
- entities[].fields: all present (verified mechanically over all 74 field names)
- endpoints[].request_body / input: all present (to_iso8601, to_status, new_tier, expected_*, variant, etc.)
- endpoints[].query_params: limit, offset, variant, child_profile_id, content_item_id, alert_status, alert_id, case_status — present
Status: PASS

Rule coverage check:
- validations[] priority order: expressed (§2.6 states OCC ordering after auth/authz/existence/scope, before state/business)
- concurrency_rules[]: 2/2 expressed (write endpoint framing + occ field + ERR_STALE_VERSION + 412)
- state_machines[].transitions: all 9 machines' transitions expressed (Family 2, Child 1, Device pairing 1, posture 4, Connection 6, Alert 5, Case 7, Window 2, Grant 5, DistrictLink 3)
- calculations[]: 9/9 expressed (risk scoring both variants, severity ladder with floors/clamp, excerpt truncation, proration pinned rounding, feed variants, strike window inclusive edges, device limits 2/5/10, open alert invariant, legal deadline + tie-break, age bands)
- validations[] conditions: all error ids paired with trigger prose in §2/§3
- endpoints[].side_effects: cascades (archive → revoke connections, lockdown → cancel grants, acknowledge → guidance, legal filing → clear pending + decrement obligation) all expressed
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: all
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Every scaffold rule — error ids, state machines, calculations (with constants and pinned rounding order), validations, OCC rules, and side-effect cascades — appears as verbatim-derivable prose in the PRD. The withheld difficulty/corner design files were never read.

## Step 2: Generate scaffold — 2026-09-30T17:20:00.000Z

Note: first subagent invocation exhausted its output budget mid-reasoning (zero files written); resumed the same agent (its design context intact) with a chunked-write protocol (Write for first chunk, then one ~100-200 line Bash heredoc append per message), which completed all three files. Orchestrator verified all three parse as YAML and SCAFFOLD.yaml contains neither design key.

Verbatim subagent summary:

All checks pass. Final summary:

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3277_child_device_monitoring_alerts_parent_escalation/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`, 18 instances (2 per each of the 9 rules)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`, 47 instances (41 active + 6 `excluded_because` stubs citing §1.8 instances)

**Counts**: 14 entities, 42 endpoints, 24 error codes, 10 calculations, 10 state machines, 2 OCC concurrency rules, 4 roles (PlatformAdmin opaque; Parent→ParentMember, SchoolAdmin→District, DeviceAgent→Device entity-backed).

**Lint**: `scaffold_lint.py` reports `VERDICT: clean lint` (438 calls scanned, 0 violations); all instance names unique across both design files; no forbidden concurrency vocabulary.

**Notable design decisions**:
- Archetype: compliance/audit primary + posture-driven gating secondary; flat topology with FK-linked peers; cyclic state machines (Alert resolve↔reopen; ServiceConnection pause/resume/re-consent).
- Deterministic dual-variant risk scoring: LEXICAL_V1 (sum of weights) vs CONTEXTUAL_V2 (thread-depth multiplier) pinned per family, with exact literals (55 vs 63).
- Severity classification is a 4-input clamped formula (score tier + age-band delta + sensitivity delta vs category floor) — a CHILD_9_UNDER/STRICT/BULLYING item at score 55 lands SEVERE.
- Proration pins round-per-day-then-multiply (STANDARD→PREMIUM, 7 days = 231 cents).
- Two distinct interval semantics for Rule 8: half-open adjacent-allowed screen-time windows vs padded closed-interval (±5 min buffer) access grants.
- Privacy surface: raw ContentItems are PlatformAdmin-only; parents get word-boundary-truncated excerpts (140 chars, 70 for OLDER_TEEN+LENIENT); SchoolAdmin visibility gated to HIGH/SEVERE alerts on district-linked children.
- Clock endpoint `POST /api/_clock/set_current_utc` with the mandated default `2026-09-01T00:00:00Z`, driving strike-window decay, grant expiry, and legal-report overdue flags.
- One known soft spot: `ERR_DISTRICT_SUSPENDED`'s consent-time guard is documented in the DistrictLink state machine, but no public district-suspend endpoint exists, so the corner instance asserts the baseline path and notes the dependency (kept the error for spec completeness rather than inventing an endpoint the scenario doesn't motivate).
