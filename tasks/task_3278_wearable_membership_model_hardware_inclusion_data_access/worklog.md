# Worklog — task_3278_wearable_membership_model_hardware_inclusion_data_access

## Step 1: Create Task Directory — 2026-09-30T16:44:00.000Z

Pre-allocated directory `./tasks/task_3278_wearable_membership_model_hardware_inclusion_data_access/` verified; `workspace/` exists. No new index computed (per command args).

## Step 2: Generate Scaffold — 2026-09-30T17:16:00.000Z

All three artifacts are generated, lint-clean, and verified. Final lint verdict (run after all edits):

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

### Summary

**Task**: `task_3278_wearable_membership_model_hardware_inclusion_data_access` — Whoop-style membership-included-hardware wearable platform. No sibling tasks were inspected; the design was derived purely from the scenario plus the skill spec.

**Complexity profile**: access-control matrix (consent-scoped data visibility) × event sourcing (algorithm-versioned metric reinterpretation), with optimistic concurrency, cascading side effects, dual-variant calculation, and derived-field reconciliation layers. Flat topology, cyclic state machines, peer roles, immediate consistency.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3278_wearable_membership_model_hardware_inclusion_data_access/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single `scaffold_difficulty_design` key
- `SCAFFOLD_CORNER_DESIGN.yaml` — single `scaffold_corner_design` key

**Counts**:
- **Entities: 11** — Member, MembershipTerm (plan config folded in), Device, DailyMetricSet, AlgorithmRelease, Team, TeamMembership (consent scopes embedded), ResearchStudy, ResearchEnrollment, ReplacementRequest, MerchOrder
- **Endpoints: 40** (held at the cap per the endpoint-overshoot constraint; approve/reject merged into one `decide` endpoint, fault-marking folded into replacement-request creation)
- **State machines: 9** — non-linear ones: MembershipTerm (two independent cycles ACTIVE↔PAUSED, ACTIVE↔PAST_DUE), Device (ACTIVE↔SUSPECT_FAULT diagnosis loop), DailyMetricSet (CURRENT→STALE→RECOMPUTED cycle across publishes), ReplacementRequest (branching approve/reject with divergent side effects)
- **Calculations: 9** — including dual-variant `metric_scores` (baseline v1 vs published v2+, e.g. same input → recovery 62 vs 60) and dual-variant `early_cancel_charge` (REMAINING_MONTHS 13500 vs PAID_MONTHS_FLOOR 5000 on identical term state), combinatorial `merch_order_pricing` (tier+bundle+cap, mode a) and `pause_proration_credit` (per-window rounding, mode b, pinned 66 vs 67 divergence)
- **Difficulty instances (§1.8): 18** — 2 per rule, all nine rules, with literal-computed asserts (formula values verified by executing the arithmetic)
- **Corner instances (§1.9): 32** across all nine sections (entities 6, state_machines 5, calculations 3, validations 5, endpoints 4, errors 3, rbac 3, cross_cutting 2, consistency_model 1)

**Key difficulty mechanics**: 3-hop publish cascade (release → metric recompute → member suppression → dashboard hiding), 2-hop payment-failure cascade (term PAST_DUE → member SUSPENDED → merch blocked), two OCC rules with structured `${var}` version captures, half-open pause windows vs closed device-continuity intervals (adjacency allowed vs rejected), wallet conservation invariant across merch place+cancel, and covered-days conservation across replacement swaps (stitched `end+1`). Logical clock defaults to 2026-09-01T00:00:00Z per the mandatory default rule.

## Step 3: Copy Shared Files — 2026-09-30T17:17:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T17:35:00.000Z

(Note: first subagent invocation exited with only a plan; resumed via SendMessage and it completed.)

PRD generated and verified.

**File:** `workspace/PRD.md` — 292 lines, ~6,095 words. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened.

