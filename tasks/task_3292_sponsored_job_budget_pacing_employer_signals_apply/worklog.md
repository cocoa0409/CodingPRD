# Worklog — task_3292_sponsored_job_budget_pacing_employer_signals_apply

## Step 1: Create task directory — 2026-09-30T18:00:00.372Z

Used the pre-allocated task directory `./tasks/task_3292_sponsored_job_budget_pacing_employer_signals_apply` (already contained `workspace/`); did not compute a new index and did not create any other `task_*` directory. Verified `workspace/` exists and is empty.
## Step 2: Generate scaffold — 2026-09-30T18:42:18.000Z

Sanity check complete: I re-read the ask (three exactly-named files, single top-level keys, no design keys in SCAFFOLD.yaml, scenario verbatim, no sibling-task peeking), ran the skill's own `scaffold_lint.py` to a clean verdict, and independently audited grounds resolution, duplicate names, exclusion targets, forbidden concurrency vocabulary, enum closure, and every formula-derived literal by hand.

What I built: a **quota_allocation + pricing_engine** scaffold for sponsored-job budget pacing. The core coupling is a finite campaign budget competed for by auction winners, paced across a logical day, with a 4-hop cascade: billable event → commit spend → campaign auto-completes → sponsored jobs pause → pacing holds release.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3292_sponsored_job_budget_pacing_employer_signals_apply/`)
- `SCAFFOLD.yaml` — 1462 lines, keys `scenario · domain_name · api_prefix · complexity_profile · entities · state_machines · concurrency_rules · calculations · validations · response_envelope · endpoints · errors · roles`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1071 lines, single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1899 lines, single key `scaffold_corner_design`

**Counts**: 13 entities · 5 state machines · 2 concurrency rules (OCC on Campaign.version) · 8 calculations · 11 validations · 42 endpoints · 37 error codes · 4 roles · 13 FK edges (all reverse-reachable).

**§1.8 — 18 instances, 9 rule blocks × 2**: dual_variant_calc 2, combinatorial_formula 2 (modes a/b), non_linear_state_machine 2, transitive_cascade 2 (depth-3 + depth-4), priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.

**§1.9 — 45 active instances + 4 exclusion stubs**: entities 8/1, state_machines 7, calculations 3/1, validations 11, endpoints 5, errors 2, rbac 2, cross_cutting_complexity_layers 6/2, consistency_model 1.

Two notes on deliberate deviations: endpoint count is 42 (skill's Expert band is 20–32; the scenario's nine sub-domains plus the lint's FK-reverse-reachability rule force a wider surface — I trimmed from 52 to 42); and I pushed depth via 8 calculations, 6 concurrent complexity layers, and an 8-entity cascade rather than raw entity count.

result: Generated three lint-clean scaffold artifacts (42 endpoints, 13 entities, 18 §1.8 instances, 45 §1.9 corners) for the sponsored-job budget pacing task at /home/ubuntu/github/CodingPRD/tasks/task_3292_sponsored_job_budget_pacing_employer_signals_apply/.

**Orchestrator verification (independent of the subagent's self-report):** on-disk counts confirmed 1462 / 1071 / 1899 lines; difficulty file has exactly 9 `rule_id:` blocks, 18 instance `name:` entries and 18 `test_recipe:` blocks; corner file has 9 sections, 49 instance names of which 5 carry `excluded_because:`; SCAFFOLD.yaml has 42 method/path endpoint pairs and 37 error `id:` entries.

**Flag for Step 6 (from prior-pipeline memory):** 42 endpoints is above the ~40 threshold at which the implementation-generator has historically returned a rambling report instead of writing all files. After Step 6 I must verify `workspace/implementation/` on disk directly (file list + `start.sh` boot), not trust the subagent's summary.

## Step 3: Copy shared INSTRUCTION.md — 2026-09-30T18:43:15.124Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes). Bash-only step, no subagent.

## Step 4: Generate PRD — 2026-09-30T18:53:58.860Z

The PRD is generated and verified. I read the skill spec and the fixed §2.2 source, wrote the document in three chunks (title/§1/§2, then §3, then §4/§5), and audited it mechanically. I never opened `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or any sibling task.

