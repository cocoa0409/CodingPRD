# Worklog — task_2793_international_film_sales_pre_sale_financing

## Step 1: Create task directory — 2026-09-04T22:19:30.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2793_international_film_sales_pre_sale_financing` and its `workspace/` subdirectory. Index 2793 was pre-assigned by the invoking pipeline (no scan of ./tasks/ was performed, per the orchestrator instruction that concurrent pipelines share this host).

## Step 2: Generate scaffold — 2026-09-05T00:12:00.000Z

All three scaffold artifacts are complete and lint-clean.

Files (absolute paths)
- SCAFFOLD.yaml — 2,770 lines / 156 KB
- SCAFFOLD_DIFFICULTY_DESIGN.yaml — 2,477 lines / 170 KB
- SCAFFOLD_CORNER_DESIGN.yaml — 7,894 lines / 490 KB

SCAFFOLD.yaml (§1.0–§1.7)
16 entities · 11 state machines · 2 §1.2.1 OCC rules (`valuation-publish-stale-film` -> ERR_STALE_FILM_VERSION 412, `contract-offer-stale-buyer` -> ERR_STALE_BUYER_VERSION 412) · 9 calculations · 50 ordered validations (priority 10 -> 106) · 63 endpoints · 50 errors · 7 roles (`role_model: segregation_of_duties`). Archetypes: multi_party_negotiation / ledger_reconciliation; layers optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; consistency_model immediate. Contains no `scaffold_difficulty_design` / `scaffold_corner_design` keys.

§1.8 — 9 rule ids / 19 instances
dual_variant_calc 2 · combinatorial_formula 3 · non_linear_state_machine 2 · transitive_cascade 2 · priority_pair_validation_conflict 2 · boundary_precision_check 2 · cross_entity_state_dependency 2 · resource_temporal_overlap 2 · compensating_invariant 2

§1.9 — 9 sections / 111 instances (89 full recipes + 22 `excluded_because` stubs)
entities 13 (13+0) · state_machines 18 (14+4) · calculations 18 (10+8) · validations 31 (24+7) · endpoints 11 (11+0) · errors 4 (4+0) · rbac 6 (6+0) · cross_cutting_complexity_layers 7 (4+3) · consistency_model 3 (3+0)

Verified: all 111 names unique across both design files; every stub cites a §1.8 instance that exists by name; all `claim_type` values come from `references/claim-extraction-guide.md`; all 50 §1.6 error codes are asserted by name; all 63 §1.5 endpoints are exercised by at least one call; no forbidden concurrency vocabulary anywhere.

Lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
Coverage
  §1.5 endpoints declared:    63
  §1.1 entities declared:     16
  §1.8 instances scanned:     19
  §1.9 instances scanned:     89
  Calls scanned (§1.8+§1.9):  1975

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Two things flagged by the subagent
1. `scenario:` still contained the line `Generate task harder than expert level!` (SCAFFOLD.yaml lines 6–18) because the scenario had to be reproduced verbatim. Strip that one line after Step 2 so it cannot leak into PRD.md (known difficulty-directive leak path).
2. One wording fix inside SCAFFOLD.yaml (validation priority 93, line ~1723): the original text demanded `milestone_pct_total == 1.0000` on every milestone POST, which would have made the sequential 0.45/0.20/0.10/0.25 build-up used by every §1.8/§1.9 recipe illegal. It now reads `+ payload pct_of_mg <= 1.0000` on `POST .../payment-milestones` and `== 1.0000` on `POST .../execute`. No other SCAFFOLD.yaml content changed.

ORCHESTRATOR ACTION on flag (1): the two lines `  Generate task harder than expert level!` and the blank line following it were removed from SCAFFOLD.yaml's `scenario:` block. Verified by grep across all three scaffold YAMLs: zero occurrences of "harder than expert" remain. All three files re-validated as parseable YAML with the expected top-level keys. Task dir and workspace/ confirmed intact after the scaffold subagent.

## Step 3: Copy shared files — 2026-09-05T00:13:00.000Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md -> workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T00:25:00.000Z

All checks pass. The PRD is complete.

**Output:** workspace/PRD.md — **542 lines**, ending at a real section boundary (final row of the §5 error table, `ERR_EXPENSE_LOG_LIMIT | 422`). No audit footer in the file.

### Section list
- `## 1. Introduction` (3 paragraphs — business-context angle, plus the two structural themes: segregation of duties, pinned evaluation order)
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Resource Identity, Audit Columns and the Logical Clock · 2.5 Money, Precision and Rounding · 2.6 Stale-Version Guards on Slate and Buyer Records · 2.7 Rejection Ordering · 2.8 Cascade Propagation and Version Semantics · 2.9 Enumerated Vocabularies
- `## 3. Business Logic & Workflows` — 3.1 Bringing a Picture onto the Slate and Engaging the Agency · 3.2 Market Attendance: Screening Rooms and Meeting Tables · 3.3 Territory Valuation: Comparables, Cast Tiers and Publication · 3.4 Buyers, Credit Limits and Pre-Sale Negotiation · 3.5 Countersigning: Where Every Guard Converges · 3.6 Delivery of Materials and the Final-Rejection Cascade · 3.7 Collecting Cash and Accruing Tiered Commission · 3.8 Bank Financing: Discounting Pre-Sales, Bonds and Margin Calls · 3.9 The Distribution Waterfall, Reversion and Wrap
- `## 4. Endpoint Definitions` (4 columns, 63 rows)
- `## 5. Error Code Catalogue` (2 columns, 50 rows) — **last section heading in the file**

### Coverage
16 entities · 11 state machines · 9 calculations · 50 validations (full 13-rung precedence ladder in §2.7, with the practical masking consequences named) · 63 endpoints · 50 error codes · 7 roles.