**Section list:**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications: 2.1 RBAC (all 5 roles with identity prose), 2.2 API Response Structure (verbatim block, placeholders intact), 2.3 Pagination, 2.4 The Logical Clock (default `2026-09-01T00:00:00Z`, `to_iso8601`), 2.5 Common Resource Properties, 2.6 OCC, 2.7 Member Wallet Ledger, 2.8 Hardware Continuity Windows, 2.9 Metric Precision & Money Rounding, 2.10 Validation Evaluation Order
- §3 Business Logic: 3.1 Onboarding/Terms, 3.2 Billing & Suspension Cascade, 3.3 Pause/Resume, 3.4 Cancel/Complete, 3.5 Hardware (provision/activate/upgrade/replacement), 3.6 Ingest & Algorithm Releases, 3.7 Teams/Consent/Dashboard, 3.8 Research Studies, 3.9 Merch Commerce
- §4 Endpoint table (40 rows, 4 columns), §5 Error catalogue (27 rows, 2 columns)

**Rules emphasized:** two-variant metric formulas (baseline v1 vs published v2+, exact denominators 10.0/480 vs 9.0/450 and the ×0.9+5 recovery reshape); dual cancel-fee policies (`REMAINING_MONTHS` 50% forward-looking vs `PAID_MONTHS_FLOOR` 25% chronological, floor + half-up cents); pinned merch pricing order (per-component round, sum, 30% cap; BAND_PRO 10% gated on ACTIVE/PAUSED term); pause budget strict-greater rejection with equality allowed, and per-window rounded proration credit over 30-day cycle; closed-interval continuity overlap with same-day adjacency counting as overlap and replacement stitch at faulty end + 1 day; three-hop publish cascade (recompute → SUPPRESSED → dashboard hiding) and acknowledgement clearing posture; dashboard projection omission/suppression/per-scope null rules; de-identified contribution set with withdrawal retroactively removing rows and `member_seq` never reused; both OCC rules with exact field names and HTTP 412; validation priority ordering stated explicitly in §2.10.

**Zero-silence self-check results:**
- Contract 1 (field coverage): 84 required (80 entity fields + 45 endpoint identifiers, deduplicated), 84 present in backticks, 0 missing — PASS (9 initially missing status/FK names were patched into §3 prose and re-verified).
- Contract 2 (rule coverage): all 27 error IDs present in backticks with conditions narrated in §2/§3; all 9 state machines' transitions, preconditions, and cascades expressed; all 9 calculations translated to prose (reconstruction-safe, no pseudocode, no fuzzy words — grep confirms zero hits for approximately/conservatively/roughly/more or less); all enum/state literals verified present; both OCC rules name write endpoint + `expected_*_version` + `ERR_STALE_VERSION`/412 — PASS.
- Contract 3 (§3 path purity): 422 backtick tokens scanned in §3, 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combos — PASS.
- §4 has 40 endpoint rows matching scaffold count; roles, 201/200 conventions, and §2.2 verbatim placeholders confirmed.

## Step 5: Generate Unit Tests — 2026-09-30T17:50:00.000Z

## Summary

Generated complete test infrastructure for `task_3278_wearable_membership_model_hardware_inclusion_data_access`.

**Stage 1 — `test_helpers/` (9 files):** `types.py` (TypedDicts + enums for all 11 entities), `api_client.py` (all 40 PRD endpoints), `api_errors.py` (27 error IDs with HTTP map registered via `set_error_http_status_map`), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque shared constants + per-instance `make_member_headers`/`make_coach_headers` builders for entity-backed ownership), `fixtures.py` (composite setups: member+term, active device, metric sets, funded wallet via pause+resume, suppressed member via release publish, approved replacement, team+membership+consent), `__init__.py` barrel.

**Stage 2 — `test_suite/` (8 test files + conftest, 90 test functions):**
- `test_01_member_onboarding.py`, `test_02_billing_pause_cancellation.py`, `test_03_hardware.py`, `test_04_metrics_and_releases.py`, `test_05_teams_consent_dashboard.py`, `test_06_research_studies.py`, `test_07_merch_wallet.py`, `test_08_rbac_envelope.py`

**Coverage:** All 18 difficulty instances get ≥2 tests; all 32 corner instances (no stubs in the corner yaml) get ≥1 test. Zero instances skipped — every instance passed the PRD-first two-condition filter (the PRD is unusually tight: it names every error trigger, formula, and cascade in prose).