**Sanity checks run:** fuzzy-word sweep (0 hits after fixing two "roughly"s), §2.2 byte-identical diff against the canonical source (True), field/enum/state/error coverage, §3 path-purity token scan, endpoint-table row count (42) and error-table row count (36).

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3292_sponsored_job_budget_pacing_employer_signals_apply/workspace/PRD.md` — 349 lines, 11,628 words, 77,572 bytes.

**Section list**
- 1. Introduction
- 2. Global Specifications & System-Wide Principles — 2.1 Acting Roles and Ownership Boundaries; 2.2 API Response Structure (verbatim); 2.3 Pagination; 2.4 Resource Identity, Mutable Timestamps and Version Bookkeeping; 2.5 The Immutable Budget Ledger and the Conserved Quantities; 2.6 Money and Multiplier Precision; 2.7 The Logical Clock and Day Rollover; 2.8 Graded Request Evaluation and Precedence; 2.9 Optimistic Concurrency on Campaign Writes; 2.10 Nested Resource Resolution and Child Sub-resources
- 3. Business Logic & Workflows — 3.1 Employer Onboarding, Feed Ingestion and Posting Integrity; 3.2 Campaign Budget, Pacing Mathematics and Day Rollover; 3.3 Sponsored Job Attachment, Eligibility and the Candidate Pool; 3.4 Clearing the Auction and Pricing an Event; 3.5 Recording Sponsored Events and the Budget Commit Split; 3.6 Apply Flows, Screening and Apply-Routing Events; 3.7 Employer Quality Signals and How They Reshape Distribution; 3.8 Refunds, Duplicate Invalid Clicks and Billing Posture; 3.9 Job Alerts, Matching and Relevance Ranking
- 4. Endpoint Definitions (4-column table, 42 rows)
- 5. Error Code Catalogue (2-column table, 36 rows)

**Coverage audit — scaffold rules I could not render as derivable prose:** none. One deliberate deviation: the scaffold's `campaign_pacing_multiplier` `constants` block names MIN/MAX multipliers and DAY_SECONDS, but its formula body hardcodes only the 0.05 warm-up fraction (and its variants make the lower clamp unreachable). I rendered the constants as named bounds plus "a campaign that has spent nothing halfway through the day receives a multiplier near 1.5" rather than inventing hardcoded values the scaffold does not contain — the formula itself is reconstructed exactly.

Hard Contract reports (transcript-only, not written into PRD.md):

```
Field coverage check:
- entities[].fields: 72 required, 72 present, 0 missing
- endpoints[].request_body: 41 required, 41 present, 0 missing
- endpoints[].query_params: 0 required, 0 present, 0 missing
- endpoints[].path_params: 0 required, 0 present, 0 missing
- errors[]: 36 required, 36 present, 0 missing
- enum values: 45 required, 45 present, 0 missing
- state values: 13 required, 13 present, 0 missing
- roles: 4 required, 4 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 11 checked, 11 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_campaign_version + error_id all named), 0 missing
- state_machines[].transitions: 25 checked, 25 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed, 0 missing
- validations[] conditions: 11 checked, 11 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 42 checked, 42 expressed, 0 missing
- entities[].fields[] structured content: 94 checked, 94 reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 groups checked, 9 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 586
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

result: PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_3292_sponsored_job_budget_pacing_employer_signals_apply/workspace/PRD.md` (349 lines / 11,628 words) covering all 42 endpoints, 13 entities, 5 state machines, 8 calculations, 11 validations and 36 error codes, with all three Hard Contracts reporting PASS and no scaffold rule left underivable.

**Orchestrator verification:** on-disk `workspace/PRD.md` confirmed at 349 lines / 11,628 words with the expected §1–§5 heading structure (42-row endpoint table, 36-row error catalogue). Note for Step 9: the doc-generator flagged the `campaign_pacing_multiplier` constants as a known under-specified spot (MIN/MAX multiplier bounds and DAY_SECONDS named but not hardcoded in the scaffold formula) — this is a likely PRD-silence site to re-check against the implementation.

## Step 5: Generate unit tests — 2026-09-30T19:18:34.000Z

Sanity check complete: 85 tests collect cleanly (no import/syntax errors), the coverage audit reports every one of the 18 queue-A instances at ≥2 tests and all 44 translatable queue-B instances at ≥1, the verbatim check passes on all 107 PRD citation windows, four `excluded_because:` stubs cross-reference to real queue-A instances, and no `skip`/`xfail` or scaffold vocabulary remains. `workspace/implementation/` does not exist yet, so the suite was not executed against a server — that is the expected state at this stage.

**Files generated** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3292_sponsored_job_budget_pacing_employer_signals_apply/`):

`test_helpers/` — 1519 lines total
| file | lines |
|---|---|
| `__init__.py` | 22 |
| `types.py` | 341 |
| `api_client.py` | 162 |
| `api_errors.py` | 89 |
| `assertions.py` | 280 |
| `factories.py` | 145 |
| `constants.py` | 69 |
| `test_users.py` | 49 |
| `fixtures.py` | 362 |

`test_suite/` — 2736 lines total
| file | lines |
|---|---|
| `conftest.py` | 39 |
| `test_01_pacing_and_quality_variants.py` | 165 |
| `test_02_auction_and_commit_split.py` | 138 |
| `test_03_campaign_cycle_and_posting_states.py` | 151 |
| `test_04_transitive_cascades.py` | 179 |
| `test_05_precedence_and_cross_entity_gates.py` | 270 |
| `test_06_boundary_precision.py` | 130 |
| `test_07_temporal_overlap.py` | 133 |
| `test_08_compensating_invariants.py` | 158 |
| `test_09_entity_defaults_and_lookups.py` | 147 |
| `test_10_state_machines.py` | 171 |
| `test_11_quality_signal.py` | 127 |
| `test_12_relevance_scoring.py` | 70 |
| `test_13_validations.py` | 266 |
| `test_14_endpoint_actions.py` | 163 |
| `test_15_listing_and_pagination.py` | 92 |
| `test_16_concurrency.py` | 101 |
| `test_17_errors_and_rbac.py` | 109 |
| `test_18_rollover_and_consistency.py` | 127 |

