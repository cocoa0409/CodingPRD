# Worklog — task_2844_game_localization_content_rating_submission

## Step 1: Create task directory — 2026-09-05T05:47:16.368Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2844_game_localization_content_rating_submission and its workspace/ subdirectory. Index 2844 was pre-assigned by the invocation; no scan of ./tasks/ was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T07:29:00.000Z

Subagent summary (verbatim):

All 12 entities declare `common_fields: true`, so the guide's Immutability row (Table 1, `common_fields: false`) is correctly not applicable — no missing §1.9 instance there. All three artifacts are final and verified.

## Generated artifacts

`/home/ubuntu/github/CodingPRD/tasks/task_2844_game_localization_content_rating_submission/`

| File | Lines | Bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 2813 | 146,909 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2318 | 149,805 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4232 | 277,346 |

**SCAFFOLD.yaml (§1.0–§1.7)** — 12 entities, 63 endpoints, 50 errors, 10 calculations, 10 state machines, 7 roles, 20-rule ordered validation ladder (priorities 10→70). `domain_name: game-localization-rating-submission`. Profile: `difficulty_level: expert_plus`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`, `entity_topology: flat`, `state_machine_shape: cyclic`, `role_model: segregation_of_duties`, `consistency_model: immediate`. Contains neither design key.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — single top-level key; all 9 rule_ids, 23 instances (dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2) — clears the >=2-per-rule / >=18 floor.

**SCAFFOLD_CORNER_DESIGN.yaml** — single top-level key; 82 instances across all nine guide sections (entities 12, state_machines 10, calculations 13, validations 9, endpoints 5, errors 21, rbac 4, cross_cutting_complexity_layers 7, consistency_model 1). 58 carry full `test_recipe`s; 24 are `excluded_because` stubs, each naming a real §1.8 instance and each carrying `name` + `claim_type` + `grounds` with no recipe.

## Verification

- `scaffold_lint.py` -> **clean lint**: 1148 §1.8+§1.9 calls scanned against 63 endpoints; all six fatal checks pass (endpoint declared, role allowed, payload shape, capture resolution, `expected_*_version` always `${...}`, FK reverse-reachability).
- Error coverage audit -> `errors with NO asserted trigger: []` — every one of the 50 codes is reachable and asserted.
- Structural audit -> no duplicate instance names, every stub's §1.8 reference resolves, no stub has a `test_recipe`.
- Every §1.9 numeric literal was computed by executing the §1.3 formulas (e.g. effort units 0.20/0.40, costs 840/1680/3024, defect densities 0.0400/0.2000/0.7000, submission fees 456000/403750, committed contract fee 409000, budget overage 20 against a 400-cent cap).

## Notes for the caller

1. **Deliberately over-band**: 63 endpoints and 50 errors exceed the Expert band (20–32 endpoints / 18–30 errors), accepted because the directive is "harder than expert level". 24 endpoints are the GET-one + GET-list pairs that lint check (f) mandates for FK reverse-reachability, and 12 errors are the per-entity `*_NOT_FOUND` set.
2. `api_prefix: ""` — deliberately empty rather than SKILL.md's `"/top-level-resource-path"` template value; the domain has many co-equal top-level resources. All 63 paths and all 1148 calls are unprefixed and consistent.
3. `scenario:` retains the leading `Generate task harder than expert level!` line verbatim as instructed — the pipeline should strip that line after Step 2 so it does not reach PRD.md.
4. No sibling `task_*/` directory was read at any point; the design derives solely from the scenario text and the generator skill spec.

### Orchestrator post-step actions

- Per the subagent's note 3 and known leak mode, the orchestrator stripped the leading `Generate task harder than expert level!` line (and its blank line) from SCAFFOLD.yaml's `scenario:` block so the difficulty directive cannot reach PRD.md. Verified `grep -c "harder than expert" SCAFFOLD.yaml` == 0.
- Verified all three YAMLs parse with `yaml.safe_load`; SCAFFOLD.yaml has neither design key, and each design file has exactly its single top-level key.
- Verified workspace/ still exists and was not wiped by the scaffold subagent.

## Step 3: Copy shared files — 2026-09-05T07:33:00.000Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T07:47:00.000Z

Subagent summary (verbatim):

PRD generation for task 2844 is complete.

**Output:** `workspace/PRD.md` — **485 lines, 95,833 chars**

**Section list**
```
## 1. Introduction
## 2. Global Specifications & System-Wide Principles
### 2.1. Actors, Identity Headers and Role-Based Access Control
### 2.2. API Response Structure                      (byte-identical to the fixed contract file — diff verified)
### 2.3. Pagination and List Ordering
### 2.4. Common Resource Properties, Path Resolution and the Logical Clock
### 2.5. The Rejection Ladder: Validation Precedence
### 2.6. Optimistic Concurrency on the Two Supersede-Capable Creates
### 2.7. Uniqueness Constraints
### 2.8. Precision, Rounding and Conserved Quantities
### 2.9. Regional Compliance Reference Data
### 2.10. Cascade Discipline and Compound State
## 3. Business Logic & Workflows
### 3.1. Registering a Title and Building the Source String Set
### 3.2. Market Scope Decisions and the Translation Effort Estimate
### 3.3. Handing a Market to the Vendor: Translation Units on Two Independent Axes
### 3.4. Voice Talent, Booths and the Recording Calendar
### 3.5. Booking, Running and Reversing Recording Sessions
### 3.6. Quality Assurance Passes, Defect Triage and the Density Gate
### 3.7. Filing a Rating Package, Board Review and Outcomes
### 3.8. Content Edits and the Deepest Cascade in the System
### 3.9. Release Readiness, the Simultaneous-Release Gate and Blocking a Market
## 4. Endpoint Definitions
## 5. Error Code Catalogue
```

**Coverage confirmation**
- Endpoints: 63/63 in the §4 table (65 `^| ` rows = 63 + header + separator), each with a §3 narrative.
- Error codes: 50/50 in §5 with HTTP statuses; all 50 also referenced in §2/§3 prose.
- Calculations: 10/10 in precise prose, including both dual-variant pairs (`SCOPE_ESTIMATE`/`DELIVERED_ACTUAL` effort, `SELF_ASSESSED`/`BOARD_ADJUSTED` risk), the pinned per-key-1dp-then-sum-2dp rounding order, and the pinned fee order where the discount tier keys on the pre-discount subtotal only.
- State machines: 10/10, all 50 transitions with preconditions and side-effects; both TranslationUnit axes; the 7-hop content-edit cascade; the two conserved quantities (`committed_fee_cents`, `reserved_minutes_total`).
- Validation rules: all 26 priority rungs as one ordered ladder in §2.5, with the three declared co-violable precedence pairs called out and every `applies_to` scope enumerated.

**Hard Contracts (transcript only — never written into PRD.md)**
- Contract 1 Field-Name Coverage **PASS** — entities[].fields 108/108, request_body 68/68, query_params 30/30, path_params 12/12, errors 50/50, roles 7/7, 39 state values, 108 enum values; 0 missing in every category.
- Contract 2 Rule Coverage **PASS** — every priority, OCC rule (`expected_market_plan_version`/`expected_voice_talent_version` -> `ERR_STALE_MARKET_PLAN_VERSION`/`ERR_STALE_TALENT_VERSION`, 412), transition, formula, `applies_to` scope, and field default is uniquely determined by the prose; sibling branches given equal density. Fuzzy-word scan: none. Operator/pseudocode scan: none.
- Contract 3 §3 Path Purity **PASS** — 1086 backtick tokens in §3; 0 begin with `/`, 0 bare HTTP methods, 0 method+path combinations.

**Verbatim last two lines**
```
| `ERR_MAX_APPEALS_EXCEEDED` | 422 |
| `ERR_BUDGET_OVERAGE` | 422 |
```
The file ends on the completed final row of the §5 catalogue — a real section boundary, not mid-sentence or mid-table.

Isolation constraint honored: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was read.

### Orchestrator verification (truncation guard)

- `wc -lc` = 485 lines / 95,833 chars. `tail -25` ends on the completed final table row `| \`ERR_BUDGET_OVERAGE\` | 422 |` — a real section boundary, not mid-sentence. No regeneration needed.
- Independent cross-check of error coverage: 51 distinct `ERR_*` tokens in SCAFFOLD.yaml, 50 in PRD.md; the only difference is `ERR_XXX`, a template placeholder in the scaffold's own commentary, not a real code. Real coverage is 50/50.
- Section-heading scan confirms all five top-level sections present and ordered.
- Difficulty-directive leak check: `grep -in "harder than expert|expert_plus|scaffold" PRD.md` returned nothing. The directive did not reach the PRD.