### Hard Contract Reports

```
Field coverage check:
- entities[].fields: 128 required, 128 present, 0 missing
- endpoints[].request_body: 78 required, 78 present, 0 missing
- endpoints[].query_params: 17 required, 17 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 50 checked, 50 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_film_version / expected_buyer_version + ERR_STALE_FILM_VERSION / ERR_STALE_BUYER_VERSION + 412 all named), 0 missing
- state_machines[].transitions: 11 machines / 56 transitions checked, 56 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed, 0 missing
- validations[] conditions: 50 checked, 50 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 63 checked, 63 expressed, 0 missing
- entities[].fields[] structured content: 128 checked, 128 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (Film IN_MARKET|SOLD_OUT->WRAPPED; milestone SCHEDULED|INVOICED->RECEIVED; milestone SCHEDULED|INVOICED->WRITTEN_OFF; contract OFFERED|COUNTERED|ACCEPTED->LAPSED; slot HELD|CONFIRMED->CANCELLED; package PASS->ACCEPTED vs CURED), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1054
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 diffs byte-identical against `section-2.2-response-structure.md`. No fuzzy/approximating words anywhere in the file. The two withheld design files were never opened.

Two judgement calls worth flagging: (1) the scaffold specifies a rejected package's `cure_deadline` as `submitted_at + CURE_WINDOW_DAYS` in both the state-machine table and `deliverable_completeness`, but as `current_utc + CURE_WINDOW_DAYS` in the qc-result endpoint's side effects — the doc generator wrote the two-out-of-three reading (`submitted_at` plus 30 days); (2) `ERR_BUYER_EXPOSURE_EXCEEDED` applies to revise-offer as well as offer creation per validation priority 100, so §3.4 states the gate on both.

ORCHESTRATOR TRUNCATION CHECK (per the known doc-generator failure mode): verified independently. PRD.md is 542 lines; the §4 endpoint table holds 65 pipe rows (63 endpoints + header + separator) and the §5 error table holds 52 pipe rows (50 errors + header + separator); the file's last line is a complete table row, and the last heading is `## 5. Error Code Catalogue`. The document ends at a real section boundary — NOT truncated. No regeneration needed. Also grepped PRD.md for "harder than expert", "expert level" and "SCAFFOLD": zero hits, so the difficulty directive did not leak.

## Step 5: Generate unit tests — 2026-09-05T01:30:00.000Z

Test suite generation for task 2793 is complete and verified.

## Output

**`test_helpers/` — 9 files, 2313 lines** (all at task root, none under `workspace/`)
- `api_client.py` (335) — one method per §4 endpoint under `/film-sales`; adds a `patch` shim since `GenericApiClient` has none
- `api_errors.py` (153) — all 50 §5 error IDs with their HTTP status map
- `constants.py` (232), `types.py` (239) — 16 TypedDicts, reference rows structurally distinct from audited rows
- `factories.py` (341) — money always emitted as JSON numbers
- `assertions.py` (330) — includes `assert_instant` (whole-second normalisation) and `assert_account_invariant`
- `fixtures.py` (520) — 5 tiers of composite builders
- `test_users.py` (86), `__init__.py` (77) — 311 exported names

**`test_suite/` — `conftest.py` + 11 test files, 7958 lines, 185 test functions**

## Coverage

| | instances | translated | skipped |
|---|---|---|---|
| Queue A (difficulty) | 19 | **19** | 0 |
| Queue B (corner, non-stub) | 89 | **89** | 0 |
| Queue B stubs | 22 | n/a (all 22 `difficulty_instance:` cross-refs resolve) | — |

Every queue A instance has >=3 tests (3–6); every non-stub corner instance >=1. Verifier reports **0 tag/citation errors**: exactly one `Design:` line per test, all 185 tags resolve, none points at an `excluded_because` stub, every docstring carries a verbatim `PRD: "..."` citation.

## Key judgement call

A2 initially skipped `contract_negotiation_cycles_offer_counter_offer_until_round_limit_while_other_axes_hold`. I reopened it: the cause was an **off-by-one in the design, not a PRD gap** — PRD §3.4 L277 starts a contract at `negotiation_round` 1 while the design assumed 0. That is the same class of design-vs-PRD literal conflict the other six agents *corrected* (`ERR_INVALID_REQUEST` 422->400, `NOT_STARTED`->`PENDING`, `version == 4`->`+1`, `ERR_RECEIPT_ALREADY_DISTRIBUTED` 409->422, out-of-enum `rejection_reason`), so skipping it was inconsistent and would have left `ERR_NEGOTIATION_ROUND_LIMIT` and the three-independent-axes property with zero coverage across the whole suite (two corner stubs also defer to it). A2 re-derived from the PRD and added 6 tests; a notable consequence is that the loop dies at round 4 on the *buyer's* side, leaving the contract **COUNTERED**, not OFFERED as the design asserted.

## Verification

`py_compile` clean on all 20 files; all 11 test modules **import cleanly against the frozen helpers** (proves no undefined helper names); no `__pycache__` left; nothing written under `workspace/`, no touch to `workspace/implementation/` or `worklog.md`; no server started, no `pkill`, pytest never run.

## Notes for downstream