**Test counts per queue:** Queue A (Difficulty) = **37 tests** covering all 18 instances (≥2 each). Queue B (Corner) = **48 tests** covering 44 non-stub instances (≥1 each); 4 `excluded_because:` stubs not translated, all four cross-references verified to resolve.

**Skipped instances (1), with the two-condition reason:**

- `Corner/entities/job_seeker_create_defaults_location_to_null` — fails **condition 2 (unique derivability)**. PRD §3.1 calls `location` "an optional `location`" but never pins the server-side default. Null, empty string, and field omission are all faithful PRD-only readings, so any concrete assertion would be the `default-value` silence pattern. No placeholder emitted; the gap stays a gap.

Notable fairness decisions applied under the two-condition filter: the two error-precedence scenarios assert a *disjunction* of codes (e.g. `ERR_CAMPAIGN_NOT_ACTIVE`/`ERR_CAMPAIGN_TERMINAL`/`ERR_SPONSORED_JOB_NOT_ELIGIBLE`) rather than a single code, since the PRD pins the winning *tier* but not which code within it fires; similarly the expired-posting resume accepts `ERR_POSTING_NOT_ACTIVE` or `ERR_INVALID_STATE_TRANSITION`.

result: Generated complete test infrastructure for task_3292 — 9 `test_helpers/` modules (1,519 lines) and 19 `test_suite/` files (2,736 lines, 85 tests: 37 queue-A across all 18 difficulty instances, 48 queue-B across 44 of 45 non-stub corners), 1 instance skipped for a PRD default-value silence, all design tags and PRD citations verified.

**Orchestrator verification (independent):** on-disk `test_helpers/` = 1,519 lines across 9 modules, `test_suite/` = 2,739 lines across 19 files, 85 `def test_` functions, 0 `pytest.mark.skip`/`xfail`. Programmatically cross-checked every `Design:` tag against a parse of both design YAMLs: 18/18 queue-A instances tagged and all 18 tags resolve to real instances; 44/45 queue-B instances tagged and all 44 tags resolve; the single un-covered instance is exactly the `job_seeker_create_defaults_location_to_null` skip reported above; 0 tags point at `excluded_because:` stubs. The one discrepancy vs. the subagent's self-report is cosmetic: 5 `excluded_because:` lines exist in the corner file but only 4 are instance-level stubs (the fifth is an additional exclusion note on one instance) — no tag or coverage impact.

## Step 6: Generate implementation — 2026-09-30T19:38:12.000Z

Sanity check complete. Verified: 42/42 routes registered in Flask's URL map against the scaffold's endpoint table, five consecutive clean `bash start.sh` boots with an empty store each time, default-port (10000) bind to 0.0.0.0, guarded pip install (0 re-installs on reboot), no persistence artifacts, no seed code, and 146 self-authored behavior checks passing across two suites.

## What was built

`/home/ubuntu/github/CodingPRD/tasks/task_3292_sponsored_job_budget_pacing_employer_signals_apply/workspace/implementation/`

| Lines | File |
|------|------|
| 88 | `app.py` — blueprint registration, error handlers, boot self-check |
| 61 | `auth.py` — `X-User-ID`/`X-User-Role` extraction, role gate, ownership |
| 89 | `db.py` — in-memory store, logical clock, snapshot/restore |
| 107 | `errors.py` — all 37 error IDs with catalogue statuses |
| 279 | `models.py` — row factories + serializers (mutable vs append-only families) |
| 64 | `response.py` — `meta`/`response_type`/`data` envelope, pagination |
| 194 | `validations.py` — tier-ordered existence/shape/pagination/filter guards |
| 42 × | `routes/` — employers, job_seekers, campaigns, sponsored_jobs, job_postings, assessments, applications, sponsor_events, clock |
| 654 | `services/` — calc.py (all 8 calculations, cascades, rollover), events.py (charge split) |
| 9 | `start.sh` |
| **3301** | total (incl. `requirements.txt`, package `__init__`s) |

**Endpoints implemented: 42**, matching the scaffold's `endpoints:` section one-for-one (verified by dumping Flask's `url_map`, not by counting decorators).

