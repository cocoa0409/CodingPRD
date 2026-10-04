# Worklog — task_3062_credit_monitoring_score_simulation_pre_qualified_offer

Scenario: Credit Monitoring, Score Simulation & Pre-Qualified Offer Matching (Credit Karma).

## Step 1: Create task directory — 2026-09-30T00:00:00.000Z

Task directory `./tasks/task_3062_credit_monitoring_score_simulation_pre_qualified_offer/` was pre-allocated by the caller with `workspace/` already created. Verified existence; no new index computed and no other `task_*` directory created.

## Step 2: Generate scaffold — 2026-09-30T00:05:00.000Z

All three files are written, parse cleanly, and the lint reports a clean verdict.

## Files written

| Path | Lines |
|---|---|
| `SCAFFOLD.yaml` | 2653 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1298 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 1921 |

## Inventory

**Entities (21):** Consumer, BureauSnapshot, ScoreFactorExplanation, ScoreAlert, ScoreSimulation, ProductCatalogItem, Lender, LenderProgram, TargetingCriterion, PreQualificationDecision, ConsentRecord, Referral, DisputeReferral, RevenueRecognitionEntry, ScoreTierThreshold, PreQualifiedOffer, ScoreAlertThreshold, RenderPolicy, ContentQualityFacet, OfferPresentationCap, OpsRun

**State machines (16):** Consumer, BureauSnapshot, Referral, PreQualificationDecision, ConsentRecord, DisputeReferral, OpsRun, ScoreSimulation, ScoreAlert, PreQualifiedOffer, ProductCatalogItem, Lender, LenderProgram, ScoreTierThreshold, RenderPolicy, ContentQualityFacet (plus 3 concurrency rules)

**Calculations (13):** score_alert_threshold, compute_modeled_approval_odds, compute_revenue_recognition_amount, compute_calibration_index, score_tier_lookup, monitoring_window_checks, ops_run_classification_sort, simulate_score_delta, face_value_vs_revenue, fee_breakeven_months, compute_offer_freshness, compute_score_volatility, governance_thresholds

**Endpoints:** 106 · **Validations:** 11 · **Errors:** 47

**Roles (7):** Consumer (`entity_backed:Consumer`), Referee, BureauConnector, LenderOps, ComplianceOfficer, PlatformAdmin, DataProtectionOfficer (all opaque)

**Difficulty-design instances:** 20 (rule counts: dual_variant_calc 3, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2)

**Corner-design instances:** 52 total — 48 active with `test_recipe`, 4 `excluded_because:` stubs

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (852 calls scanned)

Difficulty was pushed past the Expert band per the directive: every §0.5 rule carries 2–3 differentiated instances, and the three "biggest" token items were used to make the entities interact rather than to pad counts (dual-variant odds/calibration/revenue, a depth-3 ban→pause→decision cascade, an OCC-guarded consent funnel, and a reverse-reachability audit that forced 11 new sub-resource GETs into §1.5).

## Step 3: Copy shared files — 2026-09-30T00:06:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T00:20:00.000Z

PRD generated and verified.

Output: `workspace/PRD.md` — 418 lines, 5 top-level sections, 20 subsections.

Sections:
- §1. Introduction — three paragraphs framing the soft-pull monitoring / offer-matching marketplace, the adverse-selection trust problem, and the late-arriving referral revenue obligation.
- §2. Global Specifications & System-Wide Principles — 11 subsections: 2.1 RBAC (headers, all 7 roles with `identity:` translated, segregation of duties), 2.2 API response envelope (verbatim), 2.3 pagination (limit/offset defaults 10/0, min 1, max 100, `created_at` ASC, meta fields), 2.4 logical clock + scheduled daily run and its constituents, 2.5 soft-pull cadence (consent guards, 24h cooldown, census/`CANCELLED`, 30-day staleness), 2.6 ordinal ordering and derived consumer posture, 2.7 precision/rounding, 2.8 OCC (`expected_consumer_version`, `ERR_STALE_VERSION` 412), 2.9 left-to-right path validation, 2.10 common resource properties incl. the three `common_fields: false` families, 2.11 validation precedence ladder.
- §3. Business Logic & Workflows — 9 freely grouped subsections: 3.1 enrollment/pulls/alerts, 3.2 alert follow-through, explanations and consumer views, 3.3 score simulation walk, 3.4 render posture and presentation caps, 3.5 pre-qualification and lender/program/criteria matching, 3.6 consent/sealing/data boundary, 3.7 present/render/withdraw offers, 3.8 referrals, revenue recognition and calibration, 3.9 disputes, accuracy education and the governance envelope.
- §4. Endpoint Definitions — 4-column table (Method, Path, Description, Authorized Role(s)), 106 rows, preceded by the 201/200 status-code rule.
- §5. Error Code Catalogue — 2-column table (Error ID, HTTP Status Code), 47 rows, triggers scattered in §2/§3 only.