- Three module-private helpers live in test files rather than the frozen package: `_assert_ratio`/`_assert_not_money` (test_06), `_assert_error_envelope` (test_09).
- Design yaml defects worth reporting to the design author: the `negotiation_round` off-by-one above; `ERR_INVALID_REQUEST` given as 422 (PRD §2.7 says 400); `ERR_RECEIPT_ALREADY_DISTRIBUTED` given as 409 (§5 says 422); `delivery_status` `NOT_STARTED` (PRD uses `PENDING`); several out-of-enum literals (`MASTER_AUDIO_DEFECT`, `MISSING_M_AND_E`, `PRESS_SCREENING`); and query filters the yaml assumes but §4 never declares (`genre`, `region`, `market_id`, `room_number`).
- `workspace/PRD.md` §4's endpoint table leaks scaffold-style cross-references ("§1.2 Film machine", "§1.3 waterfall_distribution", "§1.2.1 valuation-publish-stale-film OCC guard") — worth stripping before the PRD ships.
- Two success-status readings rest on §4's prose rule rather than an explicit pin: `POST /collection-accounts/{id}/distribute` asserts **201** (creates an immutable `DistributionRun` row) and expense logging asserts **200** (no new row). Neither design yaml contradicts these; if the implementation disagrees, these are the first places to look.

ORCHESTRATOR NOTE: verified `test_helpers/` and `test_suite/` both landed at the TASK ROOT (not under `workspace/`) — the known Step-5 misplacement did not occur. `workspace/` contains exactly INSTRUCTION.md, PRD.md, implementation/. Independent count confirms 185 `def test_` functions across 11 test files. The §4 scaffold-cross-reference leak the generator flagged is cosmetic (no worked example numbers, no test answers) and is left in place deliberately: hand-patching PRD.md between Steps 5/6 and Step 7 would desynchronise the contract the tests and implementation were both generated against. Steps 8/9 own PRD revisions.

## Step 6: Generate implementation — 2026-09-05T01:30:00.000Z

Implementation complete and verified.

## Modules (13 Python files, 3,789 lines total)

All under `workspace/implementation/`:

| File | Lines | Role |
|---|---|---|
| `calc.py` | 590 | all derived figures: film counters, buyer exposures, valuation math, commission tiers, waterfall, facility figures |
| `api_contracts.py` | 549 | pre-sale contracts, negotiation, execute, payment milestones, deliverable packages, QC |
| `api_finance.py` | 472 | banking facilities, collection accounts, waterfall tiers, distribution, receipts, logical clock |
| `api_markets.py` | 351 | markets, screening slots, buyer meetings |
| `serializers.py` | 331 | 16 entity projections |
| `api_films.py` | 296 | films, agency agreements, expenses |
| `api_territories.py` | 292 | territories, comparables, buyers, valuations |
| `validation.py` | 243 | RBAC, typed body reader, pagination |
| `store.py` | 207 | in-memory dicts, base_row/touch, fetchers |
| `util.py` | 198 | Decimal quantizers, ISO 8601 3-digit instants, date math |
| `errors.py` | 130 | 50 error IDs -> HTTP status + default messages |
| `app.py` | 74 | app factory, blueprint registration, error handlers |
| `envelope.py` | 45 | meta/response_type/data envelope |
| plus `start.sh` (10) and `requirements.txt` (1) | | |

## Endpoint coverage: 63/63, exact match

A programmatic diff of the 63 `path:` entries in `SCAFFOLD.yaml` against the 63 `@bp.<verb>` routes came back with **zero** missing and **zero** extra (after normalising `{id}` vs `<id>`).

## Smoke test: booted and responded

Two scripted end-to-end runs on port 51793 plus a fresh-boot check on 51794 — **50 assertions, all passing**. The full financing lifecycle ran clean: film -> agency agreement -> PACKAGING -> territory -> 3 verified comparables -> CAST_ADJUSTED valuation (median 500,000 x 1.4 cast multiplier x 1.2 index = estimate 840,000, ask 1,050,000, floor 588,000) -> publish -> IN_MARKET -> buyer -> contract -> counter -> revise -> accept -> 3 milestones -> execute -> facility approve/draw -> collection account -> 5 waterfall tiers -> receipt -> two distribution runs -> deliverable packages -> double QC failure -> deep cascade.

Verified along the way: both OCC guards (412), segregation of duties on both valuation-publisher-vs-executor and facility-approver-vs-drawer (403), the 30-minute screening buffer including the exact edge case (12:20 rejected, 12:30 accepted), the 240-minute per-buyer meeting cap including the exact boundary, market-close cascade (HELD->CANCELLED, SCHEDULED->NO_SHOW), and the final-rejection cascade (contract LAPSED/REJECTED/WRITTEN_OFF, valuation LICENSED->PUBLISHED, film SOLD_OUT->IN_MARKET, facility DRAWN->MARGIN_CALL).

**Two findings worth flagging, both resolved as fixture errors rather than code defects:**
1. `execute` returned 422 `ERR_MG_BELOW_FLOOR` — my test MG of 560,000 was genuinely under the 588,000 floor. Correct behaviour.
2. A third uncapped waterfall tier returned 409 `ERR_TIER_ORDER_TAKEN`. I checked this against the spec rather than assuming: PRD.md line 391 states "an account may hold at most one uncapped tier, so a second tier submitted without a `cap_usd` is refused." The implementation was right.

## Constraint compliance

- **In-memory only** — a grep for `sqlite|open(|json.load|pickle|shelve|/tmp|.db|dbm` across all 13 modules returns nothing.
- **Zero seeding** — after a fresh boot from an unrelated cwd (`/tmp`), all seven collection endpoints return `data: []` with `total_count: 0`.
- `start.sh` launches correctly from any working directory (it `cd`s to its own dirname), so per-test-server isolation will work.
- All 13 files pass `python3 -m py_compile`; `__pycache__` removed so the directory ships clean.
- Wrote only inside `implementation/`; never read `test_suite/` or `test_helpers/`; did not touch `worklog.md`. Both smoke servers were killed by exact PID (1155591, 1156701) with ports confirmed released — no broad `pkill` was ever issued.