## Notable fidelity decisions
- **Guard precedence** follows PRD §2.8 literally. Fixed a real bug found in testing: `POST /events` was running the general shape check (tier 11) before the OCC check, so a missing `expected_campaign_version` returned `ERR_INVALID_REQUEST` instead of `ERR_MISSING_EXPECTED_VERSION`. `expected_campaign_version` is now validated at tier 10 and excluded from `require_fields`.
- **List ordering** had to be handled deliberately: with a frozen logical clock every row shares `created_at`, so ordering fell back to UUID and made `ApplyEvent` order nondeterministic. Added a monotonic insertion sequence as the tie-break under "creation timestamp ascending".
- **Pacing scope**: `campaign_pacing_multiplier` is pinned at 1.0 while the campaign is DRAFT (PRD §3.3, response-visible), implemented as a campaign-status gate; the auction candidate pool separately requires campaign ACTIVE.
- **Assessment gate**: completion always consults the posting's newest `PUBLISHED` assessment (not only one captured at start), so an application started without `assessment_id` still hits `ERR_ASSESSMENT_SCORE_BELOW_THRESHOLD`; answers are required only when that assessment's threshold exceeds zero.
- Fraud scanning covers the PRD's canonical examples (wire transfer, upfront fee, pay to start) plus close variants like "application fee"/"deposit required".

## Boot verification
Five consecutive `PORT=<n> bash start.sh` cycles: server reachable each time (first within ~1 s), `total_count == 0` for `GET /api/sponsored-jobs` on every boot, no `__pycache__`-external artifacts, and `grep` for seeding/preloading returns only doc-comments. A separate default-port run confirmed `0.0.0.0:10000` and that the `import flask` guard skips `pip install` entirely on re-invocation. All test servers I started were killed by exact PID (verified per-process cwd before signalling) — no broad kill patterns used.

Per the isolation rule, I read only `INSTRUCTION.md`, `SCAFFOLD.yaml` and `PRD.md` plus the skill; `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_suite/` and `test_helpers/` were never opened, no sibling task directory was read, and the benchmark suite was not run.

result: task_3292 sponsored-job-pacing API implemented and verified — 42/42 scaffold endpoints live across 22 files (3301 lines) in workspace/implementation/, in-memory only with no startup seeding, boots cleanly from a fresh process on every `bash start.sh` (verified over 5 consecutive boots + default port 10000 on 0.0.0.0), and 146 self-authored behavior checks covering all 5 state machines, 8 calculations, 11 validation tiers and 37 error codes pass with 0 failures.

**Orchestrator verification (independent — memory flagged that >40 endpoints has historically made Step 6 return a report without writing every file):** on-disk file list confirms all 22 expected files present (no truncation, no missing `routes/`/`services/` modules), 3,292 `.py` lines. I dump-loaded the Flask app myself: `url_map` yields exactly **42** real method+path rules. Grep for seeding/persistence (`sqlite`, `open(`, `pickle`, `shelve`, `/tmp`, bare `.json` writes) returned **zero** hits. I then ran `bash start.sh` twice in fresh processes on ports 10137/10139: both boots served `0.0.0.0`, returned the correct `{meta,response_type,data}` envelope, and `GET /api/sponsored-jobs` as PlatformAdmin returned `total_count: 0` — empty store, no startup seeding. Both servers killed by exact PID. The overshoot risk flagged before Step 6 did not materialise.

## Step 7: Run tests and iterate — 2026-09-30T20:13:22.000Z

Sweep is clean: all 8 parallel rounds report 85/85 with zero failures, zero flakiness.

**Sanity check performed:** re-read the ask (union-of-failures across 8 rounds, PRD-faithful fixes only), confirmed 85 tests still present (0 deleted), 0 `skip`/`xfail`, no `implementation/` writes after the sweep (checked mtimes against `results.1.json`), and no seeding/persistence in `implementation/`.

**Result of iteration 1** (union = 10 tests, all failing deterministically in 8/8 rounds — no timing flakiness):
- `db.py iso()` + `app.py` self-check — whole-second instants rendered as `.000Z`, breaking 3 `day_open_date` assertions.
- test_01 realized-multiplier literals; test_02 competing-employer quality fixture (40 vs 70); test_03 lifetime budget vs 2×daily spend; test_04 hold-status after the commit split; test_13 daily budget below the 1000c BUDGET_HOLD floor; test_15 illegal backwards clock set.

All fixes traced to verbatim PRD sentences (I can cite any on request): PRD §3.2 pacing formulas and the "1.0 by convention" branch, §3.7 tier boundaries and the closed-unanswered population, §3.5 `ERR_TOTAL_BUDGET_EXCEEDED` and the oldest-first hold consumption, §3.3's 1,000-cent BUDGET_HOLD floor, §2.7's forward-only clock, and §2.2's timestamp format. No test was deleted, and no assertion was weakened.

result: task_3292 — 8/8 parallel rounds pass 85/85 (union of 10 deterministic failures fixed: 2 implementation files — timedelta break in db.py iso() + stale app.py boot assert; the rest test_helpers/test_suite fixtures and literals, all re-derived from PRD prose).