Hard contracts — all three PASS (verified by script over the generated file):
- Contract 1 (Field-Name Coverage): entities[].fields 108/108 present; endpoints[].input 70/70; endpoints[].path_params 1/1; endpoint output-shape fields 25/25; 0 missing. All four were repaired after a first pass found 6 entity fields, 3 input identifiers and 1 output field unbackticked (`alert_kind`, `decision_status`, `entry_kind`, `realized_amount_cents`, `recognized_at`, `topic`, `approval_odds_calibration_index`).
- Contract 2 (Rule Coverage): all 11 validations (priority ordering stated explicitly in §2.11), 3 concurrency_rules (write target + `expected_consumer_version` + `ERR_STALE_VERSION` 412 each named), every state-machine transition/side-effect, all 14 calculations with constants translated into prose with no operator syntax, every validation condition matchable to its `error_id` in §2/§3, every `applies_to` scope enumerated, all 47 error IDs present in §2/§3, and all calculation constants (`ODDS_*`, `UTIL_*`, `SCORE_*`, `OFFER_*`, `PREQUAL_CACHE_DAYS`, `CONSENT_SEAL_MAX_PER_RUN`, `RETENTION_DAYS`, `PENDING_DISPUTE_CAP`, `CONTENT_QUALITY_MIN`, `OFFER_CAP_BPS`, `SNAPSHOT_STALENESS_DAYS`, `PULL_COOLDOWN_HOURS`, `SCORE_ALERT_DEFAULT_THRESHOLD`) embedded in business context. State enumeration values verified complete.
- Contract 3 (§3 Path Purity): 611 backticked tokens in §3 scanned, 0 starting with `/`, 0 bare HTTP methods, 0 combined method+path tokens.

§2.2 is byte-identical to `section-2.2-response-structure.md`. No invented rules (the only non-scaffold error IDs grep hit, `ERR_OFFER_PRESENTATION_BLOCKED`, is scaffold-declared in the render transition preconditions). Constraints respected: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was read, grepped or referenced, and no sibling task directory was inspected.

## Step 5: Generate unit tests — 2026-09-30T00:45:00.000Z

All checks pass. Final state verified.

**Files written** (`tasks/task_3062_credit_monitoring_score_simulation_pre_qualified_offer/`)

`test_helpers/` — 1,631 lines total:
- `__init__.py` 29 · `api_errors.py` 107 · `constants.py` 51 · `types.py` 490 · `api_client.py` 492 · `assertions.py` 167 · `factories.py` 156 · `test_users.py` 25 · `fixtures.py` 514

`test_suite/` — 3,449 lines total:
- `conftest.py` 55 · `test_01_monitoring_enrollment.py` 234 · `test_02_bureau_pulls_and_alerts.py` 315 · `test_03_score_simulation.py` 110 · `test_04_modeled_odds_and_decisions.py` 208 · `test_05_offers_and_consent.py` 354 · `test_06_offers_render_posture.py` 159 · `test_07_referrals_and_revenue.py` 207 · `test_08_disputes_and_calibration.py` 319 · `test_09_roles_and_clock.py` 378 · `test_10_catalog_and_lifecycle_errors.py` 201 · `test_11_dual_variant_and_caps.py` 280 · `test_12_quota_persistence_and_readback.py` 284

**Test count: 101** (all collect cleanly; byte-compile clean).

**Tagging: 41 tests from queue A (all 20 difficulty instances, ≥2 each) and 60 tests from queue B (all 48 non-stub corner instances, ≥1 each).** Zero untagged, zero dual-tagged, zero tags resolving to nonexistent instances. The 4 `excluded_because:` stubs were not translated; their `difficulty_instance` pointers all resolve.

**Design instances SKIPPED by the PRD-first filter: none.** Every instance in both queues passed the two-condition filter. Where an instance's literal asserted value was not uniquely derivable from PRD prose, the generator kept the instance but re-anchored the assertion to the PRD-derivable value (see disagreements below) — no instance was dropped.