ORCHESTRATOR NOTE: Steps 5 and 6 were launched concurrently in a single assistant message, so the implementation generator's process could not have read `test_suite/` (it did not exist at its spawn time) — physical isolation held.

## Step 7: Run tests and iterate — 2026-09-05T01:55:00.000Z

Clean sweep achieved. Only the two intended files changed; `worklog.md` untouched.

**Iterations run:** 2

**Iteration 1 baseline:** 183/185 in all 8 rounds — the same 2 tests failed deterministically in every round (no flakiness anywhere in the suite; no load-induced timeouts).

### Tests deleted
None. Both failures were resolvable — one was a genuine implementation defect, the other a test assertion that contradicted the PRD's own precedence ladder.

### Fixes applied to `test_helpers/`
None — no fixture, factory, or role-header bug surfaced.

### Fixes applied to `test_suite/`
- `test_suite/test_02_lifecycle_cycles_cascades_and_precedence.py` — `TestNegotiationRoundLoop.test_a_further_counter_at_the_round_limit_is_refused_identically` (renamed `..._is_refused_on_the_state_axis`): asserted `ERR_NEGOTIATION_ROUND_LIMIT` (422) on a fourth-round counter, but PRD §2.7 puts the own-state guard (rung 7, `ERR_INVALID_STATE`) **above** the round limit (rung 12), and explicitly lists "countering" under rung 7 including "a repeated trigger on a row already in the destination state". The setup drives the contract to `COUNTERED` and counters again, so the state guard fires first. Corrected the expected error to `ERR_INVALID_STATE` (409) and re-cited the governing PRD sentences.

  Worth flagging: `ERR_NEGOTIATION_ROUND_LIMIT` is **unreachable on the counter branch** in any PRD-faithful implementation. Countering is legal only from `OFFERED`, and the alternation places `OFFERED` at rounds 1 and 3 only — both strictly below 4. Round 4 is always `COUNTERED`. The limit is reachable only on the agency's `revise-offer` branch, which `test_the_answer_at_the_round_limit_is_refused` already covers and which passed throughout.

### Fixes applied to `implementation/`
- `workspace/implementation/store.py` — `base_row()` and `touch()` stamped `created_at` / `updated_at` from `wall_now()` (real wall-clock) instead of the logical clock. PRD §2.4 states "Time in this system is a **logical clock**, not wall-clock time", that `current_utc` "never falls back to real time", that "Fields that record 'when this happened' are stamped from `current_utc`", and closes the set with "**The one exception** is `received_at` on a payment milestone". A second, unmentioned time source is not a reading the PRD admits. Both now read `now()`; the pre-existing `_seq` insertion counter already tie-breaks every `created_at` ordering, so the resulting logical-clock ties are deterministic (film slate keeps its PRD-mandated `created_at` DESC / `id` ASC tie-break). Removed the now-unused `wall_now` import; `envelope.py`'s `api_request_timestamp` deliberately stays wall-clock, as it is a response-metadata field rather than a resource field.

### Final sweep evidence (8 parallel rounds, `results.$i.json`)
| Round | Passed / Total |
|---|---|
| 1 | 185 / 185 |
| 2 | 185 / 185 |
| 3 | 185 / 185 |
| 4 | 185 / 185 |
| 5 | 185 / 185 |
| 6 | 185 / 185 |
| 7 | 185 / 185 |
| 8 | 185 / 185 |

0 failed, 0 errors, 0 skipped in every round.

ORCHESTRATOR VERIFICATION (per the known "claimed clean sweep with no artifacts" failure mode): independently re-read all 8 `workspace/implementation/results.$i.json` files. All eight exist (~60.5 KB each, timestamped 01:50), and each reports passed=185, failed=0, errors=0, skipped=0, total=185. The clean sweep is real. Step 8 is NOT skipped — Step 7 applied 1 `implementation/` fix and 1 `test_suite/` fix.

## Step 8: Finalize PRD — 2026-09-05T02:00:00.000Z

Done. Two edits, both traceable to the single `implementation/` fix in `<step_7_diff>`.

## Line counts
- `PRD.md`: 542 lines
- `PRD_FINALIZED.md`: 544 lines
- Delta: +2 lines (+0.37%); 2 hunks (1 sentence revised, 1 paragraph inserted)

## Changes

- **§2.4 (Resource Identity, Audit Columns and the Logical Clock)** — *revise* — the "Fields that record 'when this happened' are stamped from `current_utc`" sentence now explicitly names `created_at` (every resource) and `updated_at` (wherever present) as reading the logical present instant, adds "There is no second, real-clock time source behind any resource field", and carves out `api_request_timestamp` as call metadata generated from the real clock — `implementation/store.py:56-72` (`base_row()` / `touch()` reading `now()`), `implementation/envelope.py:12`.
- **§2.3 (Pagination)** — *insert* — new paragraph pinning that, because `created_at` comes from the logical clock, ties on it are the normal case, and that wherever `created_at` is the last ordering key named (including the plain default and the `start_date` / `start_at` / `due_date` / `revision_round` orderings once their leading key ties) rows are returned in insertion order; the film slate keeps its own `id` ASC tie-break; leading keys unique within scope cannot tie — `implementation/store.py:75-81` (`creation_key` = `(created_at, _seq)`), `api_markets.py:88,201,320`, `api_contracts.py:418,480`, `api_finance.py:363`, `api_films.py:84-85`.