## Step 5: Generate unit tests — 2026-09-05T09:00:00.000Z

Launched CONCURRENTLY with Step 6 in a single assistant message, per the skill, so the implementation generator was physically unable to read test_suite/ (the directory did not exist at its spawn).

Subagent summary (verbatim):

Stage 1 and Stage 2 are complete and verified.

## Files written (all at the task root, nothing under `workspace/`)

`test_helpers/` — 9 modules, 2,610 lines: `__init__.py` 34, `api_client.py` 346, `api_errors.py` 141, `assertions.py` 323, `constants.py` 255, `factories.py` 376, `fixtures.py` 716, `test_users.py` 92, `types.py` 177.

`test_suite/` — `conftest.py` 26 plus 19 test modules, 8,856 lines total: test_01 211, test_02 182, test_03 237, test_04 229, test_05 139, test_06 291, test_07 280, test_08 355, test_09 269, test_10 248 (queue A); test_11 695, test_12 686, test_13 1011, test_14 559, test_15 654, test_16 1128, test_17 890, test_18 489, test_19 277 (queue B).

## Coverage

**170 tests**, each carrying exactly one `Design:` line as the final docstring line — verified mechanically (0 problems): 79 unique tags, every tag resolving to a real non-stub instance, no stub tag, no dual tag, no untagged test, no `skip/skipif/xfail`, no "scaffold" mention, and every quoted docstring sentence confirmed a verbatim substring of `workspace/PRD.md`.

- Queue A (Difficulty): 22 of 23 instances, 56 tests.
- Queue B (Corner): 57 of 58 non-stub instances, 114 tests (entities 11/12, state_machines 8/8, calculations 9/9, validations 7/7, endpoints 5/5, errors 9/9, rbac 4/4, cross_cutting 3/3, consistency_model 1/1). None of the 24 `excluded_because:` stubs was translated.

## Instances SKIPPED (2, both non-unique-derivability)

- `Difficulty/non_linear_state_machine/rating_submission_appeal_cycle_terminates_at_max_appeals` — an appeal needs an `APPLIED` content edit, edits may only be proposed from `EDITS_REQUIRED`, and there is no `EDITS_REQUIRED -> RATED` path, so a `RATED` submission can never carry one; the precondition chain is unreachable.
- `Corner/entities/market_plan_create_missing_required_scope_tier_returns_invalid_request` — §3.2 declares `scope_tier` "null until scoped", so an omitted value is as readable as the legal null case as it is a missing-required-field violation; the yaml's 400 `ERR_INVALID_REQUEST` is not forced by the PRD.

## Design-yaml literals corrected against the PRD