Files changed:
- `/home/ubuntu/github/CodingPRD/tasks/task_3292_sponsored_job_budget_pacing_employer_signals_apply/workspace/implementation/db.py` — `iso()` now omits the fractional part on whole-second instants (T00:00:00Z) and keeps 3 digits otherwise.
- `/home/ubuntu/github/CodingPRD/tasks/task_3292_sponsored_job_budget_pacing_employer_signals_apply/workspace/implementation/app.py` — boot self-check expected the old `.000Z` form and crashed every server start.
- `/home/ubuntu/github/CodingPRD/tasks/task_3292_sponsored_job_budget_pacing_employer_signals_apply/test_helpers/fixtures.py` — `setup_competing_employers` rebuilt: `quality_b_low` → `quality_b_middle`, driving employer B to 5000 bps/70 (the old one closed-unanswered app gave base tier 40).
- `/home/ubuntu/github/CodingPRD/tasks/task_3292_sponsored_job_budget_pacing_employer_signals_apply/test_suite/test_01_pacing_and_quality_variants.py` — divergence test now commits half the daily budget at day start so both multipliers are derivable (1.25 vs 0.667).
- `/home/ubuntu/github/CodingPRD/tasks/task_3292_sponsored_job_budget_pacing_employer_signals_apply/test_suite/test_02_auction_and_commit_split.py` — uses the corrected competitor fixture (runner-up rank 210 → price 211).
- `/home/ubuntu/github/CodingPRD/tasks/task_3292_sponsored_job_budget_pacing_employer_signals_apply/test_suite/test_03_campaign_cycle_and_posting_states.py` — lifetime budget 10000 → 12000 so the second 6000c click reaches the terminal condition instead of being rejected.
- `/home/ubuntu/github/CodingPRD/tasks/task_3292_sponsored_job_budget_pacing_employer_signals_apply/test_suite/test_04_transitive_cascades.py` — serving job's hold is COMMITTED (consumed by the commit split), not RELEASED.
- `/home/ubuntu/github/CodingPRD/tasks/task_3292_sponsored_job_budget_pacing_employer_signals_apply/test_suite/test_13_validations.py` — daily budget 400 → 1200 (above the BUDGET_HOLD floor) with bid 1300 to exceed the day.
- `/home/ubuntu/github/CodingPRD/tasks/task_3292_sponsored_job_budget_pacing_employer_signals_apply/test_suite/test_15_listing_and_pagination.py` — removed the clock rewind that PRD §2.7 forbids; filter check now asserts the ACTIVE set.

**Orchestrator verification (independent):** read all 8 `results.{1..8}.json` directly — every round reports `passed 85 / total 85 / failed 0`; mtimes 20:12:37–20:12:40. `find -newermt "2026-09-30 20:12:37"` over `workspace/implementation/`, `test_suite/` and `test_helpers/` returns **zero** files, so no post-sweep write invalidated the sweep (this is the exact failure mode prior pipelines hit). 85 `def test_` functions still present, 0 `pytest.mark.skip`/`xfail`. Spot-checked the two `implementation/` fixes against source: `db.py:28 iso()` now branches on `dt.microsecond == 0` to omit the fractional part, and `app.py:74 _self_check()` asserts the clock is at `CLOCK_START` and all 13 tables are empty at boot (consistent with the no-seeding requirement).

**Step 8 gate:** NOT skipped — Step 7 ran one fix iteration and touched 2 `implementation/` files, 1 `test_helpers/` file and 5 `test_suite/` files. The `<step_7_diff>` handed to Step 8 is the body of this entry.

## Step 8: Finalize PRD — 2026-09-30T20:26:41.000Z

Sanity check passed: PRD_FINALIZED.md is 349 lines (identical to PRD.md, 0% line delta; +763 bytes, +0.98%); the only remaining "three fractional digits" claim (line 47) is the envelope `api_request_timestamp`, which the impl still renders with 3 digits via `response.py::_stamp` — consistent. Implementation compiles.

`result:` Wrote /home/ubuntu/github/CodingPRD/tasks/task_3292_sponsored_job_budget_pacing_employer_signals_apply/workspace/PRD_FINALIZED.md — one logical-clock timestamp-rendering rule applied in two places (§2.4 + §2.7), pinning the whole-second-no-fraction / sub-second-3-digits behavior the impl now exhibits.

## Line counts
- PRD.md: 349 lines / 77,572 bytes
- PRD_FINALIZED.md: 349 lines / 78,335 bytes
- Delta: 0 lines (0%), +763 bytes (+0.98%)

## Changes (2 — both the same subject)
- **§2.4 Resource Identity, Mutable Timestamps and Version Bookkeeping — revise** — replaced "`created_at`, an ISO 8601 UTC timestamp with three fractional digits (for example `2025-05-24T10:30:00.123Z`) ... `updated_at`, a timestamp in the same format" with a two-branch rule: a logical-clock instant exactly on a whole second is rendered with **no** fractional part (e.g. `2026-09-01T00:00:00Z`), otherwise with **exactly three** digits; the rule is scoped to logical-clock timestamps and enumerates the governed fields. Impl: `db.py:28-38` (`iso()`), reached by `models.py:42,58,65`, `routes/campaigns.py:69`, `services/calc.py:532`, `routes/job_postings.py:130,142,246,255`, `routes/applications.py:83,98,190,199,264`, `routes/employers.py:77`, `routes/job_seekers.py:180`, `services/events.py:73`, `routes/clock.py:36-37`.
- **§2.7 The Logical Clock and Day Rollover — insert** — one appended sentence: the clock-setting response's `current_utc` and `day_open_date` are stamped from the logical clock and follow the §2.4 format, so a whole-second instant (a midnight day boundary) carries no fractional part. Impl: `routes/clock.py:36-37`.