**Scaffold/PRD disagreements found:**
1. **`odds_weighted_penalty_branch_and_clamp`** — the recipe's ordered pair is incoherent. It assigns 0.80 to util exactly 30.00 and 0.85 to util 40.00, but the PRD's strict `> ODDS_UTILIZATION_FREE_PCT` branch gives 0.80 at 30.00 *without* penalty. The set {0.80, 0.85, 0.99} is only reachable if the soft-criterion fraction differs across the two consumers; the fixture uses one program, so the fraction is equal. Asserted the PRD-derivable values instead (0.85 at util 40 / 0.80 at util 30 with a soft criterion that fails).
2. **`calibration_index_including_provisional_versus_settled_only`** — distinguishing_aspect claims "two decisions, both modeled at 0.91, one funded and one declined" yield 1.82 provisional vs 0.91 settled. Per PRD §3.8 both are then settled (`modeled_odds_settled` true after a realized outcome), so both variants should compute identically (≈1.82). The 1.82/0.91 divergence only arises if the second decision is left unconsumed. Used the unconsumed second decision, which uniquely derives 1.82 / 0.91.
3. **`odds_provisional_versus_settled_after_realized_outcome`** — the recipe seeds a hard `UTILIZATION_PCT LTE 50` with 40% utilization plus a *failing* soft `DTI_PCT LTE 30` at dti 35, after asserting 0.91. A failing soft criterion reduces the soft-match fraction and gives 0.85, not 0.91. Used a soft criterion that matches (dti 25 via the program's `max_dti_pct`), which yields 0.91.
4. **`utilization_penalty_boundary_exactly_at_thirty_percent`** — the "30.01" consumer's workaround gives util 40.01, and the recipe's own per-consumer values do derive (0.86 / 0.86 / 0.91). Asserted those.
5. **`referral_creation_requires_unsealed_consent`** grounds `errors.ERR_OFFER_NOT_RENDERED`, but the instance's scenario has a rendered offer; the actual refusal is a state/consent error. The error_id is also absent from the PRD §5 catalogue (`ERR_OFFER_NOT_RENDERED` *is* present, but the recipe never triggers it), so that test asserts the PRD's "a consent that is no longer pending … is refused" rule with `ERR_INVALID_STATE_TRANSITION`, not a weakly-derived literal. The genuinely-unrendered case was tested separately in `test_07`.
6. **Scaffold/prose surface drift** (not test-bearing): PRD §3.7 mentions `ERR_COLLATERAL_ELIGIBILITY_CHANGED` and `ERR_OFFER_PRESENTATION_BLOCKED` as distinct render gates, whereas scaffold Table 4 lists priority-8 `ERR_COLLATERAL_ELIGIBILITY_CHANGED`; no design-index instance asserts either, so no test was emitted.

All 101 docstrings carry a C1/C2/C3 PRD citation (verbatim ≥8-word grep confirmed, 0 failures), end in exactly one `Design:` line, contain no `skip`/`skipif`/`xfail`, and reference no scaffold table/§1.x labels. Implementation directory was never read.

## Step 6: Generate implementation — 2026-09-30T01:15:00.000Z

First attempt aborted with `API Error: Claude's response exceeded the 32000 output token maximum` and wrote nothing. Relaunched with an explicit output-token-discipline instruction (many small modules, one Write per message, each under ~400 lines). Second attempt completed.

Implementation complete and verified.

## Files written — `workspace/implementation/`

| File | Lines |
|---|---|
| `start.sh` | 9 |
| `requirements.txt` | 1 |
| `app.py` | 85 |
| `errors.py` | 70 |
| `envelope.py` | 69 |
| `store.py` | 105 |
| `auth.py` | 56 |
| `helpers.py` | 324 |
| `models.py` | 197 |
| `consumers.py` | 156 |
| `monitoring.py` | 378 |
| `simulation.py` | 188 |
| `analytics.py` | 109 |
| `catalog.py` | 234 |
| `lenders.py` | 340 |
| `prequal.py` | 233 |
| `consent.py` | 151 |
| `offers.py` | 449 |
| `referrals.py` | 344 |
| `disputes.py` | 171 |
| `opsrun.py` | 245 |

**Endpoints: 106** blueprint routes under `/credit` (the full §4 table, including the nested sub-resource collections).

## Boot verification

Launched `PORT=47857 bash start.sh` on a free high port, curled, then killed exactly that PID (`$!` captured to a pidfile). Results: `POST /credit/_clock/set_current_utc` 200, `GET /credit/consumers` 200 (empty store), `POST /credit/consumers` 201, missing-header request 400 `ERR_INVALID_REQUEST`, bad-role request 400. Full happy path also exercised end to end (tier→item→lender→program→criterion→consumer→consent→pull 201→alert `SCORE_FLAT`→factor explanation `rank_index 0`→simulation 201 `projected 702`→pre-qual 201 `ELIGIBLE/0.86`→qualify→present 201→render 200→consent 201→referral 201→fund 200 `REVENUE 5000`→reverse 200→catalog derived view→ops run 201→dispute 201). A **reboot check** confirmed the store comes back empty after a fresh `start.sh` (200 with `data: []`), so `--isolation per-test-server` is satisfied. No stray processes remain.

Storage is module-level dicts only — no SQLite, no JSON dump, no `/tmp` cache, and no `seed_*`/startup population anywhere.

## PRD ambiguities resolved

- **Consumer auth needs enrollment id** — a test enrolling as `c_1` then pulling with `X-User-ID: c_1` would 403 under a strict "id must equal `X-User-ID`" rule; the implementation stores the enrollment-caller id on the consumer and accepts either it or the entity id as "own" for Consumer-role ownership checks.
- **`whole_render_completeness` constituents** (PRD never enumerates them) — treated as all `ContentQualityFacet` rows for the consumer being `COMPLETE`; no facets at all → false. `content_quality_override` is implemented as waiving only the content-quality minimum, never the completeness facet, per §3.4.
- **Sealed-consent visibility** — `POST /referrals`/`/referral-attempts` require a *PENDING* grant, but the funding path accepts a grant that a prior daily run already sealed (only `NOT_SEALED` counts as consumed), since PRD §3.6 states the settlement pass seals pending consents.
- **`is_over_presentation` / render cap** — "total offer count" taken as the consumer's non-withdrawn offers; breach when `presented_count > floor(cap_bps * total / 10000)`.
- **Governance constants not in either table** — `REFERRAL_FUNDING_WINDOW_DAYS` (30, stated as prose in §3.8) and the `OFFER_INTENT_TTL_HOURS`/`OFFER_SETTLEMENT_TTL_HOURS` pair (both 720 h → 30 days) are hardcoded as PRD prose values.
- **Factor `direction`/`impact_points`** — the scaffold points to a "scoring factor table" with no fixed values; derived deterministically from a curated negative-token list plus a magnitude computed from the code, with `store.FACTOR_TABLE` written by the score-tier endpoints (never preloaded).
- **`monitoring_posture` `COMPLETE` vs `IMMATURE`** — all postures are derived on read / by the ops run from the pull count and consent timestamp rather than stored as authored state; a single successful pull reads `IMMATURE`, two or more `COMPLETE`, consent without a pull `MONITORING`.
- **`ERR_PRESENTATION_BLOCKED`** — absent from §5's catalogue; implemented as HTTP 409 locally, since §7 of the scaffold's `present`/`render` rules names it.

## Step 7: Run tests and iterate — 2026-09-30T02:30:00.000Z

All 8 rounds pass 101/101 consistently. The loop is complete.

### Summary

**Iterations run:** 2 (initial sweep → diagnosis/fixes → verification sweep). Baseline was 47/101; final result is **101/101 passing across all 8 parallel rounds**, zero failures in the union.

No tests deleted. Every fix traces to a verbatim PRD sentence (§2.5, §2.6, §3.1, §3.4, §3.5, §3.6, §3.7, §3.8, §3.10/§2.10/§2.11) or to the scaffold state machine the PRD prose mirrors.

#### Fixes applied to `test_helpers/`
- `factories.py` — `create_bureau_snapshot_payload` now sends the pull `channel` the PRD §3.1 alert rule requires ("the requested channel is stored on it unchanged"). The missing field was the upstream cause of the alert-row failures.
- `fixtures.py` — added `read_referral` (referenced by `test_07` but absent); `create_targeting_criterion_payload`'s defaults are the standard hard UTILIZATION_PCT/LTE/50 + soft DTI_PCT/LTE/30 criterion the PRD §3.5/§3.7 recipes use, and `pull_bureau_snapshot` no longer collapses to a single factor code (the design recipe asserts the multi-factor explanation chain).

#### Fixes applied to `test_suite/`
- `test_02` — `list_consumer_alerts` calls now pass the exact-status filter the PRD §3.2 defines; FLAT-row assertions filter to the intended `to_score` row (the first pull legitimately also writes a SUPPRESSED FLAT row); deleted the two assertions whose premise ("natD DTI boosts odds") contradicted the PRD's `DTI_PCT` only acting through criteria.
- `test_05` — `read_offer` call signatures corrected (a header dict was being passed where an api client was expected).
- `test_06` — ops-posture setup now creates a correctly-topic'd COMPLETE facet rather than relying on a stale facet.
- `test_08` — adverse-action summary now derives `factor_codes` from its own snapshot (PRD §3.2 defines the field as read-only/derived, not the fixture's pull array), preserving the recipe's asserted design point.
- `test_01`, `test_09` — consent-after-close and consumer-read timestamp/header assertions corrected to the PRD's role/ownership semantics.
- `test_12` — sealing-quota test now completes consent via `setup_offer_scenario` (offer must be RENDERED before referral consumes consent, PRD §3.8) instead of referencing a referral's consent; program-pause test no longer asserts an empty consent list (the setup scenario legitimately consumes consent).
- Cross-suite: `intent_recorded_at`/`funded_at`/`sealed_at`/`granted_at`/invoice timestamps are compared with `startswith` because the fixtures seed the clock as `2026-09-01T00:00:00.000Z` (three fractional digits, PRD §2.4/§2.10) while the design recipes abbreviate to `...Z`. The pre-existing `is_iso8601_timestamp` contract already permits both, so this is a normalization of over-literal assertions, not a weakening.

#### Fixes applied to `implementation/`
(present as `workspace/implementation/`)
- `opsrun.py` — decision TRAP now only rescues a PREQUALIFIED decision whose pinned snapshot is stale (PRD §3.5); previously it demoted every consent-less PREQUALIFIED decision on any ops run, breaking the entire offer funnel.
- `opsrun.py` — decision expiry now runs before the TRAP pass so expiry is not silently overwritten.
- `models.py` — settled decisions serialize `modeled_odds_pct` as the realized integer 0/100 (PRD §3.5); the raw provisional value is retained for the calibration calculation (PRD §3.8's two-variant divergence).
- `analytics.py` — `realized_rate` default is `0.0` per §3.8's formula (`successes / considered`), and the mean uses the provisional odds.
- `lenders.py` — program_code uniqueness enforced at activation, not creation (scaffold); pause cascade now reverts PREQUALIFIED/CONSENTED decisions to INELIGIBLE while still stamping `PROGRAM_PAUSED`.
- `referrals.py` — `modeled_odds_settled` derived from terminal outcomes; referral-attempt consumes the one-time consent; terminal offer/decision statuses return state errors; clawback leg uses `clawback_rate_bps` (PRD §3.8 compensating invariant); decline releases PENDING consent; SENT referrals release after the 30-day window on read.
- `monitoring.py` — consumer-scoped alert listing honours the `status` filter (PRD §3.2).
- `consumers.py` — `close` gate matches §3.6 (every decision must be CONSENTED/CONSUMED/EXPIRED); non-owning consumer resolves to `ERR_CONSUMER_NOT_FOUND` (PRD §2.9); `adverse_action_summary` sorts by ordinal; volume drilldown read requires active consent (PRD §3.6).
- `offers.py` — `whole_render_completeness` requires both scorable topics (PRD §3.4); facet rescoring is Referee-only; cap/expiry boundary made inclusive.
- `consent.py` — release clears `sealed_at`; expiry boundary inclusive.
- `helpers.py` — presentation-census total counts all offers (PRD §3.4).
- `envelope.py` — added plain-instant timestamp helper used by `models.py` for domain instants.

**Per-process state:** in-memory dicts only; no SQLite/JSON/`/tmp` persistence, no startup seeding — the reboot check confirms a fresh boot returns empty, and `--isolation per-test-server` was clean across all 8 concurrent rounds.

**Verified on disk by orchestrator:** `results.{1..8}.json` each report `passed 101 / total 101`.

## Step 8: Finalize PRD — 2026-09-30T03:00:00.000Z

Done. `PRD_FINALIZED.md` is written at the requested path. Final verification: 418 lines both files (0% line-delta), 12 in-place single-line edits.

### Summary

- **PRD.md**: 418 lines. **PRD_FINALIZED.md**: 418 lines. **%-delta: 0%** (every edit is a single-line replacement; no line added or removed).

### One bullet per change

- **§2.5 (L90)** — insert — consent grant now also requires the consumer to still be `ACTIVE` (any other status is a state error) — `implementation/monitoring.py:57` (traced to the `test_01` consent-after-close fix).
- **§2.9 (L120)** — insert — a `Consumer` addressing another consumer's record (consumer read or that consumer's adverse-action summary) gets `ERR_CONSUMER_NOT_FOUND`/404 — `implementation/consumers.py:18`.
- **§2.10 (L124)** — revise — `created_at`/`updated_at` keep three-fractional-digit form, but every other dated field (domain instants) is reported at whole-second granularity; `api_request_timestamp` stays three-digit — `implementation/models.py:10` / `envelope.py:14`.
- **§3.2 (L155)** — revise — adverse-action-summary `factor_codes` is derived from the highest-ordinal snapshot's own factor array (not caller-supplied), and `education_topics_consumed` is the sorted set from submitted/acknowledged disputes — `implementation/consumers.py:104` (traced to the `test_08` fix).
- **§3.4 (L173)** — insert — `whole_render_completeness` requires both scorable topics (`factor_explanations`, `accuracy_education`) to be represented and all facets `COMPLETE` — `implementation/offers.py:243`, `helpers.py:291`.
- **§3.5 (L185)** — revise — `program_code` uniqueness is checked among already-`ACTIVE` programs at activation; pause cascade now also converts `CONSENTED` decisions to `INELIGIBLE` — `implementation/lenders.py:250`, `lenders.py:79`.
- **§3.5 (L191)** — revise — settled odds report the integer 0/100 (underlying provisional odds below 0.5 → 0, else 100) while the provisional value is retained for the calibration mean — `implementation/models.py:160`.
- **§3.5 (L195)** — revise — the consent-less `PREQUALIFIED` rescue fires only when the pinned snapshot is no longer `ACTIVE`; an `ACTIVE`-pinned decision is left `PREQUALIFIED` — `implementation/opsrun.py:68`.
- **§3.6 (L203)** — revise — close is refused if any referral is non-terminal (not just `SENT`) and any decision is still `NEEDS_SNAPSHOT`/`ELIGIBLE`/`INELIGIBLE`/`PREQUALIFIED` — `implementation/consumers.py:134`.
- **§3.7 (L217)** — revise — the render cap's total is the consumer's non-`WITHDRAWN` offer count — `implementation/offers.py:220`.
- **§3.8 (L231)** — revise — the CLAWBACK leg uses the referral's copied `clawback_rate_bps` (not the revenue share) — `implementation/referrals.py:224`, `referrals.py:336`.
- **§3.8 (L237)** — insert — when the index is null, the reported `realized_rate` reads 0.0 while `modeled_odds_mean` reads null — `implementation/analytics.py:44`.

### Per-edit pre-edit search log

1. **§2.5 consent-requires-ACTIVE.** (a) Subject: monitoring-consent grant precondition. (b) Read `monitoring.py:52-66`; enumerated `consumers.py` close (`refresh_posture` forces posture but leaves status `CLOSED`), all `monitoring_consent_at` writers. (c) Widened to "any other consumer status is a state error" (not the specific `CLOSED`) so it matches the `ERR_INVALID_STATE_TRANSITION` code without falsely narrowing.
2. **§2.9 non-owning consumer read.** (a) Subject: ownership/404 resolution for a non-owning consumer caller. (b) Read `consumers.py:18-21` and every `helpers.owned`/`identity_matches` caller (`monitoring.py` alerts, `prequal.py`, `simulation.py`, `consent.py`, `offers.py`); confirmed GET `pre-qualified-offers`, referrals, consents and disputes fall to a different helper (`_get` → `ERR_CONSUMER_NOT_FOUND`) but the shared `_scope`/`identity` pattern is the only one reaching identity_matches with a role. (c) Scoped the wording to the two paths the shared `_scope` helper actually gates (consumer read + adverse-action summary) rather than "any non-owning read", since other consumer-scoped GETs resolve the id first.
3. **§2.10 timestamp granularity.** (a) Subject: reported timestamp format for `_at`/`until` fields. (b) Scripted-enumerated all field lists in `models.py` and cross-checked against `PLAIN_INSTANT_FIELDS`; read `envelope.timestamp`/`plain_timestamp` and `app.py` `IsoJSONProvider`. Result: exactly two datetime families — `created_at`/`updated_at` three-digit, all other dated resource fields whole-second. (c) Listed every plain field explicitly and added the `api_request_timestamp` carve-out so the global sentence cannot be read as retracting §2.2.
4. **§3.2 adverse-action-summary derivation.** (a) Subject: derived fields of the credit-health view. (b) Read `consumers.py:87-125` (`_education_topics`, `_volatility`, `adverse_action_summary`). (c) None required; used "distinct... ordered as a sorted list" to match the `sorted({…})` implementation.
5. **§3.4 whole_render_completeness.** (a) Subject: the completeness predicate. (b) Read `offers.py:243-252` and `helpers.py:291-296` (the duplicate); grepped all callers (`offers.py:227`, `offers.py:281`). (c) Softened "that is, when both... " to "which requires that both... are represented... and every constituent facet is COMPLETE", so the separate `blanket_presentation_override`/`content_quality_override` render paths (§3.7) are not accidentally narrowed.
6. **§3.5 program_code + pause cascade.** (a) Subject: program-code uniqueness timing and the pause cascade's decision set. (b) Read `lenders.py` create (no check), `activate_program` (L241-257), `pause_program` (L260-269), `_cascade_ban`/`_ineligible_decisions_of_program` (L67-98), `resume_program`. (c) Scoped uniqueness to "already `ACTIVE` programs" (avoids claiming a global/uniqueness-everywhere rule that DRAFT programs violate) and kept the enumerated cascade set exactly as the impl's `("ELIGIBLE","PREQUALIFIED","CONSENTED")`.
7. **§3.5 settled odds integer.** (a) Subject: how `modeled_odds_pct` is reported once settled. (b) Read `models.decision` (L160-169), `prequal.py` writers, `referrals.py:259-267` (`refresh_settled`), `analytics.py:52` (provisional mean source). (c) Added the non-null guard and the "underlying provisional value retained" clause so the sentence stays consistent with the calibration mean (which reads the raw provisional value, not the integer).
8. **§3.5 PREQUALIFIED rescue.** (a) Subject: the decision TRAP pass. (b) Read `opsrun.py:40-85` (`_mobility`), including the same-function expiry loop and the `SENT`→`UNFUNDED` release; grepped `consent_for`. (c) None required; wording mirrors the impl's `pinned is ACTIVE → continue` early-out.
9. **§3.6 close gate.** (a) Subject: consumer-close preconditions. (b) Read `consumers.py:128-141`; enumerated the four terminal referral statuses and `agreements` with `referrals.py` terminal set and `prequal.py` status values; checked `test_01` close tests. (c) Rewrote to "non-terminal referral (any status other than the four terminal ones)" and the exact four decision statuses, since the impl's `NEEDS_SNAPSHOT`/`INELIGIBLE` inclusion is broader than the PRD's "ELIGIBLE or PREQUALIFIED".
10. **§3.7 render cap total.** (a) Subject: presentation-cap breach denominator. (b) Read `offers.py:219-224` (render check), `offers.py:59-65` (`_recompute_cap`), `offers.py:420-426` (`_cap_view`), and `helpers.is_over_presentation` (L187-199). (c) Qualified only §3.7's render-path total as "non-`WITHDRAWN`" and deliberately left `helpers.is_over_presentation`'s all-offers total (used by §3.5 qualify) unchanged, so the two divergent total-bases remain intact; note this WITHDRAWN detail sits outside `<step_7_diff>`'s listed items and should be confirmed in Step 9 (it is a genuine PRD-silence at the extracted site but is the one edit not verbatim-listed).
11. **§3.8 clawback rate.** (a) Subject: the clawback entry's rate source. (b) Read `referrals.py:224-240` (`post_clawback_entry`), `referrals.py:325-350` (`reverse_referral`, incl. `clawback_rate_bps` copy), `analytics.py:69-88` (`face_value_vs_revenue`, revenue-share leg). (c) None required; explicitly preserved §3.8's compensating-invariant sentence (which still reads from `clawback_rate_bps`).
12. **§3.8 null calibration defaults.** (a) Subject: the reported calibration fields in the empty/no-success branch. (b) Read `analytics.py:36-66` (`calibration_index`), `catalog.py:81-116` (item read + settled-index read). (c) None required.

### Deliberately not edited (pure fixture/test bugs, no PRD signal)

`factories.py` `.channel` default, `fixtures.py` `read_referral`/`pull_bureau_snapshot` multi-factor, `test_05`/`test_06` call-signature fixes, and the cross-suite `startswith` timestamp normalization (already permitted by the existing `is_iso8601_timestamp` contract and §2.10 text) are fixture defects or over-literal assertions — they reveal no PRD silence or PRD/impl mismatch, so no PRD prose was changed for them.

## Step 9: Complete PRD — 2026-09-30T03:40:00.000Z

I've completed the alignment. Here is the summary.

### Output

**`workspace/PRD_COMPLETED.md`**

- Source: `workspace/PRD_FINALIZED.md` (used, as instructed)
- Lines: 418 → 419 (one net line — the added §5 error-catalogue row)
- Chars: 88,550 → 94,608 (**+6,058**)
- Sections: 25 → 25 (no structure change; only inline prose edits)
- Change footprint: 21 edited lines / 23 distinct prose changes; all are in-paragraph inserts or rewordings. No new sections, no invented behavior.

### Counts

- **Ambiguity-pins: 21**
- **Mismatch-revisions: 2** (PRD §3.7 offer-freshness; PRD §3.8 second-clawback code)
- (Several pins were implemented by rewording the sentence they sit in, so the "insert vs revise" split is 16 pure inserts / 5 rewordings.)

### Changes

- §2.1 (L19) — insert — ambiguity — Consumer ownership accepts either the enrolling `X-User-ID` or the consumer row's own `id` — `implementation/helpers.py:74`
- §2.4 (L82) — insert — ambiguity — run always settles `COMPLETED` with all nine stages; settle bumps the run's `version`/`updated_at` — `implementation/opsrun.py:239`
- §2.5 (L90) — insert — ambiguity — accepted monitoring-consent grant advances the consumer's `version` — `implementation/monitoring.py:64`
- §2.5 (L94) — insert — ambiguity — empty census writes the `CANCELLED` row and bumps `version`, but no supersede/recompute/alert — `implementation/monitoring.py:85,176`
- §2.6 (L100) — insert — ambiguity — `previous_score` is the second score in the **non-CANCELLED** counter set, not the second-highest ordinal overall — `implementation/helpers.py:133`
- §3.1 (L143) — insert — ambiguity — cancelled pull writes no alert; alert `channel` is read from the pull payload (replay → null) — `implementation/monitoring.py:183,155`
- §3.1 (L147) — insert — ambiguity — replay re-mints one factor explanation per code and evaluates an alert with null channel — `implementation/monitoring.py:232`
- §3.3 (L161) — insert — ambiguity — a consumer with counted pulls but no `ACTIVE` snapshot also gets `ERR_SIMULATION_NEEDS_SNAPSHOT` — `implementation/simulation.py:116`
- §3.3 (L163) — insert — ambiguity — the settle route recomputes `FINALIZED` sims against current state and is refused otherwise — `implementation/simulation.py:184`
- §3.4 (L173) — insert — ambiguity — render posture is **not** recomputed on facet create/rescore, only on policy writes and the rollup — `implementation/offers.py:342,395`
- §3.4 (L175) — insert — ambiguity — `content_quality_override` (not `blanket_presentation_override`) governs the `RENDER_OPEN` climb — `implementation/offers.py:243`
- §3.4 (L177) — insert — ambiguity — cap breach denominator is non-`WITHDRAWN`; the qualify-time over-presentation test counts **all** offers; a missing cap row defaults to 5000 bps / presented 0 — `implementation/offers.py:59,220`; `helpers.py:187`
- §3.5 (L187) — revise — ambiguity — `CONSUMER_STATE_EXCLUDED` surfaces as the decision's `reason`, not a raised error — `implementation/prequal.py:95`
- §3.5 (L195) — insert — ambiguity — the adverse-selection stage never re-checks lender-served-state; a resume does not rescue cascaded decisions — `implementation/opsrun.py:101`
- §3.5 (L195) — insert — ambiguity — `ERR_SHARED_CRITERION_NO_SNAPSHOT`/`ERR_SNAPSHOT_MOVED` are catalogue-only; the surfaced path is `NEEDS_SNAPSHOT` + `NO_ACTIVE_SNAPSHOT` — `implementation/errors.py`, `opsrun.py:101`
- §3.7 (L215) — **revise — mismatch** — single 30-day basis from `intent_recorded_at`, strictly-after expiry, lazy on read, and the stale-offer stage sweeps **all** `RENDERED` offers unconditionally — `implementation/offers.py:20-41`; `opsrun.py:142`
- §3.7 (L217) — insert — ambiguity — render re-checks the decision's `fresh_until` (`ERR_OFFER_EXPIRED`) before its three gates — `implementation/offers.py:213`
- §3.7 (L217) — insert — ambiguity — the third render gate's code is `ERR_OFFER_PRESENTATION_BLOCKED` (values agree with the presentation gate) — `implementation/offers.py:218`
- §3.8 (L227) — insert — ambiguity — funding accepts the linked grant whether `PENDING` or already `SEALED` — `implementation/referrals.py:38`
- §3.8 (L231) — **revise — mismatch** — a repeated clawback surfaces as `ERR_INVALID_STATE_TRANSITION`, not `ERR_CLAWBACK_ALREADY_APPLIED` — `implementation/referrals.py:334`
- §3.8 (L235) — insert — ambiguity — the past-window release is also applied lazily on referral read-back — `implementation/referrals.py:163`
- §3.9 (L251) — revise — ambiguity — `ERR_PROGRAM_NOT_DELIVERABLE`/`ERR_PROGRAM_PAUSED` are catalogue-only; routing refuses through the decision's cascaded state — `implementation/lenders.py:260`; `referrals.py:28`
- §5 (L387) — insert — mismatch — added the `ERR_OFFER_PRESENTATION_BLOCKED` row — `implementation/errors.py:22`

### Step 8 question — confirmed and reconciled

Requested §3.7 render-cap denominator: **confirmed**. The two divergent total-bases live in `implementation/offers.py:59-65` (`_recompute_cap`, used by render/`render_offer` and by the daily run's cap-window stage — divides by offers whose status is **not WITHDRAWN**) versus `implementation/helpers.py:187-199` (`is_over_presentation`, used by the qualify promotion — divides by **all** offers regardless of status). Both are reconciled in the single §3.4 (L177) insertion, which now names both bases and which path uses which. All three render cap sites in `render_offer` (`offers.py:220-224`), `_cap_view` (`offers.py:420-426`) and `_recompute_cap` use the non-withdrawn base consistently; only the qualify path uses the all-offers base.

### Note on an implementation defect (not a PRD matter)

`implementation/opsrun.py:193` calls `helpers.content_quality_required_met(cns["id"])`, which is **not defined** in `helpers.py` (confirmed via `hasattr` and by direct invocation: raises `AttributeError`). It is reached only by the blanket-override render path (`run_blanket_renders`, `opsrun.py:184-202`), whose daily-run branch always crashes, so blanket renders can only ever happen through the direct render endpoint. No test exercises the blanket path (nothing in `test_suite/` touches `blanket_presentation_override`; all 101 tests pass because the crashing branch is never taken). I did **not** invent this into the PRD — the run-settling prose I added stays at the observable-behavior level. Since the implementation is the alignment target, the PRD cannot be made to describe the (unreachable) crash as intended behavior; the defect belongs to `implementation/`, not the PRD. Flagged as the one residual behavioral inconsistency a reader of the PRD could not have predicted.

## Step 9 follow-up: implementation defect fix — 2026-09-30T04:00:00.000Z

Orchestrator action on Step 9's flagged defect. PRD §3.4 (L175) and §3.7 (L219) both explicitly require the daily run's blanket-override path to render `PRESENTED` offers only when the consumer's content-quality requirement stands ("the content-quality facet is explicitly not waived by this path, so an offer that fails the content-quality requirement does not render through it"). The call site correctly expressed that rule; only the helper itself was missing — a coding omission, not an unspecified capability.

Fixed: restored `content_quality_required_met(cid)` in `implementation/helpers.py` — requires both scorable topics (`factor_explanations`, `accuracy_education`) to be represented and every such facet's `score_bps` to meet `CONTENT_QUALITY_MIN` (8000).

Also ran a static AST scan across all implementation modules for undefined cross-module attribute references: exactly one real finding (this one); the other five hits were Flask app-object attributes (`app.errorhandler`, `app.json`, `app.register_blueprint`, `app.run`, `app.url_map`) and therefore false positives.

Re-ran the full 8-round parallel sweep after the fix: **all 8 rounds 101/101**, no regressions. Smoke-tested the restored helper and the `run_blanket_renders` no-policy path directly — both clean.