**Self-check results:**
- Stage 1/2 interface: all 90 tests import cleanly; `pytest --collect-only` succeeds.
- Stage-2 completeness audit (C4): every test carries exactly one verbatim `Design:` tag as the docstring's last line; all 50 tags resolve to real instances; coverage thresholds met (difficulty ≥2, corner ≥1).
- Final PRD-citation pass (C1/C2/C3): every quoted sentence in every docstring verified against PRD.md verbatim (whitespace- and backtick-normalized); four initially non-verbatim quotes were fixed (section-reference artifacts). No `skip`/`skipif`/`xfail` markers anywhere; no scaffold references in generated code comments.

One judgment call worth noting: for `Difficulty/priority_pair_validation_conflict/consent_grant_suppression_safety_beats_temporal`, the assertion relies on PRD §2.10's explicit priority ordering (suppression boundary before temporal-window rules), which the PRD states verbatim, so the error-preference test was kept as specified by the instance.

## Step 6: Generate Implementation — 2026-09-30T18:02:00.000Z

Done. Summary of the implementation for task 3278:

**Files written** (all under `workspace/implementation/`):
- `app.py` — the complete Flask server (~1050 lines), single-file design with in-memory store
- `start.sh` — foreground launcher with guarded dependency install (`if ! python3 -c "import flask"`), `exec python3 app.py`, honors `PORT` (default 10000), binds `0.0.0.0`
- `requirements.txt` — `flask>=3.0`, `python-dateutil>=2.8`

**Endpoint coverage**: all 40 endpoints from the scaffold endpoint table implemented (clock, members + sub-resources, terms incl. pause/resume/record-payment/cancel/upgrade, devices incl. activate/ingest/replacement-requests, replacement decide/receive-return, algorithm releases + publish, teams + memberships + dashboard, team-memberships + consents + remove, research studies + enroll + enrollments + contribution-dataset + withdraw, merch order placement/cancel).

**Boot verification**: booted via `bash start.sh` on `PORT=19378`, then ran two end-to-end smoke suites (~90 assertions) covering: metric score formulas v1/v2 with exact values (12.0/57/88 vs 13.3/56/93), publish cascade → SUPPRESSED posture → ack clears → consent grant blocked/unblocked, OCC 412 on consents and upgrade, pause budget boundary (exactly-at-budget allowed, +1 rejected), scheduled pause open/close via clock, early-resume proration credit (1500), merch pricing (member 10% + bundle 5%, 30% cap, debit/cancel refund invariant), suspension cascade blocking all five gated actions, replacement flow (approve → RMA_INBOUND → replacement PROVISIONED → early activate rejected with ERR_REPLACEMENT_DEVICE_NOT_RETIRED → receive-return → stitched continuity_start_on = faulty end + 1 day), continuity overlap on same-day second device, study enrollment window / member_seq / withdrawal emptying the dataset, term completion via clock, pagination meta, and the validation ordering (headers → role → ownership → 404 → 400 → 412 → state → business). A final fresh-restart confirmed the store is empty and the clock reads exactly `2026-09-01T00:00:00Z` before any `_clock` call. Afterward I killed exactly the two PIDs I started (shell + python child); port 19378 is free.

**Design decisions worth noting**:
- The logical clock is the single source of "now": created_at/updated_at and all date stamps use it (three-fractional-digit ISO), so published releases and records keep logical-consistent timestamps.
- `study_status` is computed at read/enroll time from the clock (never stored), matching the PRD's "computed, not stored as an input."
- Duplicate member email and duplicate study code are rejected with `ERR_INVALID_REQUEST` (400), since the catalog has no dedicated codes for those and they are request-validity failures.
- The upgrade endpoint returns the term plus an extra `upgrade_device` field carrying the new PROVISIONED device (scaffold requires the device be "returned in the response" but pins no shape).
- `AlgorithmRelease` carries the common-fields OCC counter as `entity_version` internally to avoid colliding with the domain `version` (algorithm version number); members still get their `version` bumped by wallet/posture mutations per PRD §2.5.

## Step 7: Run Tests and Iterate — 2026-09-30T18:00:00.000Z

All 8 rounds pass 90/90. Clean sweep achieved. (Orchestrator verified all 8 results.${i}.json show 90/90, and app.py mtime 17:56 predates sweep results 17:58 — no post-sweep impl writes.)