## Pre-edit search log
- **Edit 1 (timestamp rendering).** (a) Subject: how a server-minted instant is rendered — presence/width of the fractional part. (b) Paths enumerated and read: `db.py iso()` both branches; every `iso()` caller listed above; plus the independent wall-clock formatter `response.py:21 _stamp()` used only by the envelope `api_request_timestamp` (`response.py:27`). (c) Adjustment: scoped the sentence to *logical-clock* timestamps and listed the fields explicitly, so it does not collide with §2.2's "three fractional digits" claim about the wall-clock envelope `api_request_timestamp` (still 3 digits in the impl). Used a monotonic, non-enumerating phrasing for the general clause to avoid falsely claiming the whole mutable field set is always-sub-second.
- **Edit 2 (§2.7 clock response).** (a) Subject: the timestamp fields returned by `POST /api/_clock/set_current_utc`. (b) Paths enumerated: `routes/clock.py:36-37`; cross-checked the other `day_open_date` producers `routes/campaigns.py:69` and `services/calc.py:532`, both also whole-second `iso()` outputs. (c) Adjustment: none needed beyond keeping it a cross-reference to §2.4 rather than restating a rule that could drift.

## Items deliberately NOT patched (fixture/test bugs, not PRD silence or mismatch)
All Step 7 test/fixture changes trace to sentences already verbatim in the PRD, with no implementation change, so there is nothing to pin: test_01 realized multiplier (§3.2 formulas), test_03 lifetime budget 10000→12000 (§3.5 `ERR_TOTAL_BUDGET_EXCEEDED`), test_02 competitor fixture (§3.7 tier boundaries + closed-unanswered population), test_13 daily 400→1200 (§3.3 1,000-cent BUDGET_HOLD floor), test_15 clock rewind (§2.7 forward-only clock), test_04 hold COMMITTED (§3.5 oldest-first consumption ordering — PRD §3.5 already states the hold becomes `COMMITTED`, impl `services/calc.py:179`). The `app.py` self-check change is internal (boot-time assert, no response-visible behavior) and is covered by Edit 1.

**Orchestrator verification (independent):** `diff workspace/PRD.md workspace/PRD_FINALIZED.md` returns exactly the two hunks described (line 86 §2.4 revise, line 108 §2.7 insert) and nothing else; line counts 349/349, bytes 77,572 → 78,335 (+763). I confirmed the one claim that could have been a hidden new mismatch: `response.py:21 _stamp()` uses `datetime.now()` (wall clock, not the logical clock) and always appends `.%03d`, so PRD line 47's "three fractional digits" statement about `api_request_timestamp` remains accurate and does not contradict the new logical-clock rule.

## Step 9: Complete PRD — 2026-09-30T20:41:12.000Z

Sanity checks pass: PRD structure intact (5 sections, 82 table rows), all 13 list endpoints' filters match the impl's `reject_unknown_query` sets exactly, `reject_unknown_query` fires only on list endpoints (confirming the §2.3 claim), and Python's stable sort preserves insertion order for the auction residual tie (confirmed empirically). I also caught and fixed two draft claims that grep disproved (matches-view and serving-job selection both fall back to `id`, not insertion order). I read only the allowed files — never SCAFFOLD*.yaml or worklog.md — and edited only `workspace/PRD_COMPLETED.md`.

`result:` PRD_COMPLETED.md written — a minimal patch over PRD_FINALIZED.md pinning 37 ambiguities and correcting 7 mismatches against `implementation/`.

**Source vs output**
- `PRD_FINALIZED.md`: 349 lines, 78,335 bytes (78,158 chars)
- `PRD_COMPLETED.md`: 351 lines, 94,338 bytes (94,095 chars)
- Delta: +2 lines, +15,937 chars; 41 lines revised, 43 inserted across §2, §3 and §4. No sections added or removed.

**Counts:** 37 ambiguity-pins, 7 mismatch-revisions (44 edit sites).

**Changes** (`{PRD section} — {insert|revise} — {ambiguity|mismatch} — {what changed} — {impl file:line}`)