Cultural surcharge floor 1,500,000 (not 150,000); instance-6 bug class/link fixed; instance-11 non-empty disclosure and `fee_cents` 0 (not null); instance-13 overage 1,419,152 plus a missing signed contract and closed LINGUISTIC pass; instance-15 `projected_rating_band` null at submit; instance-17 needed a second unsigned-contract talent because the voiced hand-off demands a `SIGNED` contract; instance-18's `PLANNING`+`SCOPED` pair is unreachable, replaced by a `SHIPPED` title; instance-19 missing closed LINGUISTIC pass. Queue B additions: `blocked_reason` is an enum (`LEGAL_RESTRICTION`/`RATING_TOO_STRICT`/`CERT_DEADLINE_MISSED`), not free text; TM band sums re-derived to 3.70 units / 15,540 cents (yaml said 3.50 / 14,700); several recipes' `target_char_count` values contradicted §3.3's recompute-from-text rule and were replaced by strings of the real asserted length; `POST /_clock/set_current_utc` returns `{current_utc}`, not `{message}`; talent day-minutes are only readable via `reserved_minutes_on_clock_date`, so the clock is moved before asserting 180; absolute `version` literals were replaced by deltas plus unchanged-row checks, since the PRD does not uniquely settle whether every cascade touch bumps a parent; the qa-mark "overflow waiver" step in `errors` instance 7 was dropped as non-derivable (§3.3 allows `PASSED` only at zero overflow) and replaced by a fully derivable reject/re-close variant.

`python3 -m py_compile` passes on all 29 files, a reflection pass confirms every referenced `E./A./C./f./fx./users.` attribute and every `api.<method>` exists, and there is no string-typed money, date-only instant, or `["data"]` double-unwrap anywhere. `worklog.md` was not touched, nothing under `workspace/implementation/` was read or written, and no `__pycache__` or scratch artifacts remain in the task tree.

### Orchestrator verification