## No edit made for the `test_suite/` item
The round-limit precedence fix needed no PRD change: §2.7 already puts the own-state guard (rung 7, `ERR_INVALID_STATE`) above the round limit (rung 12) and explicitly lists countering under rung 7, and §3.4's "Both countering and revising require that `negotiation_round` be strictly below 4" already matches `api_contracts.py:210-213` and `:234-237` (state check first, then limit) exactly. That was a pure test-assertion bug, not a PRD silence. I deliberately did **not** add prose about `ERR_NEGOTIATION_ROUND_LIMIT` being unreachable on the counter branch — the impl does contain the check (`api_contracts.py:212`), so declaring it dead would itself be a new mismatch.

## Pre-edit search log

**Edit 1 — §2.4 time source**
- (a) Subject: which clock stamps which timestamp field, across every resource and the envelope.
- (b) Paths enumerated: `store.py:50-72` (`base_row`, `touch`); every `base_row(...)` callsite — `api_territories.py:78,122,154,227`, `api_markets.py:65,173,291`, `api_finance.py:76,201,281,335`, `api_contracts.py:145,392,453`, `api_films.py:52,208` (confirmed **all** row creation goes through `base_row`, so "every resource" is safe); all ~70 `touch(...)` callsites across `api_*.py` and `calc.py` (confirmed `updated_at` is never assigned outside `base_row`/`touch`); the three `versioned=False` callsites (`api_territories.py:78,122` territories/comparables, `api_finance.py:335` runs) which correctly carry no `updated_at` — hence the "wherever `updated_at` is present" hedge rather than "every resource"; `util.py:156` (`wall_now`) and its only remaining consumer `envelope.py:12`; `serializers.py:10-12`; `calc.py:317` (`facility_figures` reading `now()`).
- (c) Adjustments: wrote "`updated_at` wherever `updated_at` is present" instead of "on every resource", so the three version-free types in §2.4's own exception list are not contradicted. Added the `api_request_timestamp` carve-out specifically because "no second real-clock source" would otherwise falsely cover `envelope.py:12`; scoped the absolute claim to "behind any resource field".

**Edit 2 — §2.3 ordering tie-break**
- (a) Subject: the resolution of ties under every list ordering the spec names, now that logical-clock `created_at` collides routinely.
- (b) Paths enumerated: `store.py:75-81` (`creation_key`, `by_creation`) and all 15 `by_creation` consumers in `store.py:151-212`; every explicit sort in the codebase via a repo-wide `sort|sorted` grep — `api_films.py:84-85` (slate: `id` ASC then `created_at` DESC, stable => `id` ASC tie-break, *not* `_seq`), `api_territories.py:103` (`code` only), `api_markets.py:88,201,320`, `api_contracts.py:416,478`, `api_finance.py:361`, `calc.py:414,500,538`; uniqueness of the leading keys — `api_finance.py:275-279` (`ERR_TIER_ORDER_TAKEN`, so `tier_order` unique per account), `api_finance.py:336` (`run_index = run_count + 1`, unique per account), `ERR_TERRITORY_CODE_TAKEN` for `code`. Also checked whether iteration order leaks into arithmetic where a tie-break claim would bind: `calc.py:284-348` (per-contract discounting — each term independently `q2`-rounded then summed, order-independent), `calc.py:420-428` (`median_fee` — ties are equal fees, median value unaffected), `calc.py:506-553` (waterfall — driven by unique `tier_order`).
- (c) Adjustments: scoped the sentence to "wherever `created_at` is the **last** ordering key an endpoint names" rather than a blanket "all ties", so `api_films.py:84-85`'s `id` ASC is not overwritten; added the explicit film-slate carve-out sentence; added the final "leading key unique within its scope" sentence so the `code` / `tier_order` / `run_index` orderings are not implicitly given a tie-break rule the impl never exercises. Deliberately confined the paragraph to list results rather than all internal iteration, since the arithmetic paths above proved order-insensitive and a broader claim would have been an unverifiable universal.

ORCHESTRATOR VERIFICATION: PRD_FINALIZED.md exists at 544 lines and is NOT byte-identical to PRD.md (`cmp` reports DIFFERENT); the diff is exactly the two hunks reported above — one §2.3 paragraph insert and one §2.4 sentence revision. Step 8 genuinely ran.

## Step 9: Complete PRD — 2026-09-05T02:35:00.000Z

ORCHESTRATOR DECISION: Step 9 was run as **three sequential file-partitioned passes** over one shared `PRD_COMPLETED.md`, partitioned by implementation module rather than as a single subagent. A one-shot full scan of a 13-module / 3,789-line implementation reliably under-scans and can leave `PRD_COMPLETED.md` byte-identical to its source. Pass 1 owned the `cp`; passes 2 and 3 were forbidden from copying and advanced the file in place with Edit calls only. Each pass was told to read the other passes' modules freely for context but to confine its edits to its own partition, and to hand forward anything it spotted out of scope.

Partition:
- Pass 1 — app.py, envelope.py, errors.py, util.py, store.py, validation.py, serializers.py, api_films.py, api_territories.py
- Pass 2 — api_markets.py, api_contracts.py
- Pass 3 — api_finance.py, calc.py

### Pass 1 summary (verbatim)

Step 0: performed the `cp` itself: `cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` -> 544 lines.

Counts: **ambiguity-pins: 15**, **mismatch-revisions: 6**. All 21 edits in-paragraph; no sections or lines added. Final line count: 544 (21 lines differ from PRD_FINALIZED.md).

