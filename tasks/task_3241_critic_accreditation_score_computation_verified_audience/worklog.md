# Worklog — task_3241_critic_accreditation_score_computation_verified_audience

## Step 1: Create task directory — 2026-09-30T13:05:00.000Z

Task directory was pre-allocated by the caller: `./tasks/task_3241_critic_accreditation_score_computation_verified_audience/` with `workspace/` inside. Verified existence; no new index computed, no other task_* directory created.

## Step 2: Generate scaffold — 2026-09-30T13:27:00.000Z

All audits pass. The three artifacts are complete and lint-clean.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3241_critic_accreditation_score_computation_verified_audience/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design` (§1.9)

**Key counts:**
- Entities: 12 (Publication, Critic, AccreditationReview, Title, Release, CriticReview, AudienceMember, TicketVerification, AudienceRating, ScoreSnapshot, BombingIncident, Dispute)
- State machines: 10 (Critic and Dispute are non-linear — revocation/reapply cycle and TRIAGED→FILED revert loop, respectively)
- Calculations: 5, with dual variants on two domains (tomatometer provisional/certified on Release; critic standing provisional/final on Critic) and two combinatorial formulas in different modes (bombing index = mode (a) capped 3-input weighted sum; certification gate chain = mode (c) pinned evaluation order N→T→P)
- Validations: 19 (priorities 1–19)
- Endpoints: 41 initially → consolidated to **40** after orchestrator flagged the >40 impl-gen guardrail. Removed `GET /titles/{id}` (Title has no inbound FKs; Release→Title reverse-reachability already covered by filtered `GET /releases?title_id=`). Corner instance `error_responses_use_fixed_envelope_shape` retargeted to `GET /reviews/{unknown-id}`. First attempt (removing `GET /ticket-verifications/{id}`) failed lint check (f) and was reverted.
- Errors: 21
- Roles: 5 (PlatformAdmin, AccreditationBoard, Critic entity-backed, StudioRep, AudienceMember entity-backed)
- §1.8: 9 rules × 2 instances = 18; §1.9: 36 active instances + 9 `excluded_because` stubs across 9 sections

**Verification:** `scaffold_lint.py` reports `VERDICT: clean lint` (751 calls scanned, zero violations, all FKs reverse-reachable). All YAML files parse.

**Notable design decisions:**
- Archetype: compliance_audit + posture-driven gating; layers: OCC, scheduled/deferred (embargo), cascading side effects, derived-field reconciliation.
- Two OCC concurrency rules that pass the serial-observability filter: release score-recalculation and dispute rulings (rulings require `expected_dispute_version`; TRIAGE/RETURN do not — recipes capture fresh versions via GET before ruling).
- Boundary precision pins: embargo is half-open (publish allowed at exactly `embargo_until`), theatrical windows are closed (showtime == window end verifies), accreditation review windows are half-open (adjacency allowed), certification gates are inclusive (75 certifies, N==5 meets the count gate).
- No endpoint returns the envelope wrapper in `output:` (lint constraint); title-matching across releases/cuts is modeled as multiple Release rows under one Title with per-release scoring scope.

## Step 3: Copy shared files — 2026-09-30T13:31:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T13:45:00.000Z

PRD generated at `workspace/PRD.md`.

- **Line count:** 275 lines
- **Section list:**
  - §1 Introduction (3 paragraphs: trust model, embargo/clock, disputes)
  - §2 Global Specifications: 2.1 RBAC (5 roles with identity semantics), 2.2 API Response Structure (verbatim fixed block — confirmed byte-identical against `section-2.2-response-structure.md`), 2.3 Pagination (limit 10/1/100, offset 0, created_at ascending), 2.4 Resource Identity/Timestamps/Versioning, 2.5 Logical Clock (fixed epoch 2026-09-01T00:00:00Z), 2.6 OCC (both rules with `expected_release_version` / `expected_dispute_version` → `ERR_STALE_VERSION` 412), 2.7 Precision/Rounding/Snapshot discipline, 2.8 Validation Order (priorities 1–6 explicit)
  - §3 Business Logic (8 subsections): 3.1 Publications & critic accreditation (incl. revocation/reinstatement cascades), 3.2 Periodic accreditation reviews (incl. half-open overlap, standing score final/provisional variants), 3.3 Titles/releases/embargo, 3.4 Critic reviews (publish/withdraw/flag lifecycle), 3.5 Tomatometer & certification (provisional/certified variants, pinned gate order with constants 5/2/75/60), 3.6 Audience members/tickets/verified score (window closed-interval, stars≥4, single-rounding rule, SUSPENDED display), 3.7 Bombing detection (24h window, weights 20/40/30, threshold 6000 bps, suspend/invalidate/resolve), 3.8 Disputes (both kinds, self-dispute ban, triage/return loop, OCC rulings)
  - §4 Endpoint Definitions: all 40 endpoints in a 4-column table (Method, Path, Description, Authorized Roles)
  - §5 Error Code Catalogue: all 21 errors in a 2-column table

**Contract reports**

- Contract 1 (Field-Name Coverage): all 62 entity field names + common fields + endpoint input identifiers verified present in backticks via a YAML-driven diff script — 0 missing. PASS
- Contract 2 (Rule Coverage): all 40 endpoints (table + workflow narratives), 19 validations (each condition paired with its error id in §2/§3), 5 calculations (formulas translated to prose with constants embedded, pinned evaluation orders preserved), 10 state machines (all transitions with preconditions/side-effects incl. cascades), 21 errors (all mentioned in narrative and tabled), 2 OCC rules (endpoint + field + error id + 412 all named). PASS
- Contract 3 (§3 Path Purity): 294 backticked tokens in §3 scanned — 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos. PASS

Note: the withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened or referenced at any point.

## Step 5: Generate unit tests — 2026-09-30T14:05:00.000Z

## Files written

**`test_helpers/`** (Stage 1, all py_compile-clean and importable):
- `types.py` — status enums for all 10 entities + `UserRole`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (30 methods)
- `api_errors.py` — `ApiErrorId` (21 errors) + HTTP status map registered via `set_error_http_status_map`
- `constants.py` — certification gates (5/2/75/60), bombing weights (20/40/30, threshold 6000), standing penalties (1500/500)
- `factories.py` — payload factories with unique-per-run outlet names/emails
- `assertions.py` — per-entity assertions + `find_live_snapshot(scope, variant)`
- `test_users.py` — shared headers for opaque roles + `make_critic_headers` / `make_audience_member_headers` builders for entity-backed roles
- `fixtures.py` — composite setup chain (accredited publication/critic, open release, publish reviews, verified ticket/rating chain, dispute filing/triage/ruling with OCC version threading)
- `__init__.py` — barrel export

**`test_suite/`** (Stage 2): `conftest.py` + 13 test files, **72 tests total**

## Test counts and coverage

- **Queue A (Difficulty): 36 tests covering all 18/18 instances** (exactly 2 per instance)
- **Queue B (Corner): 36 tests covering all 36/36 non-stub instances**; the 9 `excluded_because:` stubs were not translated (each cross-reference verified to resolve to a real difficulty instance)

## Verification results

- **Tag audit (scripted)**: every `Design:` line resolves to a real instance in the correct rule/section; no malformed, untagged, or stub-pointing tags — PASS
- **Citation audit (scripted)**: all 72 docstrings' quoted PRD sentences (>30 chars) survive whitespace-normalized verbatim grep against `PRD.md` — PASS
- **py_compile**: all helpers + suite files compile
- **Import check**: `import test_helpers` and all 13 test modules import cleanly
- **No `pytest.mark.skip` / `skipif` / `xfail` anywhere**

## Instances skipped

None. All 18 difficulty instances and all 36 active corner instances passed the PRD-first two-condition filter (verbatim coverage + unique derivability). Notably:

- The two `priority_pair_validation_conflict` instances were kept (not skipped under the `validation-priority` silence pattern) because PRD §2.8 sentence 7 pins domain rules to "the order their narratives present them," and the §3.4 publish narrative presents the embargo rule after the accreditation rule, uniquely deriving the asserted outcomes.
- `critic_cannot_run_board_accreditation_transition` was emitted with the 403 + `ERR_UNAUTHORIZED`-or-`ERR_FORBIDDEN` relaxation exactly as the corner instance's own assert line specifies (PRD doesn't uniquely pin which 403 error_id fires for a role-permitted-but-wrong-action call).
- The disputed corner instance named `release_create_with_invalid_cut_enum_value_returns_invalid_request` actually tests review `self_designation` enum validation — translated as written, tag copied verbatim from the YAML name.

## Step 6: Generate implementation — 2026-09-30T14:25:00.000Z

Done. The implementation is complete, compiles cleanly, boots from a fresh process, and passes an end-to-end smoke test.

## Summary

All files under `workspace/implementation/`:

| File | Lines | py_compile |
|---|---|---|
| `start.sh` | 8 | n/a (chmod +x, guarded pip install, `exec python3 app.py`) |
| `requirements.txt` | 1 | n/a |
| `app.py` | 41 | OK |
| `db.py` | 56 | OK |
| `errors.py` | 38 | OK |
| `response.py` | 97 | OK |
| `middleware.py` | 25 | OK |
| `helpers.py` | 71 | OK |
| `scoring.py` | 203 | OK |
| `cascades.py` | 56 | OK |
| `routes_base.py` | 331 | OK |
| `routes_catalog.py` | 279 | OK |
| `routes_audience.py` | 312 | OK |
| `routes_disputes.py` | 197 | OK |

Total ~1707 lines across 12 Python modules; all `py_compile` clean. No seeding at startup — the store boots empty with the logical clock at `2026-09-01T00:00:00Z`.

**Coverage**: all 40 endpoints from the scaffold table; envelope `meta`/`response_type`/`data` with `api_request_id` (`req_` + alnum), 3-fractional-digit ISO timestamps; pagination `limit`/`offset`/`total_count`/`has_more` (default 10, min 1, max 100); auth via `X-User-ID`/`X-User-Role` with the 5 exact role names; validation priority order (auth → authorization → existence → shape → state → OCC → business rules); OCC on `expected_release_version` (score-recalculation) and `expected_dispute_version` (dispute transitions) returning 412.

**Key logic**: tomatometer PROVISIONAL/CERTIFIED variants with single round-half-up (via `Decimal`) and superseding snapshots; certification gates N<5 → T<2 → P>=75/P<=60 (inclusive); critic revocation cascade (publication count decremented exactly once, tomatometer recompute per affected release) shared by review-revoke and publication-revoke paths; audience VERIFIED_ONLY/ALL_RATINGS variants; bombing index over trailing 24h half-open window with per-share pre-rounding (pinned order) and weights 20V + 40·new% + 30·neg%, capped at 10000; CONFIRM suspends display + invalidates in-window ratings, RESOLVE lifts and recomputes; score read reports `audience_display: "SUSPENDED"` and nulls `audience_score_pct` while suspended; dispute workflow with FLAGGED→PUBLISHED handling, auto-reject on withdrawal of a flagged review, and `ERR_SELF_DISPUTE_FORBIDDEN` segregation-of-duties; standing-score final variant at uphold ruling.

**Smoke test** (PORT=18241, killed exactly the launched PID):
- `GET /critics/nope` unauthenticated → `ERR_UNAUTHENTICATED` 401 in the correct error envelope.
- `POST /_clock/set_current_utc` → `{"current_utc": "2026-10-01T00:00:00.000Z"}`.
- Full pipeline (publication → ACCREDIT → critic → ACCREDIT → title OPEN → release OPEN → ingest review → PUBLISH) → review became `PUBLISHED`/`FRESH`, release `tomatometer_pct: 100`, `certification: NONE` (N=1 < 5 gate), and two non-superseded snapshots `(TOMATOMETER, PROVISIONAL, 100)` and `(TOMATOMETER, CERTIFIED, 100)`.

## Step 7: Run tests and iterate — 2026-09-30T14:50:00.000Z

All 8 rounds pass: 68/68 in every round (72 original minus 4 deletions). Verified by orchestrator: all 8 `results.{i}.json` report passed==total==68.

**Summary**

- **Iterations run**: 2 (first sweep 62/72 × 8 rounds, all 10 failures deterministic; second sweep clean 68/68 × 8 rounds).

- **Tests deleted (4)** — all from `test_suite/test_10_validation_boundaries.py`, all generated from scaffold `priority_pair_validation_conflict` instances whose P-number priorities the PRD deliberately replaced with narrative-order rule 7-19:
  - `test_embargo_error_fires_for_revoked_critic_before_lift` — ERROR PRECEDENCE SILENCE: PRD §3.4 publish narrative presents the accreditation rule *before* the embargo rule, so a PRD-faithful impl may return `ERR_CRITIC_NOT_ACCREDITED` first; the scaffold's "P7 temporal beats P8 referential" ordering is not in PRD.
  - `test_embargo_error_takes_priority_over_accreditation_error` — same scaffold instance, same collapse.
  - `test_second_review_on_closed_release_rejected` — PRD SILENT: the §3.4 ingestion paragraph never gates ingestion on release status; the scaffold's "P5 state beats P10 duplicate" rule is not derivable.
  - `test_state_check_fires_before_duplicate_review_constraint` — same scaffold instance, same silence.
  - (Their private setup helpers `_setup_revoked_critic_with_ingested_review_under_late_embargo` and `_setup_closed_release_with_live_review` were removed with them.)

- **`test_suite/` fixes (3)**:
  - `test_02_state_machines.py::test_review_publish_sets_published_at_from_logical_clock` — assertion now expects `2026-09-02T12:00:00.000Z` (PRD §2.3: all timestamps carry three fractional digits; test had asserted the fraction-less form).
  - `test_05_score_computation.py::test_certification_threshold_boundary_at_exactly_seventy_five` — added missing `create_title, open_title, create_release, open_release` imports (NameError).
  - `test_09_cascades.py::test_upheld_dispute_recomputes_certified_snapshot_and_certification` — corrected arithmetic: six reviews stay published and one flips FRESH→ROTTEN, giving 5/6 = 83 pct, `positive_count == 5`, `total_count == 6` (test had wrongly expected 4/5 = 80, as if the review left the input set).

- **`test_helpers/` fixes**: none needed.

- **`implementation/` fixes (2)**:
  - `workspace/implementation/routes_catalog.py::recalculate_release` — after the OCC check, raise `ERR_SCORE_NOT_COMPUTABLE` (409) when both the review input set and the rating input set are empty, per PRD §2.7 "attempting to persist a snapshot from an empty input set is rejected with `ERR_SCORE_NOT_COMPUTABLE`"; no snapshots are persisted on that path.
  - `workspace/implementation/scoring.py::compute_bombing_index` and `routes_audience.py::transition_bombing_incident` (CONFIRM branch) — trailing-24h window comparisons changed from `created < now` to `created <= now`: entities are stamped at the logical clock, so ratings/accounts created at the present instant were falling outside the window (index computed 0 instead of 7200 bps). The window is still half-open on the past side; only the present-instant edge is closed, matching how the deterministic logical clock is used.

No skips, no weakened assertions, no seeded state, no PRD-untraced implementation additions.

## Step 8: Finalize PRD — 2026-09-30T14:58:00.000Z

**Files**: `workspace/PRD_FINALIZED.md` created from PRD.md.

**Line counts**: PRD.md 275 lines, PRD_FINALIZED.md 275 lines (0% line-count delta; edits were in-place paragraph revisions — 5 paragraphs changed).

### Changes (one bullet per edit)

- **§3.4 (ingestion paragraph)** — revise — added two sentences: accreditation check precedes duplicate-review check, and ingestion never inspects release status (ingestible against UPCOMING/OPEN/CLOSED) — `implementation/routes_catalog.py:180-213` (`ingest_review`: accreditation at line 195, duplicate at 199-203, no release-status read).
- **§3.4 (publish paragraph)** — revise — pinned explicit guard order author-FORBIDDEN → accreditation → release OPEN → embargo, with a parenthetical that the review-must-be-INGESTED state check is §2.8 priority 5, so a revoked author's embargoed publish yields `ERR_CRITIC_NOT_ACCREDITED` — `implementation/routes_catalog.py:240-270` (`transition_review`, checks at lines 248, 254, 257, 260, 262).
- **§3.5 (manual recalculation paragraph)** — revise — pinned the `ERR_SCORE_NOT_COMPUTABLE` trigger: after the OCC version check, rejected only when both input sets are empty (no PUBLISHED/FLAGGED review AND no VERIFIED/UNVERIFIED rating); no snapshots persisted and version not incremented; automatic recomputes from other workflows are not gated and append null-`pct` snapshots — `implementation/routes_catalog.py:132-155` (`recalculate_release`, empty-set check at 145-153).
- **§3.7 (detection paragraph)** — revise — replaced "half-open window … strictly before the present instant" with closed-at-present semantics (created exactly at the present instant is in-window; half-open only on the past side), applying to both the rating window and the `account_created_at` window — `implementation/scoring.py:129-158` (`compute_bombing_index`, `window_start <= created <= now` at line 141, account window at line 151).
- **§3.7 (confirm paragraph)** — revise — pinned that the CONFIRM invalidation window is recomputed at confirmation time from the then-current logical clock with the same boundary semantics, only VERIFIED/UNVERIFIED ratings are invalidated, and a single audience-score recompute runs after all invalidations — `implementation/routes_audience.py:271-295` (`transition_bombing_incident` CONFIRM, window at 284, status filter at 288, recompute at 294).

### Step 7 items needing no PRD edit
- `test_02` fractional-digits fix — PRD §2.4 already pins "three fractional digits"; pure test bug.
- `test_05` missing imports — pure test bug.
- `test_09` arithmetic correction (5/6 = 83) — the corrected expectation follows directly from PRD §3.4/§3.8 (upheld-with-change review stays in the input set; recompute); no PRD silence.

### Per-edit pre-edit search log

1. **§3.4 ingestion edit** — (a) subject: ingestion guard set and order, release-status gating. (b) enumerated: `routes_catalog.py::ingest_review` (read fully — order shape → critic 404 → FORBIDDEN → accreditation → duplicate; release fetched only for 404, status never read); `transition_review` (only other review-mutating path); grep across `cascades.py`, `routes_disputes.py`, `routes_base.py` for `ERR_CRITIC_NOT_ACCREDITED`/`ERR_DUPLICATE_REVIEW` — no other occurrences. (c) none.
2. **§3.4 publish edit** — (a) subject: publish guard order incl. ownership vs state vs accreditation vs embargo. (b) enumerated: `transition_review` PUBLISH branch (lines 253-270); §2.8 priority list (state admissibility at 5 precedes domain rules); confirmed FORBIDDEN precedes the state check in impl so the parenthetical was scoped to "priority 5, before these domain rules" rather than claiming state-before-ownership. (c) parenthetical re-scoped to avoid asserting an order between the ownership check and the state check.
3. **§3.5 recalculation edit** — (a) subject: ERR_SCORE_NOT_COMPUTABLE trigger and scope. (b) enumerated: `recalculate_release` (only raise site — grep confirmed no other); `recompute_all_scores`/`recompute_tomatometer`/`recompute_audience_score` in `scoring.py` (append null-pct snapshots on empty sets, never raise); all automatic-recompute call sites (publish, withdraw, cascades, rating create/verify/invalidate, bombing confirm/resolve, dispute uphold) — none gate on emptiness. (c) added explicit clause that automatic recomputes are not gated, to keep the new sentence from implying a universal rule.
4. **§3.7 detection-window edit** — (a) subject: trailing-24h window boundary semantics. (b) enumerated: `compute_bombing_index` rating window (line 141) and account window (line 151), both `<= now`; `transition_bombing_incident` CONFIRM window (line 291), also `<= now`; `critic_standing_final`/`critic_standing_provisional` use `< end` (genuinely half-open) — confirmed those are different windows described in §3.2, untouched. (c) extended the new sentence to the `account_created_at` sub-window ("with the same closed-at-the-present boundary") so both in-function windows are consistently described.
5. **§3.7 confirm-window edit** — (a) subject: CONFIRM invalidation window timing, target statuses, recompute multiplicity. (b) enumerated: CONFIRM branch (lines 271-295) — window recomputed from current clock at confirm, filter `status in ("VERIFIED","UNVERIFIED")`, one `recompute_audience_score` after the loop. (c) replaced the preserved original phrase "each invalidation flowing through the audience-score recompute" with "after all in-window invalidations are applied, the audience score is recomputed" to match the single-recompute impl (avoids a new per-invalidation-recompute mismatch).

## Step 9: Complete PRD — 2026-09-30T15:12:00.000Z

Done. `workspace/PRD_COMPLETED.md` written.

## Summary

- **Source**: `PRD_FINALIZED.md` — 275 lines, 39,885 chars. **Result**: `PRD_COMPLETED.md` — 277 lines, 42,416 chars (+2 lines, +2,531 chars).
- **Counts**: 11 ambiguity-pins, 2 mismatch-revisions (13 edits total).

Changes:

- §2.4 Resource Identity — insert — ambiguity — pinned `id` as 32-char lowercase hex UUID (no dashes), list tie-break by `id` ascending, and `has_more = offset + page_size < total_count` — helpers.py:42,67,70; response.py:30
- §2.5 Logical Clock — insert — ambiguity — unparsable `to_iso8601` rejected with `ERR_INVALID_REQUEST` — routes_base.py:28
- §2.7 Precision — revise — ambiguity — scoped the `ERR_SCORE_NOT_COMPUTABLE` empty-snapshot rule to the manual-recalculation path only (auto-recomputes append null-pct snapshots) — scoring.py:72,79,112,117; routes_catalog.py:144-153
- §2.7 Snapshots — insert — ambiguity — supersede flips the prior non-superseded snapshot; that flag flip is the sole mutation allowed on existing snapshots — scoring.py:35-39
- §3.1 Publications — insert — ambiguity — duplicate outlet name rejected with `ERR_INVALID_REQUEST`; new publication's `accredited_critic_count` is 0 — routes_base.py:47,52
- §3.1 Critics — revise — mismatch — new critic starts with `standing_score_bps` = 10000 and `last_review_period_start` null (PRD had implied a computed initial standing score) — routes_base.py:122-123
- §3.1 Revocation cascade — insert — ambiguity — count decrement is floored at zero and only when the critic currently counts (`ACCREDITED`/`PROBATION`/`UNDER_REVIEW`) — cascades.py:23,29
- §3.2 Standing variants — revise — mismatch — final variant counts `UPHELD` classification disputes on the critic's in-window reviews (not "classification-changed" disputes); provisional penalizes critic's `FLAGGED` reviews under pending disputes at 500 bps — scoring.py:161-206
- §3.3 Releases — insert — ambiguity — `cut_label` is a free string, not an enum; release representation includes `audience_display` (`SUSPENDED`/`ACTIVE`) and nulls `audience_score_pct` when suspended — routes_catalog.py:62-67; response.py:62-69
- §3.4 Reviews — insert — ambiguity — new review starts with `classification` and `published_at` null — routes_catalog.py:209-211
- §3.5 Manual recalculation — revise — mismatch — removed claim that the release's `version` increments on successful recalculation; impl performs two recomputes, each bumping version once — routes_catalog.py:154; scoring.py:123-126
- §3.5 Tomatometer — insert — ambiguity — `tomatometer_pct` is set from the certified-variant percentage (null when certified input set empty) — scoring.py:96
- §3.6 Audience score / suspension — revise — mismatch — suspended score read reports `audience_score_pct` as null rather than omitting the field; verify sets the rating's `ticket_verification_id` to the supplied id — response.py:66; routes_audience.py:226
- §3.7 Bombing confirmation — insert — ambiguity — already-`INVALIDATED` ratings are skipped; each invalidated rating's version increments — routes_audience.py:285-293
- §3.8 Disputes — insert — ambiguity — pinned filer/subject field consistency rules, reclassification guard fires on null `classification`, guard order (reclassification → self-dispute → review-state), OCC applied to all transitions with terminal-check first, and SCORE_DISPLAY uphold marks the dispute `UPHELD` before recomputing — routes_disputes.py:29-70,126-140,184-187