- test_helpers/ and test_suite/ both landed at the TASK ROOT; `ls workspace/` shows only INSTRUCTION.md, PRD.md, implementation/ — no stray copies under workspace/ (a known Step 5 failure mode).
- Independent count: 170 test functions across test_suite/*.py; `Design:` tag census = 114 Corner + 56 Difficulty = 170, i.e. exactly one tag per test.

## Step 6: Generate implementation — 2026-09-05T08:47:00.000Z

Launched concurrently with Step 5 (same assistant message). Read only INSTRUCTION.md + SCAFFOLD.yaml + PRD.md; test_suite/ did not exist at spawn time.

Subagent summary (verbatim):

All modules are written, compiled, and smoke-tested. Final state:

## Modules written (all under `workspace/implementation/`)

| File | Lines |
|---|---|
| `start.sh` (chmod +x) | 11 |
| `requirements.txt` | 1 |
| `app.py` | 68 |
| `constants.py` | 220 |
| `db.py` | 186 |
| `errors.py` | 132 |
| `middleware.py` | 73 |
| `validation.py` | 198 |
| `response.py` | 98 |
| `serialize.py` | 254 |
| `derive.py` | 587 |
| `routehelp.py` | 43 |
| `routes/__init__.py` | 30 |
| `routes/titles.py` | 117 |
| `routes/string_keys.py` | 105 |
| `routes/market_plans.py` | 303 |
| `routes/translation_units.py` | 128 |
| `routes/voice.py` | 439 |
| `routes/qa_passes.py` | 130 |
| `routes/lqa_bugs.py` | 207 |
| `routes/rating_submissions.py` | 251 |
| `routes/content_edits.py` | 211 |
| `routes/clock.py` | 26 |

Total 3,818 lines. `python3 -m py_compile` clean on every `.py`; `__pycache__` removed afterwards.

## Endpoint coverage
**63 endpoints routed — machine-verified.** I extracted the PRD §4 table (63 rows) and diffed it against `app.url_map`: exact match on every method+path, zero differences. Separately, the 50 error ids and their HTTP statuses were diffed against the PRD §2.4 error table: exact match.

## Smoke tests (port 39844, killed by recorded PID only)
Three scripted suites, ~138 assertions, **0 failures**:
- **Workflow/auth/pagination (87 checks):** full title -> keys -> lock-strings -> plan -> scope -> start-localization -> PUT/deliver -> enter-lqa -> QA pass -> bug lifecycle -> close -> submission -> submit -> begin-review -> record-outcome -> mark-release-ready -> title SHIPPED/CLEARED; plus voice slice (booth geometry 12:29 rejected / 12:30 accepted, 210 reserved minutes, aggregate talent cap exactly-at-cap accepted, complete -> 9600 line fee -> committed 509600, RECORDED-cancel 5-hop reversal), clock endpoint inline object, RBAC/ownership/SoD/OCC/404/409/412/pagination edges.
- **Content-edit cascade (30 checks):** all 7 hops verified individually (unit revert, key RETIRED, plan LQA->IN_LOCALIZATION, pass reopen_count 1, VERIFIED->TRIAGED with density back up, title CERT_WINDOW->STRINGS_LOCKED), plus withdraw-cascades-proposed-edits and cross-parent 422.
- **Arithmetic (21 checks):** SCOPE_ESTIMATE 17.00 vs DELIVERED_ACTUAL 18.20 (per-row 1dp then 2dp), cost/cap/overage, cultural floor surcharge, fee 456,000 (CERO r1/122d), density boundary 0.0500 refused then 0.0250 accepted, gate posture AT_RISK on clock move.

Restart idempotence: three consecutive kill->relaunch cycles each answered HTTP 200 in **~0.57 s** with `total_count = 0`.

## No seeded data
Storage is 12 plain dicts in `db.Store` plus the logical clock (`2026-08-01T00:00:00Z`); nothing is inserted at import or boot, and there is no SQLite/JSON/`/tmp` persistence — confirmed by grep and by every collection returning `[]` on a fresh boot.

## Two decisions worth flagging to the orchestrator
1. **Cultural surcharge floor changed to 1,500,000 cents.** PRD §3.2 prose says "the greater of 1,500,000 cents and fifteen per cent...", while SCAFFOLD.yaml's `CULTURAL_FLOOR_CENTS: 150000` and its worked example say 150,000. I followed the PRD (the stated source of truth); the constant carries a comment quoting the line. If the test suite was generated from the scaffold example, this single constant is the one-line flip.
2. **Content-edit apply hop 4 fires when the edit un-delivered any previously DELIVERED unit**, not on the bare `delivered < required` inequality — because hop 3's key retirement lowers `required_unit_count` by the same amount, so a REMOVE_CONTENT edit over fully-delivered units would otherwise never drag the plan out of LQA and hops 4-7 would silently no-op (this was caught by the cascade smoke test).

Also applied: `derive.cancel_session_cascade` hop 4 narrowed to the voice-quota comparison per PRD §3.5. `worklog.md` untouched; scratch confined to `/tmp/task_2844_implstage/`; no test suite/helper directory was read.

### Orchestrator note on the flagged cultural-floor discrepancy

Steps 5 and 6 ran in isolation from each other, yet BOTH independently resolved the SCAFFOLD-vs-PRD cultural-floor conflict the same way — in favour of the PRD's 1,500,000 cents (impl constant + test literals). This is the correct PRD-First resolution and means the conflict should NOT surface as a Step 7 failure. Recorded here because it is a genuine doc-generator/scaffold divergence worth reporting upstream.

## Step 7: Run tests and iterate — 2026-09-05T09:29:00.000Z

Subagent summary (verbatim):

All 8 rounds green: **170/170 passed in every round**, 0 failed / 0 errors / 0 skipped.

## Summary

**Iterations run:** 2 (each a parallel 8-round `setsid nohup` stability sweep, all rounds run to completion, diagnosed only from `results.$i.json`).

Iteration 1 was 168/170 in **all eight** rounds with an identical, fully deterministic failing pair (no flakiness, no load-induced timeouts, no reaping):

**Tests deleted:** none. Both failures were test-layer bugs; no assertion was weakened to an HTTP status, no skip/xfail added.

**Fixes applied to `test_suite/`** (no `test_helpers/` change was needed — factories already emit integer cents and full ISO-8601 instants, and `assertions.normalize_instant` already canonicalises fractional-second width):

1. `test_suite/test_16_error_catalogue.py` — helper `_two_titles_one_owning_the_menu_key`. It returned the *creation-response* snapshot of `title_a` as the "unchanged by the refused write" baseline, but setup then adds `menu.start`, and PRD §3.1 requires that "Every new key starts in `status` `EXTRACTED` and increments the title's `extracted_key_count`" — a title mutation that legitimately moves `version` 1 -> 2. So `A.assert_unchanged_row` in `test_a_reused_title_code_is_refused_across_the_whole_system` was blaming the 409 for a version bump the *setup* had caused. Fix: re-read `title_a` after setup so the baseline is the post-setup state. The PRD-required side effect on the implementation was left untouched.

2. `test_suite/test_08_cross_entity_state_dependency.py` — `test_the_hand_off_materialises_the_units_in_string_key_created_at_order`. STEP 1c partial-coverage split: the exact positional ordering assertion was dropped (replaced by set equality on `string_key_id` plus `A.assert_created_at_ascending`); every other assertion (one unit per LOCKED key, all seven opening field defaults, `required_unit_count`/`delivered_unit_count`, plan version bump) was kept verbatim. Reason — **PRD self-contradiction, so the assertion is not uniquely derivable**: §3.2 says "Units are created in ascending string-key `created_at` order, so a subsequent listing filtered by `market_plan_id` returns them in that same order", while §2.3 names *that very cascade* as the case where "two rows can share an identical `created_at`", with the tie broken by "the `key_name` of the string key it points at". For this test's key pair those two rules disagree (`hud.ammo` < `menu.start` alphabetically, but `menu.start` was created first), so a faithful PRD-only implementer can land on either order. Docstring now records the conflict.

**Fixes applied to `implementation/`:** none. The implementation was already correct on every diagnosed point — including the known PRD-vs-scaffold divergence (`constants.py: CULTURAL_FLOOR_CENTS = 1500000`, following PRD §3.2, not the scaffold's 150,000), the discount tier keyed on the pre-discount subtotal, in-memory-only storage with nothing seeded, and the §2.3 natural-key tie-break which I deliberately did not change to chase the ambiguous ordering assertion.

**Final round tallies:** round 1 170/170 · round 2 170/170 · round 3 170/170 · round 4 170/170 · round 5 170/170 · round 6 170/170 · round 7 170/170 · round 8 170/170 (~322 s per round).

`worklog.md` was not touched.

### Orchestrator verification

- Independently re-read all 8 `workspace/implementation/results.*.json` after the agent exited: every file reports `passed == total == 170`. The clean sweep artifacts genuinely exist on disk (guarding against a subagent claiming a green sweep without leaving results behind).
- Step 8 decision: NOT skipped. The skip condition requires 0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes; Step 7 made 2 `test_suite/` fixes across 2 iterations, so Step 8 runs with those two items as its `<step_7_diff>`.
- Noted for Step 8/9: Step 7 applied ZERO implementation fixes, so a byte-identical PRD_FINALIZED.md would be a legitimate outcome for Step 8 (there is no impl-side behavioural change to document). Item 2 does, however, record a genuine PRD self-contradiction between §2.3 and §3.2 on cascade ordering, which Step 8 should reconcile toward what the implementation actually does.

## Step 8: Finalize PRD — 2026-09-05T09:34:00.000Z

Not skipped: Step 7 made 2 `test_suite/` fixes over 2 iterations, so the skip condition (zero of everything) did not hold. The Step 7 worklog entry above was inlined verbatim as `<step_7_diff>`.

Subagent summary (verbatim):

Done. Both Step 7 diff items resolved with three inline edits, no line-count change.

## Line counts
- `PRD.md`: 485 lines / 95,833 bytes
- `PRD_FINALIZED.md`: 485 lines / 96,910 bytes
- Line delta: 0% (all edits are inline inside existing paragraphs); byte delta +1.12%

## Changes

- **§3.3 (hand-off cascade, diff item 2)** — *revise* — replaced "Units are created in ascending string-key `created_at` order, so a subsequent listing filtered by `market_plan_id` returns them in that same order" (the half of the PRD self-contradiction that §2.3 refutes) with: the server iterates locked keys in string-key `created_at` order, but every unit of the plan is created inside the one request and so shares an identical `created_at`, therefore a `market_plan_id`-filtered listing is ordered entirely by the §2.3 tie-break — ascending `key_name` of the linked string key — which need not match key-extraction order. §2.3 left verbatim. — `implementation/routes/market_plans.py:168-182`, `implementation/db.py:122-152`, `implementation/response.py:78-80`, `implementation/serialize.py:220-222`
- **§3.1 (title derived counters, diff item 1)** — *insert* — pinned that `extracted_key_count`, `market_plan_count` and `ready_market_count` are stored (not read-time derived) and refreshed in the same request, so a refresh that changes any of them is a title-row mutation that increments the title's `version` (string-key creation via `extracted_key_count`, market-plan creation via `market_plan_count`); a refresh that changes none of the three and leaves `string_lock`/`release_gate_state` alone contributes no increment. — `implementation/derive.py:135-152`, `implementation/routes/string_keys.py:53`
- **§2.4 (id/timestamps/version paragraph)** — *insert* — one sentence: however many hops of a single request mutate the same row, that row's `version` advances by exactly 1 in total for that request. Required so the new §3.1 sentence cannot be read as double-counting the title in multi-hop cascades. — `implementation/db.py:131-142` (`touch()` per-request dedupe via `g.touched`; the only writer of `version`)

## Per-edit pre-edit search log

**Edit A — §3.3 ordering.** (a) Subject: ordering of translation units in listings and same-request `created_at` ties. (b) Enumerated: `response.py:78-98` `sort_rows`/`paginated` (the single ordering implementation); all 12 `paginated(...)` callsites (`titles.py:78`, `market_plans.py:119`, `string_keys.py:72`, `translation_units.py:41`, `qa_passes.py:82`, `lqa_bugs.py:107`, `rating_submissions.py:131`, `content_edits.py:111`, `voice.py:93,131,205,359`) — all use the uniform `(created_at, natural_key)` rule, so §2.3 stays correct and untouched; `serialize.py:208-254` all twelve natural keys, confirming `nk_translation_unit` = linked `key_name`; `db.py:102-152` (`next_wall`/`request_now`/`base_row` — one stamp per request, strictly increasing across requests); `grep insert("translation_units"` -> only `market_plans.py:182`, and `start_localization` requires `SCOPED`, which is unreachable again after the `LQA -> IN_LOCALIZATION` revert, so a plan's units are always one single-request batch; `derive.py:108-109` `by_created` and all 16 of its callsites (creation/iteration order only, never response order). (c) Adjustment: scoped the ordering claim to listings *filtered by `market_plan_id`* rather than to translation-unit listings in general, because unfiltered listings span plans with distinct `created_at`; kept the "iterates in string-key `created_at` order" clause (true of `by_created`) but explicitly marked it unobservable instead of deleting it.

**Edit B — §3.1 title counters/version.** (a) Subject: which writes mutate the title row and bump its `version`. (b) Enumerated every title-mutation site: `derive.py:135-152` `refresh_title` (change-gated on exactly five fields: the three counters plus `string_lock` and `release_gate_state`) and all its callers — `titles.py:116`, `string_keys.py:53,104`, `market_plans.py:99,139,188,278,302`, `clock.py:24`, `derive.py:484,498,508`; direct `touch(title)` sites — `titles.py:111` (lock-strings), `derive.py:483` (`bubble_title_to_cert`), `derive.py:496` (`bubble_title_to_shipped`), `derive.py:507` (`revert_title_from_cert`); `market_plans.py:95-99` (plan creation does reach `refresh_title`). (c) Two adjustments: added "and creating a market plan does the same through `market_plan_count`" so the statement is not read as special-casing string keys (impl treats both identically); and widened the negative clause from "leaves all three counters unchanged" to "changes none of these three counters and leaves `string_lock` and `release_gate_state` as they were", because `refresh_title`'s gate includes those two — a clock move that only flips `release_gate_state` does bump the title's `version` (`clock.py:24` -> `derive.py:146-151`).

**Edit C — §2.4 once-per-request clamp.** (a) Subject: the per-row, per-request cardinality of `version` increments. (b) Enumerated: `grep '"version"'` across the whole implementation -> written only at `db.py:140` (inside `touch`) and initialised at `db.py:151`; the two optimistic-concurrency readers (`rating_submissions.py:77`, `voice.py:156`) only compare. Then checked the clamp against every PRD site that could demand two increments of one row in one request: §3.9 `mark-release-ready` (`ready_market_count` refresh + `CERT_WINDOW -> SHIPPED` bubble -> impl gives the title exactly +1 via `market_plans.py:278` + `derive.py:487-498`), §3.8 hops 3/4 (plan `required_unit_count` drop + `LQA -> IN_LOCALIZATION` revert -> +1), §3.8 hop 7 and §3.9's compensating revert (`localization_state` + `release_gate_state` -> +1), §2.6's "every row a cascade touches is a mutation". No PRD sentence requires +2 for one row in one request, so the clamp adds no divergence. (c) No wording adjustment needed; kept it phrased as a per-request total so it composes with §2.4's existing "exactly 1 on every mutation" and §2.6's cascade rule.

No `implementation/` behaviour was invented: Step 7 applied zero implementation fixes, and all three edits describe code that already exists (uniform sort rule, single-stamp-per-request row bookkeeping, change-gated title refresh).

### Orchestrator verification

- PRD_FINALIZED.md exists, 485 lines / 96,910 bytes, and is NOT byte-identical to PRD.md (`diff` reports 6 changed lines = 3 inline revisions). Ends on the completed final §5 table row, so no truncation.

## Step 9: Complete PRD — 2026-09-05T10:10:00.000Z

Run as THREE SEQUENTIAL module-partitioned passes over one shared `workspace/PRD_COMPLETED.md`, rather than one monolithic scan. Rationale (orchestrator decision, made without a user to consult): a single pass over 3,806 lines of implementation reliably exhausts its budget and silently no-ops, leaving PRD_COMPLETED.md byte-identical to its source — which would be a false completion signal. Pass 1 performed the `cp` from PRD_FINALIZED.md; passes 2 and 3 were explicitly forbidden from copying so they could not destroy earlier passes' edits. Each pass received the previous pass's hand-off findings.

Partition:
- Pass 1 — app.py, constants.py, db.py, errors.py, middleware.py, response.py, routehelp.py, serialize.py, validation.py, routes/{__init__,clock,titles,string_keys}.py (cross-cutting infrastructure + Title/StringKey domains).
- Pass 2 — routes/{market_plans,translation_units,voice}.py plus the derive.py paths they reach (scope/effort/cost, TM bands, talent/booth/contract/session, session-cancellation cascade, conserved quantities).
- Pass 3 — routes/{qa_passes,lqa_bugs,rating_submissions,content_edits}.py plus the derive.py paths they reach (density gate, bug triage, rating risk, submission fees, board review, appeals, content-edit apply cascade), plus a final global cross-pass consistency check.

### Pass 1 summary (verbatim)

`cp PRD_FINALIZED.md PRD_COMPLETED.md` done. **PRD_COMPLETED.md = 485 lines**, tail verified as the last row of the §5 error table (`| ERR_BUDGET_OVERAGE | 422 |`). 14 inline edits, all in-paragraph, no new sections, line count unchanged.

Counts: ambiguity-pins 12, mismatch-revisions 2.

Changes:
- §2.1 — revise — ambiguity — an empty or whitespace-only `X-User-ID` counts as absent for `ERR_UNAUTHENTICATED` — `middleware.py:20`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric chars; `api_request_timestamp` comes from real server time, not the logical clock — `response.py:21,25`
- §2.3 — revise — ambiguity — a non-integer-literal `limit`/`offset` is also `ERR_INVALID_REQUEST`, an empty value falls back to the default, `offset` has no upper bound — `response.py:53-75`
- §2.3 — insert — ambiguity — filter values are matched literally and not shape-validated; `union_flag` accepts true/1/yes and false/0/no in any case and is dropped when unparseable; undefined query params ignored — `routehelp.py:5-43`, `routes/voice.py:128`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` drawn from real server time (truncated, not rounded, to ms), one stamp minted per request and strictly advanced between requests — `db.py:102-152`
- §2.4 — insert — ambiguity — the clock may be set backward; clock response rendered to 3 fractional digits; a title whose posture changes is mutated while an unchanged one is not; nothing else re-derived by the clock move — `routes/clock.py:20-26`, `derive.py:135-152`
- §2.5 rung 3 — revise — **mismatch** — rung 3 also applies to the pagination parameters of every list endpoint — `response.py:72-75`
- §2.5 rung 3 — insert — ambiguity — explicit `null` on a required field counts as absent; integers must be JSON integers; duplicate values in a distinct-array are a shape violation; datetime parsing tolerances; undeclared fields ignored; body parsed regardless of `Content-Type`; bodyless action endpoints ignore any body — `validation.py:14-198`, `db.py:18-49`
- §2.8 — insert — ambiguity — all quantities render as bare JSON numbers, never strings — `serialize.py:7-10,52,152`
- §3.1 — revise — ambiguity — `target_release_utc` at or before the clock is `ERR_INVALID_REQUEST`, reported ahead of the `title_code` collision; explicit `null` for `source_language`/`release_mode` is a shape violation — `routes/titles.py:36-43`
- §3.1 — insert — ambiguity — string-key amendment semantics; a no-op amendment is not a mutation — `routes/string_keys.py:79-105`
- §3.1 — revise — **mismatch** — on string lock, a market plan whose recomputed `required_unit_count` is unchanged is *not* mutated — `derive.py:178-187`, `routes/titles.py:113-114`
- §3.4 — insert — ambiguity — `reserved_minutes_on_clock_date` is derived at read time, so it changes with the clock without mutating the talent row — `serialize.py:96-106`
- §4 — revise — ambiguity — a trailing slash is equivalent to the path without one — `app.py:20`
- §5 — insert — ambiguity — three out-of-catalogue identifiers: `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405 (both decided by routing ahead of authentication), `ERR_INTERNAL` 500 — `app.py:33-57`, `errors.py:73-75`

### Pass 2 summary (verbatim)

**No file was copied.** Edited the existing PRD_COMPLETED.md in place with 29 `Edit` calls. Line count 485 before -> 485 after. Pass 1's work intact (spot-checked the `req_` sentence, the §3.1 unchanged-`required_unit_count` clause, and Step 8's §3.3 unit-ordering sentence). Counts: 19 ambiguity-pins, 10 mismatch-revisions.

Changes:
- §2.5 rung 3 — revise — mismatch — the "Two.../A third" exhaustive count was false; now lists the contract `rights_start_utc < rights_end_utc` check and the `recorded_line_count <= planned_line_count` check — `voice.py:147,402`
- §2.5 rung 12 — revise — mismatch — "guards five operations" was false; added scoping, unit text-write/deliver, session start, session cancel — `market_plans.py:129`, `translation_units.py:61,85`, `voice.py:379,385,432`
- §2.5 rung 13 — revise — mismatch — swapped so `ERR_CONTENT_RESTRICTION_UNRESOLVED` precedes `ERR_MANDATORY_DISCLOSURE_MISSING` — `market_plans.py:250-255`
- §2.10 — revise — mismatch — qualified "every row a cascade touches is a mutation": counter-recompute hops no-op when unchanged, **except** the contract and plan hops of the session-cancellation cascade, which mutate unconditionally — `derive.py:178-182` vs `derive.py:553-562`
- §3.2 — insert — ambiguity — plan creation opens `required_unit_count` at the title's locked-key count, others at 0, `version` 1; explicit `null` `scope_tier` accepted — `market_plans.py:86-98`
- §3.2 — insert — ambiguity — scoping's title precondition is `ERR_PREREQUISITE_STATE_NOT_MET` at rung 12 — `market_plans.py:126-133`
- §3.2 — insert — ambiguity — a null `applied_tm_match_pct` on a DELIVERED unit reads as the new-text band 1.00 — `constants.py:212-214`
- §3.2 — revise — ambiguity — scope multiplier is 1.00 for a plan whose `scope_tier` is still null — `derive.py:248`
- §3.3 — insert — ambiguity — the voiced-tier coverage scan reads stored `status` only, runs no lazy expiry, ignores `media_scope` — `market_plans.py:155-166`
- §3.3 — insert — ambiguity — a title with no `LOCKED` key still hands off, creating no unit and `required_unit_count` 0 — `market_plans.py:168-186`
- §3.3 — insert — ambiguity/mismatch — PUT semantics: `target_text` present but may be null; `target_char_count` shape-checked then discarded; `applied_tm_match_pct` optional/sticky; a no-op write is still a mutation — `translation_units.py:48-71`
- §3.3 — insert — ambiguity — deliver takes no mandatory body; no effort/cost recompute — `translation_units.py:78-99`
- §3.3 — insert — mismatch — qa-mark accepts all four `qa_status` values; PASSED guards report `ERR_UNIT_NOT_DELIVERED` — `translation_units.py:107-127`
- §3.3 — revise — mismatch — "flagged values are written by defect logging rather than by an inspection call" softened to "also written by defect logging" — `translation_units.py:107`, `derive.py:364-373`
- §3.3 — revise — mismatch — `required_unit_count` redefined as a stored counter with exactly four writers plus the scoping exception — `market_plans.py:96,135,185`, `derive.py:184-186`, `titles.py:113`, `content_edits.py:167`
- §3.4 — revise — mismatch — `booth_code` is not unique — `voice.py:65-79`
- §3.4 — insert — ambiguity — explicit `null` `union_flag` falls back to `false` — `validation.py:127-133`
- §3.4 — insert — ambiguity — inverted/empty rights window is `ERR_INVALID_REQUEST` at rung 3 — `voice.py:147`
- §3.4 — insert — ambiguity — signature failure code is `ERR_CONTRACT_RIGHTS_WINDOW_EXCEEDED`; signing before `rights_start_utc` is allowed — `voice.py:215-219`
- §3.4 — insert — ambiguity — a `DRAFT` contract's `committed_fee_cents` is 0 regardless of `buyout_fee_cents` — `derive.py:306-313`
- §3.5 — insert — ambiguity — no scope tier is a booking prerequisite; the `media_scope` rule bites on `FULL_CULTURAL` alone — `voice.py:287-290`
- §3.5 — insert — ambiguity — `duration_minutes` floors to whole minutes — `voice.py:300`
- §3.5 — revise — mismatch — session start's check order and per-check codes pinned — `voice.py:367-389`
- §3.5 — insert — ambiguity — completion imposes no contract/plan state precondition and runs no lazy expiry — `voice.py:398-421`
- §3.5 — insert — ambiguity — cancel: `RELEASE_READY` refusal is `ERR_PREREQUISITE_STATE_NOT_MET`; a `BLOCKED` plan does not block cancellation — `voice.py:429-436`
- §3.5 — insert — mismatch — hops two and three mutate contract and plan unconditionally; hop four weighs the voice quota alone — `derive.py:553-568`
- §3.9 — insert — ambiguity — mandatory-disclosure failure code; a plan with no submission has an empty effective set — `market_plans.py:247-268`
- §3.9 — insert — ambiguity — blocking leaves `localization_state` untouched, reopens no pass, leaves effort alone — `market_plans.py:293-302`
- §3.9 — insert — ambiguity — each auto-revert trigger tests only its own half — `derive.py:563-568`

Handed-over findings: all four resolved (see pass 2 detail above); the inclusive `>=` lapse boundary was already correctly pinned by §3.4, so no change was needed there.

### Pass 3 summary (verbatim)

**No re-copy.** Edited in place with the Edit tool only. Line count 485 before, 485 after. `tail -5` still ends at `| ERR_BUDGET_OVERAGE | 422 |`. Pass 1's `req_`-prefix sentence and pass 2's §2.10 cascade qualification and §3.9 voice-quota sentence all still present; 69 diff hunks against `PRD_FINALIZED.md`.

Counts: 30 edits — 18 ambiguity-pins, 12 mismatch-revisions.

- §2.5 rung 6 — revise — mismatch — added duplicate triage to the referential-coherence rung — `routes/lqa_bugs.py:126`
- §2.5 rung 6 — insert — mismatch — `duplicate_of_bug_id` must resolve under the same `qa_pass_id` — `routes/lqa_bugs.py:126-127`
- §2.5 rung 8 — revise — mismatch — review entry added to the segregation-of-duties applies-list — `routes/rating_submissions.py:170`
- §3.3 — insert — ambiguity — the defect-logging flag write is unconditional — `derive.py:364-373`
- §3.3 — revise — mismatch — `required_unit_count` recompute scope: §3.1's cascade spans every plan of the title, the §3.8 key-retirement hop touches the edited submission's plan alone — `routes/content_edits.py:168`
- §3.6 — insert — ambiguity — uniqueness (rung 10) outranks plan state (rung 12) on pass creation — `routes/qa_passes.py:40-48`
- §3.6 — revise — ambiguity — plan-must-be-`LQA` on close reports `ERR_PREREQUISITE_STATE_NOT_MET` — `routes/qa_passes.py:96-100`
- §3.6 — revise — ambiguity — same code named for reopen's plan-state check — `routes/qa_passes.py:119-124`
- §3.6 — insert — ambiguity — `translation_unit_id` is discarded for `FUNCTIONAL_CRASH`; an unlinked defect touches no unit — `routes/lqa_bugs.py:51-52,82-85`
- §3.6 — insert — ambiguity — the four DUPLICATE-target conditions with codes and rungs — `routes/lqa_bugs.py:116-138`
- §3.6 — insert — ambiguity — the defect's own state is evaluated before the owning pass's — `routes/lqa_bugs.py:129-133`
- §3.6 — insert — ambiguity — submit-fix body optional; `target_text` 0..4000; conditional mutation; `qa_status` untouched — `routes/lqa_bugs.py:159-177`, `derive.py:347-361`
- §3.6 — insert — ambiguity — verify's overflow guard names `ERR_TEXT_OVERFLOW_UNRESOLVED`; an unlinked overflow/truncation defect can never reach `VERIFIED` — `routes/lqa_bugs.py:196-198`
- §3.7 — insert — ambiguity — supersede covers any of the four non-terminal states and drags the superseded package's `PROPOSED` edits — `routes/rating_submissions.py:52-59,87-90`
- §3.7 — insert — mismatch — a supplied `target_rating` is enum-checked before being discarded in favour of the plan's — `routes/rating_submissions.py:71`
- §3.7 — revise — mismatch — filing has exactly two compliance gates (no restriction check) — `routes/rating_submissions.py:147-152`
- §3.7 — insert — mismatch — begin-review names `ERR_SEGREGATION_OF_DUTIES` and its rung-8 precedence — `routes/rating_submissions.py:170`
- §3.7 — insert — mismatch — RATE's band comparison is skipped when `projected_rating_band` is null, so the request instead reports `ERR_SUBMISSION_STATE_INVALID` — `routes/rating_submissions.py:193-197`
- §3.7 — insert — mismatch — an explicit `null` `assigned_rating` counts as present for `REQUIRE_EDITS` — `routes/rating_submissions.py:200-201`
- §3.7 — revise — ambiguity — appeal's four conditions are evaluated in ladder order — `routes/rating_submissions.py:222-233`
- §3.7 — insert — mismatch — the APPLIED-edit prerequisite (rung 12) precedes both rung-13 appeal conditions — `routes/rating_submissions.py:224-233`
- §3.7 — revise — mismatch — withdrawal also refuses `RATED`; a `RATED` submission survives a later round's supersede — `routes/rating_submissions.py:247,89`
- §3.8 — revise/insert — ambiguity — arrays omitted-or-null = empty; per-element resolve-then-title-check order; subset violation is `ERR_INVALID_REQUEST` — `routes/content_edits.py:45-53,63-79`
- §3.8 hop 3 — insert — ambiguity — recompute only when a key actually moved, only for the submission's own plan; the title's `extracted_key_count` is left stale unless hop 7 runs — `routes/content_edits.py:160-168`
- §3.8 hop 4 — revise — mismatch — the trigger is compound: plan in `LQA` AND (undelivered > 0 OR delivered < required) — `routes/content_edits.py:176-179`
- §3.8 hop 4 — insert — mismatch — why the first disjunct is not redundant; only the delivered side is examined; a non-`LQA` plan skips hops 4-7 — `routes/content_edits.py:176-180`
- §3.8 hop 6 — insert — ambiguity — also raises reverted units' `open_bug_count`; units stay `NOT_CHECKED` — `routes/content_edits.py:184-197`
- §3.8 hop 7 — insert — ambiguity — a title outside `CERT_WINDOW` keeps its state but is still re-derived — `derive.py:501-508`
- §3.8 apply — revise — ambiguity — the `EDITS_REQUIRED`/`RATED` submission precondition names `ERR_PREREQUISITE_STATE_NOT_MET` — `routes/content_edits.py:122-126`
- §3.9 — insert — mismatch — the content-edit revert trigger weighs the delivered side alone and its test is broader than the bare inequality — `routes/content_edits.py:176-179`

Handed-over findings: (1) compound revert trigger RESOLVED and verified reachable; (2) filing-gate codes/order RESOLVED, consistent with pass 2's rung-13 ordering; (3) dead `plan_lqa_deficient` RESOLVED — confirmed referenced by no route, §3.9 now describes the two live half-triggers; (4) §2.10's conditional/unconditional claim VERIFIED CORRECT for pass-3 modules, the one unconditional write (`flag_unit_for_bug`) being a genuine state write now pinned in §3.3; (5) `recompute_pass_density` zero guard CONFIRMED unreachable, no PRD edit.

**Final global consistency check: no contradictions introduced across the three passes.** §2.10's cascade qualification and §2.5's rung contents re-read after the rung-6/rung-8 corrections and internally consistent. One latent tension pre-empted: §3.3's `required_unit_count` sentence now distinguishes the §3.1 title-wide cascade from the §3.8 single-plan key-retirement hop. Step 8's §2.4 version-clamp and §3.1 title-counter sentences left untouched.

### Orchestrator verification and close-out

- Totals across the three passes: **73 edits — 49 ambiguity-pins, 24 mismatch-revisions.**
- PRD_COMPLETED.md = 485 lines / 119,466 bytes vs PRD_FINALIZED.md 485 lines / 96,910 bytes: **+22,556 bytes (+23.3%)**, 128 changed lines. It is NOT byte-identical to its source, so the scan demonstrably ran (a byte-identical Step 9 output would mean the scan silently no-opped).
- `tail` confirms the file still ends on the completed final row of the §5 error table — no truncation from any of the three passes.
- Step 9 edits documentation only; `implementation/` was untouched after Step 7, so the clean 8-round sweep (all rounds 170/170, artifacts retained at `workspace/implementation/results.{1..8}.json`) remains valid. No re-sweep run.
- Housekeeping: removed `__pycache__`/`*.pyc` left by the pytest runs. Confirmed exactly one `worklog.md` at the task root with no strays under `workspace/` (a known cwd-drift failure mode). `workspace/sweep.log` retained as launch evidence only — it is interleaved output from 8 concurrent rounds and was not used for diagnosis.

PIPELINE COMPLETE — Step 9 wrote workspace/PRD_COMPLETED.md.

