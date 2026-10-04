# Worklog — task_3236_community_center_membership_scholarships_program_subsidy

## Step 1: Create Task Directory — 2026-09-30T12:52:00.000Z

Pre-allocated task directory `./tasks/task_3236_community_center_membership_scholarships_program_subsidy/` verified to exist with `workspace/` inside. Used exactly this path per command args; no new index computed, no other task_* directory created.

## Step 2: Generate Scaffold — 2026-09-30T13:12:00.000Z

All three files written, lint-clean, and verified on disk.

**Files** (line counts via `wc -l`):
- `SCAFFOLD.yaml` — 1727 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1194 lines (single top-level key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1558 lines (single top-level key `scaffold_corner_design`)

**SCAFFOLD.yaml counts**:
- Entities: 14 (Association, Branch, MembershipCategory, Member, Membership, BillingDraft, ScholarshipApplication, Program, ProgramSession, Registration, FacilitySpace, FacilityReservation, Campaign, Donation)
- State machines: 7 (32 transitions; Membership has parallel status × draft_status dimensions, ScholarshipApplication has a review↔more-info cycle, ProgramSession is clock-driven, Registration has waitlist-promotion chaining)
- Calculations: 8 (incl. dual-variant sliding scale, pinned nested-rounding registration fee, interval-merge hold allowance, forward-vs-replay pool reconciliation)
- Concurrency rules: 3 (OCC on Membership approve/PATCH, Campaign close — all `expected_*_version` with `${var}` payloads)
- Endpoints: 83 (flat topology, api_prefix `""`; includes `/_clock/set_current_utc` with pinned default 2026-09-01T00:00:00Z)
- Validations: 11 priority tiers; Errors: 35; Roles: 6 (Member is entity_backed:Member, rest opaque)

**Difficulty design**: 18 instances (9 rules × 2), each with distinguishing aspects naming the required §0.5 distinction (different entity domains, different modes (a)/(b), different error-category pairs, different interval semantics, different conserved quantities).

**Corner design**: 33 instances (32 active + 1 `excluded_because` stub) across sections entities / state_machines / calculations / validations / endpoints / errors / rbac / cross_cutting_complexity_layers. All 51 instance names unique across both design files.

**Lint verdict** (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (469 calls scanned, 0 violations.)

**Notable incident**: SCAFFOLD.yaml was accidentally truncated mid-session by a failed in-place Python rewrite (`open(p,'w')` evaluated before the NameError); the file was rebuilt from scratch with the flat-topology endpoint design and re-verified end-to-end.

Orchestrator note: first subagent turn exited without writing files (design monologue only); resumed twice via SendMessage with explicit write-now instruction. Orchestrator independently verified on disk: 1727/1194/1558 lines, correct top-level keys in both design files, 83 `path:` entries in SCAFFOLD.yaml.

## Step 3: Copy Shared Files — 2026-09-30T13:25:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T13:33:00.000Z

PRD generated and verified. Summary:

**Output**: `workspace/PRD.md` — 336 lines, non-empty.

**Section list**:
- §1 Introduction (3 paragraphs)
- §2 Global Specifications: 2.1 RBAC (all 6 roles with identity prose), 2.2 Response Structure (verbatim block), 2.3 Pagination (limit 10 / min 1 / max 100 / offset 0, created_at asc), 2.4 Common Properties & Money (UUID id, ISO timestamps, version, integer cents round-half-up), 2.5 OCC (3 rules: scholarship approve + membership PATCH with `expected_membership_version`, campaign close with `expected_campaign_version`, all `ERR_STALE_VERSION`/412), 2.6 Logical Clock (2026-09-01T00:00:00Z startup, all clock-driven transitions), 2.7 Validation Priority Order (11 tiers in order), 2.8 Pool Conservation Law
- §3 Business Logic: 3.1 Association/Branch setup, 3.2 Joining & first bill (30-day join-fee waiver, prorated first draft, anniversary cap 28), 3.3 Holds/billing/delinquency/lapse/reinstate (30–180 day window, 120-day trailing allowance with interval merge, 45-day lapse, 90-day reinstate window, 3-attempt delinquency), 3.4 Sliding scale (multiplier 0.80+0.20·min(n,12), 4-decimal ratio, tiers 0.30/0.50/0.80 with exact-boundary prose, approval cascades, renewal continuity), 3.5 Programs/sessions/registrations (member-priority windows, registrant-class derivation, two-step fee rounding with 1.25 reciprocity surcharge, licensed ratio capacity, waitlist promotion with ratio skip, 48h refund forfeiture), 3.6 Facility scheduling (per-type buffers 15/30/0/0, touching-interval rule, BLACKOUT admin-only), 3.7 Campaigns/donations (match tiers 0/0.10/0.25 at 0.50/1.00 attainment, frozen-at-close, pool solvency guard), 3.8 Reciprocity
- §4 Endpoint table: all 83 endpoints, 4 columns only
- §5 Error catalogue: all 35 errors, 2 columns only

**Hard contract results** (verified programmatically):
- Contract 1 Field-Name Coverage: 98/98 required entity-field + endpoint-input names present in backticks — PASS
- Contract 2 Rule Coverage: all 8 calculations (household_multiplier, sliding_scale_award with both variants and exact boundaries, monthly_draft_amount with proration variant, registration_fee with pinned rounding order, licensed_ratio_capacity, campaign_attainment_and_match with frozen variant, hold_allowance_interval_merge, pool_available_reconciliation), all 6 state machines with every transition's preconditions and side effects, all 3 OCC rules, all 11 validation priorities in order, all 35 error IDs paired with triggers in prose — PASS
- Contract 3 §3 Path Purity: 527 backticked tokens in §3, zero starting with `/`, zero HTTP methods — PASS

Coverage of all enum values (54) and path/query parameter names (14/35) also verified present. The withheld files `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never read or referenced.

Orchestrator note: independently verified PRD.md exists at 336 lines with proper header.

## Step 5: Generate Unit Tests — 2026-09-30T14:10:00.000Z

Done. Summary of what was generated for task_3236 (Community Center Membership, Scholarships & Program Subsidy):

**test_helpers/ (9 files, 1,595 lines)**
- `types.py` (238) — TypedDicts for all 14 entities, all with the full common-field quartet (PRD §2.4 declares it for every entity; no append-only shapes)
- `api_client.py` (363) — `ApiClient(GenericApiClient)` with one method per PRD endpoint (clock, associations, branches, categories, members, memberships incl. hold/resume/cancel/reinstate/PATCH/drafts, drafts settle/fail, scholarship applications lifecycle, programs, sessions incl. close-registration/cancel/staff, registrations, spaces, reservations, campaigns, donations) plus a raw escape hatch
- `api_errors.py` (113) — all 33 PRD error IDs with HTTP statuses, registered via `set_error_http_status_map`
- `constants.py` (87) — clock startup instant, roles, sliding-scale tier ceilings, hold window/allowance bounds, draft attempt cap, lapse/reinstate windows, public-window lead, surcharge, per-type reservation buffers, campaign match tiers
- `test_users.py` (77) — opaque headers for the five non-entity-backed roles, `make_member_headers(member_id)` for the entity-backed Member role, malformed-header helpers
- `assertions.py` (120), `factories.py` (247), `fixtures.py` (263) — envelope/common-field/pool-invariant/cents/ratio assertions, payload builders, and composite fixtures (funded scholarship pool, application-under-review, approved award, REG_OPEN session scenarios, etc.)
- `__init__.py` (87) — barrel export

**test_suite/ (19 files, 2,877 lines incl. conftest)** — 68 tests total, all collected by pytest cleanly:
- Queue A (difficulty): **36 tests covering all 18/18 instances** (≥2 each)
- Queue B (corner): **32 tests covering all 32/32 non-stub instances** (≥1 each). The one `excluded_because` stub (`error_space_conflict_on_overlapping_approved_reservation` → `rental_buffer_blocks_adjacent_program_but_zero_buffer_maintenance_touches`) resolves to a real difficulty instance and was not translated, per spec.
- **Skipped instances: 0.** Every instance passed the PRD-first two-condition filter; the PRD mirrors the scaffold closely.
- **Tag audit:** every test carries exactly one `Design:` line as the final docstring line; a programmatic cross-check against both yamls found zero missing, zero unknown, zero dual-tagged, zero shortfall.
- **Citation audit:** every `PRD §x.y: "..."` quote in every docstring was grep-verified verbatim against `PRD.md` (0 failures after fixing 5 markdown/ellipsis mismatches).
- No `skip`/`skipif`/`xfail` markers anywhere.

Notable PRD-driven judgments: the terminal-state lockdown test accepts `ERR_INVALID_STATE`/`ERR_ALREADY_TERMINAL`/`ERR_REINSTATE_WINDOW_PASSED` (PRD §3.3 states both error names for terminal membership actions — two-reader ambiguity resolved via error set); the `clock_default_is_fixed_startup_instant` test asserts only a date-prefix on `created_at` (PRD pins the instant but not millisecond rendering of created_at).

Orchestrator note: independently verified on disk — test_helpers/ 9 files 1595 lines, test_suite/ 19 files 2877 lines.

## Step 6: Generate Implementation — 2026-09-30T14:15:00.000Z

All 83 endpoints are registered (the 84th is Flask's built-in `/static` handler). Done. Summary:

## Implementation complete — task_3236_community_center_membership_scholarships_program_subsidy

**Files** (all under `workspace/implementation/`):

| File | Lines |
|---|---|
| start.sh | 8 |
| requirements.txt | 1 |
| app.py | 59 |
| common.py | 267 |
| db.py | 65 |
| services.py | 373 |
| routes/core.py | 219 |
| routes/memberships.py | 417 |
| routes/scholarships.py | 255 |
| routes/programs.py | 387 |
| routes/facilities.py | 205 |
| routes/campaigns.py | 254 |
| routes/lists.py | 130 |
| **Total** | **2640** |

**Endpoints:** all 83 from the PRD endpoint table implemented (verified via Flask route map; route count 84 includes Flask's built-in `/static`).

**Key design points:**
- Pure in-memory dict store, empty at boot, no seeding; `start.sh` guards `pip install` behind an import check, runs `exec python3 app.py` on `0.0.0.0:$PORT`.
- Logical clock starts at exactly `2026-09-01T00:00:00Z`, advanced only via `POST /_clock/set_current_utc`; clock-driven transitions (hold auto-resume, session SCHEDULED→REG_OPEN→REG_CLOSED→COMPLETED, reservation COMPLETED, award EXPIRED, 45-day delinquency LAPSED) are evaluated lazily in a `before_request` hook plus on clock-set, all against the logical clock.
- Exact envelope: `meta{api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]}`, `response_type`, `data`; error envelope with `error_id`/`message`. Pagination limit/offset with defaults 10/0, min 1, max 100.
- All money in integer cents via `Decimal` + `ROUND_HALF_UP`; income_ratio rounded to 4dp half-up before tier comparison; boundary tiers (exactly 0.30→0.50, 0.50→0.25, 0.80→ineligible) implemented as `<` comparisons.
- Pool counters and campaign totals recomputed eagerly from source records (guarantees the conservation law); `match_pct`/`matched_raised_cents` frozen once campaign CLOSED.
- OCC (`expected_membership_version` / `expected_campaign_version`) checked last, per the §2.7 priority order; 412 `ERR_STALE_VERSION`.
- Waitlist promotion recomputes fee at promotion time, skips ratio-breaking candidates on licensed sessions, tie-breaks by created_at.

**Smoke test (port 18342, killed by exact PID afterward):** full chain exercised live — association/branch/category/member/membership creation with correct prorated first draft (4500 on Sep 1) and joining-fee draft; campaign activation, 500000-cent SCHOLARSHIP donation received → match_pct 0.10, matched 550000, pool received/available 500000; scholarship submitted (ratio 0.2400 → preview 0.75), reviewed, approved with OCC → obligation 40500, pool available 459500, PENDING REGULAR draft repriced to 1125; session with member-priority window opened via clock-set, `ERR_MEMBER_PRIORITY_ONLY` correctly rejected a non-member during the window, waitlisted at capacity 1, and cancel promoted the head with promotion-time non-member fee 15000. All values matched hand-computed expectations.

Orchestrator note: independently verified on disk — implementation/ has app.py, common.py, db.py, services.py, routes/{core,memberships,scholarships,programs,facilities,campaigns,lists}.py, start.sh (executable, $PORT-guarded, exec foreground), requirements.txt; 2631 total Python lines.

## Step 7: Run Tests and Iterate — 2026-09-30T14:55:00.000Z

All 8 rounds pass 67/67. Clean exit.

## Summary

**Iterations run:** 3 sweeps (8 parallel rounds each). Round 1: 60–61/68 with 8 distinct failures; Round 2: 66/67; Round 3: **67/67 in all 8 rounds**.

**Tests deleted (1):**
- `test_session_cancel_before_the_window_also_cascades` (test_difficulty_cascades.py) — unique-derivability collapse: its precondition (a SCHEDULED session holding REGISTERED/WAITLISTED registrations) is unreachable under any PRD-faithful implementation, since PRD §3.5 accepts registrations only while REG_OPEN and SCHEDULED→REG_OPEN is irreversible. PRD's "whether SCHEDULED or REG_OPEN" cascade sentence covers SCHEDULED only in the no-roster case. (Driven by scaffold instance `session_cancel_cascades_through_registrations_to_reservation` variant (b).)

**Fixes to `test_suite/` (4 tests):**
- `test_sliding_scale_household_size_alone_flips_the_tier` — test arithmetic contradicted the PRD tiers it quoted (2.4M/5M = 0.4800 is in the 0.50 tier, not 0.25). Changed income to 3,000,000: solo ratio 0.6000 → 0.25 tier, household-4 ratio 0.3750 → 0.50 tier, preserving the "size alone flips the tier" design intent.
- `test_preview_and_final_award_diverge_after_income_correction` — asserted the stale pre-resubmission preview (0.50) after PRD-mandated resubmission recompute (0.75). Now asserts recomputed preview 0.75, final award 0.75, and divergence of the original declared-income preview (0.50) from the final award (0.75).
- `test_attainment_exactly_half_takes_the_match_tier` / `test_attainment_exactly_full_takes_the_top_match_tier` — amounts 49,999/99,999 of 100,000 round to 0.5000/1.0000 under the PRD-pinned 4-decimal rounding, landing *on* the tier they claimed to be below. Changed to 49,994/99,994 (→ 0.4999/0.9999) and top-up donations of 6 cents.
- `test_hold_on_cancelled_membership_reports_state_not_allowance` — two fixes: (a) setup set the clock exactly to `hold_until`, which PRD §3.3 says auto-resumes the hold, making the manual resume fail; now sets clock one day earlier and resumes early (99 days used), keeping the allowance-overflow condition armed; (b) PRD names both `ERR_ALREADY_TERMINAL` (§3.3 "any further transition attempt on a CANCELLED membership") and `ERR_INVALID_STATE` (§3.3 hold prose) in the same §2.7 tier — relaxed the exact-error assertion to `validate_error_is_one_of([ERR_INVALID_STATE, ERR_ALREADY_TERMINAL])` per the permitted relaxation.

**Fixes to `test_helpers/`:** none.

**Fixes to `implementation/` (2):**
- `workspace/implementation/routes/programs.py` (`create_registration`) — returned `ERR_SESSION_FULL` for a hand-closed (REG_CLOSED) session; PRD §3.5: "after it closes the attempt is `ERR_REGISTRATION_WINDOW_CLOSED`, and a session already closed to the waitlist rejects with `ERR_SESSION_FULL`" — the waitlist is always expired at close, so REG_CLOSED uniquely maps to `ERR_REGISTRATION_WINDOW_CLOSED`.
- `workspace/implementation/services.py` (`refresh_session_counts`) — re-sorted the waitlist by `(created_at, id)` on every refresh; with the frozen logical clock all `created_at` tie, so random UUIDs reordered the queue between cancellation and promotion, causing flaky non-FIFO promotion. PRD §3.5: "ties broken by earliest `created_at`, never by id". Now preserves existing `waitlist_position` ordering and appends never-positioned entries at the tail in arrival order.

Orchestrator note: independently verified on disk — all 8 `results.{1..8}.json` files show 67/67 passed, 0 failed.

## Step 8: Finalize PRD — 2026-09-30T15:05:00.000Z

Done. `PRD_FINALIZED.md` written with exactly two inline revisions, both in §3.5, each tracing to one of the two `implementation/` fixes in `<step_7_diff>`.

**Line counts:** PRD.md 336 lines, PRD_FINALIZED.md 336 lines (0% delta — both edits were in-place sentence rewrites within existing paragraphs).

**Changes:**
- §3.5 (Registering a participant) — revise — replaced the "session already closed to the waitlist rejects with `ERR_SESSION_FULL`" clause: a `SCHEDULED` or `REG_CLOSED` session now uniquely maps to `ERR_REGISTRATION_WINDOW_CLOSED`, and `ERR_SESSION_FULL` is documented as never surfaced for program sessions (waitlisting at capacity is a normal outcome; the waitlist is always expired before a session is closed) — `implementation/routes/programs.py:293-298` (REG_CLOSED → ERR_REGISTRATION_WINDOW_CLOSED; `ERR_SESSION_FULL` never raised anywhere outside the `common.py:104` status map).
- §3.5 (Cancellation and promotion) — insert — added a waitlist-order stability sentence: `waitlist_position` persists until promotion/removal, roster-counter recomputation preserves existing positions and appends never-positioned entries at the tail in arrival order, and the queue is never re-sorted by `created_at` alone or by id — `implementation/services.py:146-168` (`refresh_session_counts` fixed to preserve positions instead of re-sorting by `(created_at, id)`).

**Step 7 items intentionally not patched** (pure fixture/test artifacts, no PRD silence): the deleted cascade test (precondition unreachable under any PRD-faithful impl; PRD wording already covers the reachable case), the sliding-scale arithmetic fix, the attainment rounding amounts, the preview/final divergence assertion, and the hold-on-cancelled clock/error relaxation — all match existing PRD text and impl behavior as verified in `services.py:62-103` and `routes/memberships.py:200-240`.

**Pre-edit search log:**
- Edit 1 — (a) subject: error surfaced when registering against a non-REG_OPEN session. (b) enumerated: `routes/programs.py::create_registration` lines 278-340 (all error branches: terminal → ERR_ALREADY_TERMINAL, REG_CLOSED → ERR_REGISTRATION_WINDOW_CLOSED, SCHEDULED → ERR_REGISTRATION_WINDOW_CLOSED, capacity → normal WAITLISTED outcome); repo-wide grep for `ERR_SESSION_FULL` (only the HTTP-status map, never raised); `close_registration` lines 187-204 (confirms waitlist expired at close). (c) wording scoped to explicitly carve out the at-capacity waitlist outcome so the "never surfaced" claim cannot be read as contradicting §3.5's normal-waitlisting rule.
- Edit 2 — (a) subject: waitlist ordering determination and maintenance. (b) enumerated all callsites: `refresh_session_counts` (services.py:146-168), `promote_waitlist` (services.py:216-242, sorts by `(waitlist_position, created_at)`), `create_registration` (programs.py:326, new entry gets `waitlist_count + 1`), `close_registration` (programs.py:199-201, nulls positions), `cancel_session` (programs.py:224-226), `assign_staff` (programs.py:248-256, triggers promote), `cancel_registration` (programs.py:386-387, refresh then promote). (c) wording written to cover all callsites — "any recomputation of the roster counters" rather than naming a single trigger — and to preserve (not contradict) the existing head-of-line promotion sentence it sits inside.

Orchestrator note: independently verified on disk — PRD_FINALIZED.md exists at 336 lines; diff vs PRD.md shows exactly the two §3.5 sentence revisions described above.

## Step 9: Complete PRD — 2026-09-30T15:20:00.000Z

All edits are in place. The document is complete and self-consistent.

## Summary

**Source vs output**: `PRD_FINALIZED.md` 336 lines / 54,699 chars → `PRD_COMPLETED.md` 336 lines / 60,193 chars (delta +5,494 chars, line count unchanged — all changes are in-paragraph inserts/revisions; no new sections).

**Counts**: 26 ambiguity-pins (insert), 4 mismatch-revisions (revise) across 30 edits.

**Changes** (PRD section — insert|revise — ambiguity|mismatch — what changed — impl file:line):

- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected with `ERR_INVALID_REQUEST`; list sort ties broken by `id` ascending — common.py:206-230, db.py:53
- §2.5 — revise — mismatch — the three version fields are optional; the stale check fires only when the field is supplied, omitting skips it — memberships.py:187-189, scholarships.py:226-228, campaigns.py:117-119
- §2.6 — insert — ambiguity — clock transitions evaluated lazily before every API request and on clock set; reservation completes when clock reaches or passes `end_at` — app.py:25-32, services.py:321
- §3.1 — insert — ambiguity — unresolvable body `association_id` (branch create) is generic `ERR_NOT_FOUND` — routes/core.py:88-89
- §3.2 — insert — ambiguity — Member-role joiner must be the `primary_member_id` (else `ERR_UNAUTHORIZED`); server prepends primary to `member_ids` if absent — memberships.py:93-97
- §3.2 — insert — ambiguity — joining-fee waiver window is inclusive 0–30 days; terminal date is `lapsed_on` for LAPSED and the cancellation date for CANCELLED — memberships.py:55-72
- §3.2 — insert — ambiguity — any successful PATCH re-prices PENDING drafts (not just category changes), and `JOINING_FEE` drafts are never repriced — memberships.py:190-195, services.py:135
- §3.3 — revise — mismatch — the one-draft-per-`period_month` rule constrains only the manual draft endpoint (any existing draft in the period, including activation drafts, blocks it); the two activation drafts coexist by design — memberships.py:320-323
- §3.3 — insert — ambiguity — reinstatement also clears `lapsed_on`; draft creation against CANCELLED is `ERR_ALREADY_TERMINAL`, allowed for ON_HOLD/LAPSED — memberships.py:299, 316-317
- §3.3 — insert — ambiguity — cancelling a LAPSED membership is `ERR_INVALID_STATE` (not terminal error) — memberships.py:261-262
- §3.3 — insert — ambiguity — hold from CANCELLED is `ERR_ALREADY_TERMINAL`, other non-ACTIVE states `ERR_INVALID_STATE` — memberships.py:207-210
- §3.3 — insert — ambiguity — manual resume from non-ON_HOLD is `ERR_INVALID_STATE`, from CANCELLED `ERR_ALREADY_TERMINAL` — memberships.py:237-240
- §3.3 — insert — ambiguity — reinstate window is inclusive: exactly 90 days still qualifies; reinstate from other non-terminal statuses is `ERR_INVALID_STATE` — memberships.py:282-288
- §3.4 — insert — ambiguity — Member-role filer must be the applicant (else `ERR_UNAUTHORIZED`); unresolvable `membership_id` is generic `ERR_NOT_FOUND`; `household_size` outside 1–12 is `ERR_INVALID_REQUEST`; documentation needs at least one recognized kind, extra unrecognized entries tolerated — scholarships.py:66-79
- §3.4 — insert — ambiguity — adjudication transitions on APPROVED/DENIED/EXPIRED applications are `ERR_ALREADY_TERMINAL` — scholarships.py:140-141
- §3.4 — insert — ambiguity — approval re-prices PENDING drafts excluding `JOINING_FEE` — scholarships.py:239, services.py:135
- §3.5 — insert — ambiguity — classification counts any membership whose `member_ids` roster includes the member (not only primary); member-only check enforced before priority-window check — services.py:184-196, programs.py:305-312
- §3.5 — insert — ambiguity — COMPLETED/CANCELLED session registration is `ERR_ALREADY_TERMINAL`; waitlisted registrations are created with `fee_charged_cents` null — programs.py:291-298, 328
- §3.5 — insert — ambiguity — unresolvable `program_id` on session create is generic `ERR_NOT_FOUND` — programs.py:121-123
- §3.5 — insert — ambiguity — staff ids are stored without member-registry validation; assignment allowed in any non-terminal session state — programs.py:237-257
- §3.5 — insert — ambiguity — cancelling a non-REGISTERED (incl. WAITLISTED) registration is `ERR_INVALID_STATE` — programs.py:379-383
- §3.5 — revise — mismatch — removed the 48-hour refund/forfeiture rule; the impl never moves money on registration cancellation — programs.py:384-388
- §3.6 — insert — ambiguity — `session_id`/`renter_member_id` links are optional, not type-enforced, but validated when supplied (`ERR_SESSION_NOT_FOUND` / `ERR_MEMBER_NOT_FOUND`) — facilities.py:105-110
- §3.7 — insert — ambiguity — campaign activate legal only from DRAFT (ACTIVE→`ERR_INVALID_STATE`, CLOSED→`ERR_ALREADY_TERMINAL`); close legal only from ACTIVE — campaigns.py:92-95, 112-115
- §3.7 — insert — ambiguity — donation `amount_cents` must be an integer > 0 and `designation` must be a declared value, else `ERR_INVALID_REQUEST` — campaigns.py:161-164
- §3.7 — insert — ambiguity — unresolvable `campaign_id` on donation create is generic `ERR_NOT_FOUND` — campaigns.py:154-155
- §3.7 — insert — ambiguity — receive legal only from PLEDGED (re-receive → `ERR_INVALID_STATE`, REFUNDED → `ERR_ALREADY_TERMINAL`) — campaigns.py:217-220
- §3.7 — insert — ambiguity — refund legal only from RECEIVED (PLEDGED → `ERR_INVALID_STATE`, REFUNDED → `ERR_ALREADY_TERMINAL`) — campaigns.py:236-239
- §3.8 — revise — mismatch — `reciprocity_enabled` is recorded but does not gate registration; classification/pricing follow the member record regardless — services.py:184-209 (flag never consulted)
- §4 — insert — ambiguity — list endpoints accept an exact-match `status` filter (and `designation` for donations) beyond the table; unmatched routes/methods return `ERR_NOT_FOUND` in the error envelope; `/_clock/set_current_utc` validates `current_utc`, applies transitions, and echoes it in `data` — lists.py, app.py:38-44, campaigns.py:27-38

Deliverable written to `workspace/PRD_COMPLETED.md`.

Orchestrator note: independently verified on disk — PRD_COMPLETED.md exists at 336 lines / 60,193 chars (vs PRD_FINALIZED.md 54,699 chars; +5,494 delta matches the report).