- §2.3 — insert — ambiguity — list tie-break is insertion order, `id` never used; empty query param = omitted; query params interpreted only by list endpoints — `implementation/validations.py:189-195, 142-150, 165-169`
- §2.4 — insert — ambiguity — new resource starts at `version` 1, `updated_at` == `created_at` — `implementation/models.py:39-47`
- §2.5 — insert — ambiguity — RELEASE sets hold `RELEASED`, null `sponsor_event_id`, negated amount — `implementation/services/calc.py:432-445`
- §2.6 — insert — ambiguity — multiplier conversions are exact; clamp applied after bounding never alters value — `implementation/services/calc.py:23-32, 60-66`
- §2.7 — revise — mismatch — clock body field `current_utc`; deleted "any operation whose timestamps push the clock across midnight"; rollover fires only via clock-set — `implementation/routes/clock.py:14-34`, `services/calc.py:544-551`
- §2.8 tier 11 — insert — ambiguity — integer fields require JSON integers (bool/string rejected) — `implementation/validations.py:92-96`
- §2.8 consequences — revise — mismatch — added existence-before-ownership (nonexistent target ⇒ not-found, not 403); state-before-bid precedence — `implementation/validations.py:37-44`, `auth.py:43-55`, `routes/sponsor_events.py:46-82`
- §2.9 — insert — ambiguity — `expected_campaign_version` is a body field; non-integer ⇒ `ERR_MISSING_EXPECTED_VERSION` — `implementation/routes/sponsor_events.py:73-82, 143-154`
- §3.1 — insert — ambiguity — seeker email uniqueness is case-insensitive ⇒ `ERR_INVALID_REQUEST` — `implementation/routes/job_seekers.py:35-38`
- §3.1 — insert — ambiguity — HOSTED discards a supplied `apply_redirect_url` to null — `implementation/routes/job_postings.py:108-109`
- §3.1 — insert — ambiguity — snapshot stores `external_posting_id`/`content_hash`/`ingested_at`/`freshness`; ingestion does not rewrite posting content — `implementation/models.py:172-181`, `routes/job_postings.py:241-254`
- §3.1 — insert — ambiguity — 30-day replay window measured on whole days — `implementation/routes/job_postings.py:219-230`, `services/calc.py:370-374`
- §3.1 — insert — ambiguity — dedupe location normalised casefold+whitespace; empty ext-id slot; creation path also rejected — `implementation/models.py:76-85`, `routes/job_postings.py:111-118, 232-239`
- §3.1 — insert — ambiguity — fraud scan is case-insensitive substring; missing acting employer ⇒ `ERR_EMPLOYER_SUSPENDED` — `implementation/routes/job_postings.py:40-45, 55-60`, `routes/sponsored_jobs.py:74-77`
- §3.1 — insert — ambiguity — whole assessment shape (empty, negative threshold, malformed element) ⇒ `ERR_UNSUPPORTED_ASSESSMENT_QUESTIONS` — `implementation/routes/assessments.py:33-61`
- §3.1 — insert — ambiguity — suspend of non-ACTIVE ⇒ `ERR_INVALID_STATE_TRANSITION` — `implementation/routes/employers.py:70-74`
- §3.1 — insert — ambiguity — reinstate clears `suspended_at`/`suspension_reason`; snapshot-less posting stays DRAFT — `implementation/routes/employers.py:115-135`
- §3.2 — insert — ambiguity — negative budget ⇒ `ERR_INVALID_REQUEST` — `implementation/routes/campaigns.py:44-46`
- §3.2 — insert — ambiguity — activate of non-DRAFT ⇒ `ERR_INVALID_STATE_TRANSITION` — `implementation/routes/campaigns.py:96-98`
- §3.2 — insert — ambiguity — scheduled multiplier short-circuits to exactly 1.0 when day exhausted — `implementation/services/calc.py:53-55`
- §3.2 — insert — ambiguity — out-of-scope campaigns report exactly 1.0 — `implementation/services/calc.py:49-52`
- §3.2 — revise — mismatch — realized multiplier is not gated on `day_open_date`; other statuses ⇒ 1.0 — `implementation/services/calc.py:72-80`
- §3.2 — revise — mismatch — daily exhaustion transition only fires from ACTIVE — `implementation/services/events.py:29-31`
- §3.2 — insert — ambiguity — pause non-ACTIVE/PACING_HOLD ⇒ transition error; resume at total budget ⇒ `ERR_CAMPAIGN_TERMINAL` — `implementation/routes/campaigns.py:121-146`
- §3.3 — insert — ambiguity — multipliers refreshed on sponsored-job reads — `implementation/routes/sponsored_jobs.py:34-41, 135, 145`
- §3.3 — revise — mismatch — direct BUDGET_HOLD entry is campaign-capacity-driven and scoped to ACTIVE/PACING_HOLD; revival also needs posting ACTIVE — `implementation/services/calc.py:480-497`
- §3.4 — insert — ambiguity — residual tie on all three keys ⇒ insertion order (stable sort) — `implementation/services/calc.py:121-131`
- §3.4 — insert — ambiguity — pool independent of bidding job; absent bidder ⇒ highest-ranked candidate as runner-up — `implementation/services/calc.py:134-159`
- §3.5 — insert — ambiguity — device/ip opaque and nullable; COMPLETED ⇒ `ERR_CAMPAIGN_TERMINAL`; inactive posting ⇒ `ERR_SPONSORED_JOB_NOT_ELIGIBLE`; no campaign/job consistency required — `implementation/routes/sponsor_events.py:46-56`
- §3.5 — insert — ambiguity — capacity guards are strict `>` and billable-only — `implementation/routes/sponsor_events.py:65-70`
- §3.5 — insert — ambiguity — partially consumed hold records `sponsor_event_id`; holds ordered by `created_at` only, no id tie-break — `implementation/services/calc.py:167-184`
- §3.5 — revise — mismatch — removed nonexistent "minimum hold unit"; amount < 1 ⇒ `ERR_INVALID_REQUEST`; campaign-state gate first; budget check before overlap; hold stamped with campaign `day_open_date` — `implementation/routes/sponsored_jobs.py:201-236`
- §3.6 — insert — ambiguity — assessment/posting mismatch ⇒ `ERR_ASSESSMENT_NOT_FOUND`; score semantics; score 0 with no answers; bad answers type ⇒ `ERR_INVALID_REQUEST` — `implementation/routes/applications.py:66-76`, `routes/assessments.py:73-117`
- §3.6 — revise+insert — ambiguity — CLOSED ⇒ `ERR_APPLICATION_ALREADY_TERMINAL`; governing assessment is the newest PUBLISHED; missing answers ⇒ `ERR_INVALID_REQUEST`; zero-threshold back-fill — `implementation/routes/applications.py:160-187`
- §3.6 — insert — ambiguity — serving job is earliest-created ELIGIBLE (id tie-break); null device/ip; CPC ⇒ RECORDED — `implementation/services/events.py:8-21, 87-104`
- §3.6 — revise — mismatch — close of CLOSED ⇒ terminal error, other states ⇒ state error; closing appends no ApplyEvent; INVALID_CLICK/PIXEL never emitted — `implementation/routes/applications.py:217-223`
- §3.6 — revise+insert — mismatch — disposition allowed from COMPLETED or RESPONDED; CLOSED ⇒ terminal; NONE/other ⇒ `ERR_INVALID_REQUEST` — `implementation/routes/applications.py:251-260`
- §3.7 — insert — ambiguity — application belongs to the posting's employer; empty population sets rate 0 and leaves score unchanged — `implementation/services/calc.py:242-258`
- §3.8 — revise+insert — ambiguity — non-empty `reason`; guard order; inclusive 24h window; duplicate-claim keyed on a REFUNDED event inside the window; null fingerprint exempt — `implementation/routes/sponsor_events.py:117-154`
- §3.8 — insert — ambiguity — REFUND entry attributed via `sponsor_event_id`; PACING_HOLD → ACTIVE on restored capacity — `implementation/routes/sponsor_events.py:156-179`
- §3.9 — insert — ambiguity — subscription filters required but may be empty ⇒ stored `""` — `implementation/routes/job_seekers.py:130-141`
- §3.9 — insert — ambiguity — matches item = posting object + `relevance_score`; tie-break `created_at` then `id` — `implementation/routes/job_seekers.py:92-99`, `services/calc.py:355-361`
- §3.9 — insert — ambiguity — unresolved `subscription_id` ⇒ `ERR_INVALID_REQUEST`; non-delivering subscriptions untouched; all eligible postings delivered; object shape — `implementation/routes/job_seekers.py:149-189`
- §4 — insert — ambiguity — enumerates each list endpoint's exact filter parameters — `implementation/routes/{campaigns,job_postings,employers,sponsored_jobs,job_seekers,applications}.py`