### Summary

- **Iterations run**: 2 (initial sweep → 2 deterministic failures → fixes → clean re-sweep).

- **Tests deleted**: none.

- **Fixes applied to `test_helpers/`**: none.

- **Fixes applied to `implementation/`** (both in `workspace/implementation/app.py`):
  1. `new_id()` — changed from `uuid.uuid4().hex` to `str(uuid.uuid4())`. PRD states "id is a server-minted UUID with no type prefix"; the dashless hex form failed the canonical dashed-UUID format check in `test_member_creation_defaults_applied_on_register` (and would have failed every other entity's UUID assertion).
  2. `open_replacement_request()` — moved the "device already has an OPEN request" check (`ERR_REPLACEMENT_ALREADY_OPEN`, 422) ahead of the device-state check (`ERR_DEVICE_NOT_ACTIVE`, 409). PRD: "A device may carry at most one OPEN request — a second attempt is rejected with ERR_REPLACEMENT_ALREADY_OPEN — and the device must be ACTIVE to begin with…". Since an OPEN request always implies the device left ACTIVE, checking device-state first would make the PRD's explicit second-attempt rule unreachable; the already-open check must win for `test_replacement_already_open_rejected`.

- **Final state**: all 8 parallel rounds pass 90/90 with per-test-server isolation; no flakiness observed.

## Step 8: Finalize PRD — 2026-09-30T18:15:00.000Z

Done. PRD_FINALIZED.md produced at `workspace/PRD_FINALIZED.md` with exactly two inline revisions, both traceable to the Step 7 diff. (Orchestrator verified the diff: exactly 2 changed lines, matching both Step 7 fixes.)

**Line counts / delta**
- PRD.md: 292 lines; PRD_FINALIZED.md: 292 lines (0% line-count delta; two sentences revised inline, no lines added or removed).

**Changes**
- §2.5 Common Resource Properties — revise — pinned `id` to the canonical dashed UUID string form (hyphens included), since impl `new_id()` returns `str(uuid.uuid4())` — `workspace/implementation/app.py:66-67`.
- §3.5 Hardware (replacement-request paragraph) — revise — added a scoped precedence clause: on `POST /devices/{id}/replacement-requests` the already-open check (`ERR_REPLACEMENT_ALREADY_OPEN`, 422) is evaluated before and wins over the device-state check (`ERR_DEVICE_NOT_ACTIVE`, 409) — `workspace/implementation/app.py:1415-1421`.

**Per-edit pre-edit search log** (truncated in hand-back; summary below reconstructed from verified diff)

Edit 1 (UUID format):
- (a) Subject: the format of the server-minted `id` property shared by all entities.
- (b) Paths enumerated: `app.py:66-67` (`new_id()`), `app.py:610` (`base_entity()` — the sole `id` minting site).

## Step 9: Complete PRD — 2026-09-30T18:30:00.000Z

The diff is 25 replaced paragraphs, all inline revisions (line count unchanged at 292). Done.

### Summary

**Source vs output:** `PRD_FINALIZED.md` 292 lines / 42,751 chars → `PRD_COMPLETED.md` 292 lines / 47,335 chars (+4,584 chars, 0 new lines — all edits are in-paragraph inserts/revisions, no new sections).

**Counts:** 17 ambiguity-pins, 0 outright mismatch-revisions (all gaps were PRD silence; several pins additionally narrow vague PRD prose to the impl's exact behavior).

**Changes (PRD section — insert|revise — ambiguity|mismatch — what — impl ref):**

- §2.3 — revise — ambiguity — pin `limit`/`offset` validation errors (non-integer, out-of-range 1–100, negative offset → `ERR_INVALID_REQUEST`) and `id`-ascending tie-break in list ordering — app.py:213-246
- §2.4 — revise — ambiguity — pin clock-set 200 response carrying `current_utc` — app.py:704
- §2.5 — revise — ambiguity — pin that `AlgorithmRelease` serializes its mutation counter as `entity_version` — app.py:509-520
- §2.9 — revise — ambiguity — pin degenerate scoring rule: `hrv_ms + resting_hr == 0` → recovery percentage 0 — app.py:319-330
- §2.10 — revise — ambiguity — state that §3 workflows may pin more specific check orderings (replacement already-open wins) — app.py:1415-1421
- §3.1 (registration) — revise — ambiguity — pin non-empty email/full_name and duplicate-email → `ERR_INVALID_REQUEST` — app.py:718-724
- §3.1 (term creation) — revise — ambiguity — pin field-type validations and suspension gate applying to `Member` callers only (PlatformAdmin bypasses) — app.py:852-870
- §3.2 — revise — ambiguity — pin `outcome` enum (`SUCCEEDED`/`FAILED` → else `ERR_INVALID_REQUEST`) and state gate for payments on non-accepting terms → `ERR_INVALID_STATE_TRANSITION` — app.py:1105-1123
- §3.3 — revise — ambiguity — pin `days ≥ 1`, `start_on` not in past → `ERR_INVALID_REQUEST`, and pause requires `ACTIVE` term → `ERR_INVALID_STATE_TRANSITION` — app.py:1015-1027
- §3.4 — revise — ambiguity — pin that cancellation clears `open_pause_end_on` and leaves recorded pause windows untouched — app.py:1151
- §3.5 (upgrade) — revise — ambiguity — pin term-open gate (`ERR_NO_ACTIVE_TERM` on terminal terms), suspension gate, and the response's extra `upgrade_device` field — app.py:1183-1212
- §3.5 (provisioning) — revise — ambiguity — pin member/term existence (`ERR_NOT_FOUND`), term-belongs-to-member (`ERR_INVALID_REQUEST`), and Member list-visibility scoping — app.py:1234-1241, 1280-1284
- §3.5 (decide) — revise — ambiguity — pin REJECT requires `diagnosis` ∈ {NO_FAULT, USER_DAMAGE} (else `ERR_INVALID_REQUEST`), closed-term approval → `ERR_INVALID_STATE_TRANSITION`, replacement inherits faulty device's tier, USER_DAMAGE recorded on device — app.py:1463-1510
- §3.6 (ingest) — revise — ambiguity — pin input types (`avg_hr`/`hrv_ms`/`resting_hr` any number; `sleep_minutes` non-negative integer) and stamped `algorithm_version` = highest PUBLISHED version — app.py:305-309, 1360-1367
- §3.6 (release) — revise — ambiguity — pin non-greater `version` → `ERR_INVALID_REQUEST` at create and at publish; non-DRAFT publish → `ERR_INVALID_STATE_TRANSITION` — app.py:1541-1575
- §3.6 (publish cascade) — revise — ambiguity — pin `id`-ascending final tie-break in recompute sweep — app.py:1591
- §3.6 (acknowledge) — revise — ambiguity — pin `algorithm_ack_release_id` always recorded; posture returns to `NORMAL` only when acknowledging the latest PUBLISHED release; unknown release → `ERR_NOT_FOUND` — app.py:764-772
- §3.7 (consent) — revise — ambiguity — pin REVOKE-without-GRANTED-entry → `ERR_INVALID_STATE_TRANSITION`, and suspension/suppression gates apply only to GRANT — app.py:1805-1816, 1830-1833
- §3.7 (dashboard) — revise — ambiguity — pin response shape `{"rows": [...]}` — app.py:1741
- §3.8 (create study) — revise — ambiguity — pin duplicate `code` → `ERR_INVALID_REQUEST` — app.py:1889-1891
- §3.8 (enroll) — revise — ambiguity — pin "current term" = ACTIVE/PAUSED, no such term → `ERR_NO_ACTIVE_TERM`, and `member_seq` never reused (count-based) — app.py:1935-1947
- §3.8 (dataset) — revise — ambiguity — pin response shape `{"rows": [...]}` — app.py:2002
- §3.9 (order placement) — revise — ambiguity — pin line validation rules → `ERR_INVALID_REQUEST` — app.py:913-929
- §3.9 (order cancel) — revise — ambiguity — pin non-PAID cancel → `ERR_INVALID_STATE_TRANSITION` — app.py:988-989

(24 paragraph edits covering the 17 pins above plus minor clarifications folded into the same paragraphs; each bullet cites the paragraph-level change.)

Output file: `workspace/PRD_COMPLETED.md`