Changes:
- §2.1 — insert — ambiguity — a header present but empty/whitespace-only counts as absent for `ERR_UNAUTHENTICATED` — validation.py:36-39
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 24 lowercase-alphanumeric chars (PRD's example showed 20 uppercase) — util.py:194-198
- §2.3 — insert — ambiguity — a non-whole-number `limit`/`offset` is also 400; all other list query params are filters matched for exact equality as text, a non-matching or non-enum value yields an empty page rather than an error, unknown params are ignored — validation.py:222-229, api_films.py:77-82
- §2.4 — insert — ambiguity — client-supplied instants accept any fractional-second width, `Z` or numeric offset, and a zone-less value is read as UTC; normalised to UTC on store — util.py:114-136
- §2.5 — insert — ambiguity — a numeric input §3 gives no range is shape-checked only for being a finite number of the right kind, so 0/negative passes to the business rule — api_films.py:57,205,286
- §2.5 — revise — mismatch — the 6-decimal quantisation belongs to the *derived* accrual rate; stored ratio inputs (`base_value_index`, `commission_pct`) are echoed exactly as supplied — serializers.py:46,71 + calc.py:476-482
- §2.7 rung three — insert — ambiguity — a body FK present but unresolvable (unknown id, empty string, wrong JSON type) fails on the existence rung with 404; only an absent/null FK falls to the shape rung — validation.py:205-215, api_territories.py:207-218
- §2.7 rung four — insert — ambiguity — null == omitted; strings trimmed then required non-empty; numeric fields accept decimal-literal strings but never booleans; int fields accept zero-fraction numbers; a missing/non-object body reads as `{}` — validation.py:66-202, util.py:50-87
- §3.1 — insert — ambiguity — film PATCH bumps `version` on every accepted call, including a no-op or field-less one — api_films.py:101-115
- §3.1 — insert — ambiguity — expense `memo` is mandatory and non-empty; a logged expense persists no readable row — api_films.py:287
- §3.1 — revise — **mismatch** — both `DEVELOPMENT -> PACKAGING` and `PACKAGING -> IN_MARKET` are open to `HeadOfSales` **and** `PlatformAdmin` (PRD reserved one edge to each); PACKAGING asks for bare `EXECUTED`, not the in-force window — api_films.py:143,155
- §3.1 — revise — **mismatch** — `WRAPPED` is available to `PlatformAdmin` as well as `HeadOfSales` — api_films.py:143
- §3.3 — insert — ambiguity — `currency_code` accepts any non-empty string; no code list is consulted — api_territories.py:71
- §3.4 — insert — ambiguity — all three buyer PATCH fields optional; `version` bumps unconditionally — api_territories.py:187-196
- §3.4 — revise — **mismatch** — `outstanding_exposure_usd`/`net_unpaid_exposure_usd` are derived on every serialisation, not stored and recomputed at a listed set of events (so cascade-driven milestone write-offs are reflected too) — serializers.py:156-161
- §3.9 — revise — **mismatch** — wrap is driven by `HeadOfSales` or `PlatformAdmin` — api_films.py:143
- §4 intro — insert — ambiguity — a trailing slash routes identically — app.py:26
- §4 table `GET /films` — insert — ambiguity — undocumented `genre` filter — api_films.py:78
- §4 table `GET /territories` — insert — ambiguity — undocumented `region` and `market_tier` filters — api_territories.py:97-102
- §4 table `GET /territory-valuations` — insert — ambiguity — names the four filters (`film_id`, `territory_id`, `status`, `method`) — api_territories.py:249-252
- §5 intro — revise — **mismatch** — the catalogue claimed to list *every* identifier; unrouted paths return `ERR_NOT_FOUND` (404) and unsupported methods return `ERR_INVALID_REQUEST` at **405**, the one place that id is not 400 — app.py:44-53

Verified the full `ERROR_STATUS` map in errors.py against the §5 table: all 47 domain codes match, so no table edits were needed.

### Pass 2 summary (verbatim)

Did **not** `cp` or `Write` anything — every change was an `Edit` in place. Line count on entry: 544. Final: 546 (+2 from one new paragraph inside §3.4).

Counts: ambiguity-pins **16**, mismatch-revisions **4**.

Changes:
- §2.3 Pagination — revise — mismatch — pass 1's "a value matching nothing ... yields an empty page" was false for an empty filter value; added that a recognised filter supplied empty is treated as absent and narrows nothing — api_markets.py:86,196,315, api_contracts.py:186
- §2.5 Money/Precision — insert — ambiguity — pinned `pct_of_mg` as the one ratio field quantised on input (half-up to 4 dp before storage) and that `amount_usd` / the running total derive from the stored share — api_contracts.py:377
- §3.1 (film cycle) — revise — mismatch — `SOLD_OUT -> IN_MARKET` is re-evaluated by exactly two operations (reversion, final-rejection cascade); the `/lapse` endpoint never re-evaluates it, so a film whose licensed count already dropped stays `SOLD_OUT` — api_contracts.py:363,500 vs 325-343
- §3.1 (film cycle) — insert — ambiguity — both auto-edges are evaluated after the counters have already touched the film, so a request firing either moves the film's `version` by **two** — api_contracts.py:318-319,362-363,499-500
- §3.2 (meeting resolution) — insert — ambiguity — an `outcome` supplied with `NO_SHOW`/`CANCELLED` is ignored and `outcome` stays null — api_markets.py:337-349
- §3.4 (offer gates) — insert — ambiguity — both gates read state **before** the supersede lapse, so the superseded offer's own MG is still inside the gross-pipeline figure the credit gate measures — api_contracts.py:137-143
- §3.4 (new paragraph after contract creation) — insert — mismatch — `milestone_pct_total`, `unpaid_amount_usd`, `received_amount_usd` are derived per read from the milestone rows, not stored counters written at the named events; a never-countersigned contract already reports non-zero `unpaid_amount_usd` — serializers.py:207-209, calc.py:148-168
- §3.4 (counter) — insert — ambiguity — `counter_license_term_months`/`counter_holdback_days` are bounded like their twins but appear in no response and are never read again; countering moves neither the buyer's nor the film's `version` — api_contracts.py:207-222, serializers.py:184-211
- §3.4 (revise-offer) — insert — ambiguity — the exposure read precedes the overwrite so the contract's own standing MG is still in the sum; no buyer-trading-status recheck; a milestone whose recomputed `amount_usd` is unchanged is not touched — api_contracts.py:239-241, calc.py:76-82
- §3.4 (milestone creation) — insert — ambiguity — adding a milestone is not gated on `negotiation_status`, each addition bumps the contract's `version`, and `received_at`/`received_by_user_id` start null — api_contracts.py:373-409
- §3.4 (schedule rules) — insert/revise — ambiguity — no label is mandatory; the `ON_SIGNATURE` invoicing, `ON_DELIVERY` invoicing and `ON_RELEASE` re-dating are no-ops when the label is absent; dropped "stored" from `milestone_pct_total` — api_contracts.py:311,524,529
- §3.5 (six conditions) — revise — mismatch — dropped "stored" from "the contract's stored `milestone_pct_total`" — calc.py:148
- §3.6 (verdict) — insert — ambiguity — the state gate is the package's own status alone; the owning contract's `negotiation_status` is not re-checked — api_contracts.py:512-515
- §3.6 (final rejection) — insert — ambiguity — a `REJECTED_FINAL` package still gets `qc_result` `FAIL`, the `rejection_reason` **and** a `cure_deadline` of `submitted_at` + 30 days (stamped before the branch is chosen, inert) — api_contracts.py:537-543
- §3.9 (lapse) — insert — ambiguity — `reason` is mandatory and non-empty after trim but is retained nowhere — api_contracts.py:330
- §3.9 (reversion) — insert — ambiguity — the `collection_status != PAID` failure is `ERR_INVALID_STATE`, and the three checks run in the written order, making this the one place an `ERR_INVALID_STATE` is reported *after* a temporal check — api_contracts.py:350-356
- §4 `GET /markets` — insert — ambiguity — named the `status` filter — api_markets.py:85
- §4 `GET /screening-slots` — insert — ambiguity — named `market_id`, `film_id`, `status`, `room_number` — api_markets.py:194-200
- §4 `GET /buyer-meetings` — insert — ambiguity — named `market_id`, `buyer_id`, `film_id`, `status`, `table_number`; a `Buyer` sees every meeting — api_markets.py:313-319
- §4 `GET /pre-sale-contracts` — insert — ambiguity — named `film_id`, `buyer_id`, `territory_id` and all three status axes; a `Buyer` sees every contract — api_contracts.py:177-187

Verdicts on pass-1 hand-offs: derived contract counters CONFIRMED and fixed; `pct_of_mg` q4-on-input CONFIRMED and pinned; undocumented filters CONFIRMED on all four rows; plus pass 1's own §2.3 filter sentence needed an empty-value carve-out (mismatch #1).

### Pass 3 summary (verbatim)

Never ran `cp`, `Write`, or any whole-file rewrite. All 25 changes were `Edit` calls in place. Entry 546 lines -> exit **546 lines**; growth shows in words (15,862 in PRD_FINALIZED.md -> 19,119 in PRD_COMPLETED.md, 59 lines differing).

Counts: 25 edits — **14 ambiguity-pins**, **11 mismatch-revisions** (10 distinct mismatch topics; the §3.8 recompute-event-list mismatch took two edits).

Changes:
- §3.8 — revise — mismatch — deleted the claim that a facility is created with `eligible_collateral_usd`/`advance_amount_usd` at 0.00 pending a later recompute; creation figures the collateral immediately — api_finance.py:109
- §3.8 — revise — mismatch — the recompute event list no longer says "any facility state change"; pinned to creation, the `APPROVED` and `DRAWN` transitions, and completion-bond posting, and explicitly *not* the `DEFAULTED` transition — api_finance.py:134,151,159-163,183
- §3.8 — revise — mismatch — the cross-entity event list now names the `lapse` operation of §3.9, contract execution, reversion and the final-rejection cascade, and buyer amendment; added that neither the supersede cascade nor the wrap cascade recomputes any facility figure — api_contracts.py:141-143,321,342,364,498, api_films.py:128-131
- §3.8 — insert — ambiguity — `drawn_amount_usd` and `outstanding_debt_usd` are both set to the then-current `advance_amount_usd` at draw; later recomputes move `advance_amount_usd` alone — api_finance.py:155-156
- §3.8 — insert — ambiguity — drawing rewrites every `BANK_DEBT` tier cap on the picture's **open** accounts to the drawn amount, skipping tiers already at that value — api_finance.py:61-65,158
- §3.8 — insert — ambiguity — the completion-bond gate (rejected only from `REPAID`/`DEFAULTED`) and that a repeat posting overwrites provider and amount — api_finance.py:177-182
- §3.8 — insert — ambiguity — the `MARGIN_CALL -> DRAWN` cure condition on bond posting (advance >= drawn, compared after the recompute) — api_finance.py:184-188
- §3.8 — revise — mismatch — removed "a `DEFAULTED` facility's `BANK_DEBT` tier keeps recouping"; the tier derives `SUSPENDED` unless another facility of the picture is `APPROVED`/`DRAWN`/`MARGIN_CALL` — calc.py `tier_status`
- §3.8 — insert — ambiguity — a recompute writing an unchanged set of figures is suppressed (no `version`/`updated_at` movement), while approve/draw/bond always refresh the row — calc.py `write_facility_figures`, api_finance.py:141,157,189
- §3.8 — insert — ambiguity — per-contract q2 rounding before the q2 sum, the unbonded 0.50 haircut applied after the advance rate, the q6 discount factor, tenor from the latest milestone `due_date` — calc.py `facility_figures`
- §2.5 — revise — ambiguity — extended pass 1's quantisation insert to name `discount_rate_pct`, `advance_rate_pct` and `pct_of_available` as stored exactly as supplied — api_finance.py:81-92,267-272
- §3.9 — insert — ambiguity — the residual sweep is a single pass to the highest-`tier_order` uncapped `ACTIVE` tier; a tier allocated nothing is never rewritten — calc.py `run_waterfall`
- §3.9 — revise — mismatch — new-tier status is derived by rule: `SATISFIED` at once when `cap_usd` <= 0.00, `SUSPENDED` at once for a `BANK_DEBT` tier with no live facility; tier creation is not gated on the account's status — api_finance.py:281-294, calc.py `tier_status`
- §3.9 — revise — mismatch — every lapse recomputes the picture's live facilities and may drive one `DRAWN -> MARGIN_CALL`; the `LICENSED -> PUBLISHED` return is reachable only via the final-rejection cascade since `lapse` refuses an `EXECUTED` contract — api_contracts.py:332,342,486-499
- §3.9 — insert — ambiguity — distribution debits `outstanding_debt_usd` on every `DRAWN`/`MARGIN_CALL`/`DEFAULTED` facility of the picture by the same total (not pro rata), floors at 0.00, and flips only a `DRAWN` facility to `REPAID` — calc.py:556+
- §3.9 — insert — ambiguity — a `MARGIN_CALL` or `DEFAULTED` facility whose debt reaches 0.00 stays in its status — calc.py:556+
- §3.7 — insert — ambiguity — `amount_in_usd` has no lower bound: 0.00 and negatives pass the balance check and produce a run allocating 0.00 to every tier with the negative carried into `residual_usd` — api_finance.py:313-317,342
- §3.7 — insert — ambiguity — `ERR_COLLECTION_ACCOUNT_NOT_OPEN` ordered ahead of `ERR_INSUFFICIENT_ACCOUNT_BALANCE`, both after body coercion — api_finance.py:313-317
- §3.7 — insert — ambiguity — a picture may hold several `OPEN` accounts; receipts/reversals target the **earliest-created** `OPEN` one — api_finance.py:54-58
- §3.7 — insert — ambiguity — opening an account consults nothing about the picture's `sales_status` — api_finance.py:196-214
- §3.7 — insert — ambiguity — the receipt rejection order (milestone status -> contract `EXECUTED` -> open account -> amount equality) — api_finance.py:380-388
- §3.7 — insert — ambiguity — commission accrues against the film's `EXECUTED` agreement, falling back to the earliest agreement of any status; with no agreement the receipt still posts with `accrued_commission_usd` 0.00 — api_finance.py:395-406, calc.py `agreement_for_film`
- §3.7 — revise — mismatch — reversal resyncs the `SALES_COMMISSION` tier only, not the expense tier (which a receipt does resync) — api_finance.py:412-413,456
- §3.6 — revise — mismatch — replaced the three-edge `collection_status` transition list with re-derivation from the milestone set, so `UNPAID -> PAID` in one receipt and `PAID -> UNPAID` in one reversal are both normal for a single-milestone contract, and `WRITTEN_OFF` is terminal — calc.py `resync_collection_status`/`derive_collection_status`
- §3.1 — insert — ambiguity — the five film counters, `financing_gap_usd` included, are derived fresh on every read from live contracts — calc.py `film_counters`
- §2.4 — insert — ambiguity — the clock may be set backwards as freely as forwards; the endpoint answers with an empty `data` object — api_finance.py:466-472
- §2.3 — insert — ambiguity — endpoints other than the ones §4 documents as filterable ignore unknown query parameters entirely (facilities, accounts, tiers, runs, agreements accept `page`/`page_size` only) — validation.py `page`, api_finance.py:117,221,301,365

Verdicts on the eight hand-off items: (1) facility creation figures CONFIRMED+fixed; (2) `outstanding_debt_usd` CONFIRMED+fixed; (3) recompute event set CONFIRMED and worse than reported — "any facility state change" also overstated, and two of three routes to `LAPSED` do not recompute; (4) rate quantisation PARTLY pre-covered, extended to name the three unquantised rate fields; (5) `apply_run_cross_effects` breadth CONFIRMED+fixed; (6) error-code half pre-covered, precedence and the absent lower bound on `amount_in_usd` CONFIRMED+pinned; (7) false `financing_gap` claims CONFIRMED+fixed; (8) undocumented filters CONFIRMED in the opposite direction — pass-3 endpoints accept no filters at all, so the generic "unknown query parameters are ignored" rule was pinned in §2.3 instead.

### ORCHESTRATOR VERIFICATION of Step 9

`workspace/PRD_COMPLETED.md` exists at 546 lines / 19,119 words. It is NOT byte-identical to its source (`cmp` reports DIFFERENT vs PRD_FINALIZED.md; 116 lines differ, +3,257 words) — the partitioned scan genuinely ran across all three passes rather than degenerating into a copy. All five top-level sections survive (`## 1`–`## 5`), §4 and §5 headings intact, and the file still ends at a real section boundary (final `ERR_EXPENSE_LOG_LIMIT | 422` row of the §5 catalogue) — no truncation. 62 combined edits across the three passes: 45 ambiguity-pins and 21 mismatch-revisions (counting pass 3's two-edit §3.8 topic once each).

### PIPELINE COMPLETE

All nine steps finished. Final state: 3 scaffold YAMLs, 185-test suite (9 test_helpers modules + 11 test_suite modules), a 13-module Python/Flask implementation passing 185/185 in all 8 parallel stability rounds, and the three-stage PRD chain PRD.md (542) -> PRD_FINALIZED.md (544) -> PRD_COMPLETED.md (546).