**Orchestrator verification (independent):** on-disk `PRD_COMPLETED.md` = 351 lines / 94,338 bytes, `PRD_FINALIZED.md` = 349 / 78,335 → +2 lines and +15,937 chars, matching the report; the §1–§5 heading structure is intact (25 headings, no section added or removed). Critically, `find -newermt "2026-09-30 20:12:37"` over `workspace/implementation/`, `test_suite/` and `test_helpers/` again returns **zero** files — Steps 8 and 9 wrote only PRD documents, so the Step 7 clean sweep is still the authoritative test result and was not invalidated.

## Final confirmation — 2026-09-30T20:46:22.711Z

Artifact state is frozen: Steps 8 and 9 wrote only `workspace/PRD_FINALIZED.md` and `workspace/PRD_COMPLETED.md`, so the recorded 8-round sweep (`results.1.json`…`results.8.json`, all `passed 85 / total 85 / failed 0`) remains valid. As an extra end-to-end check I then re-ran ONE further isolated round via `prd-bench-local-run --isolation per-test-server` against exactly the shipped files, writing to a scratch path so the recorded sweep was left untouched: **85 / 85 passed, 0 failed** (exit 0). Task directory is complete — SCAFFOLD trio, worklog, `test_helpers/` (9 files), `test_suite/` (19 files), and `workspace/` (INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ with `start.sh` + 21 source files + the 8 sweep result files).
