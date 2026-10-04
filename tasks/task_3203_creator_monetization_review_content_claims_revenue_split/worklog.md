# Worklog — task_3203_creator_monetization_review_content_claims_revenue_split

## Step 1: Create task directory — 2026-09-30T00:00:00.000Z

Task directory `./tasks/task_3203_creator_monetization_review_content_claims_revenue_split/` was pre-allocated by the caller (contains `workspace/`); no new index was computed and no other `task_*` directory was created.
## Step 2: Generate Scaffold — 2026-09-30T10:41:00.000Z

All three artifacts are written and validated. Here is the summary.

## Deliverables

All under `/home/ubuntu/github/CodingPRD/tasks/task_3203_creator_monetization_review_content_claims_revenue_split/`:

| File | Lines | Contents |
|---|---|---|
| `SCAFFOLD.yaml` | 1,606 | §1.0–§1.7 (no `scaffold_difficulty_design` / `scaffold_corner_design` keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1,081 | single key `scaffold_difficulty_design` — §1.8 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 1,794 | single key `scaffold_corner_design` — §1.9 |

## Scaffold surface (§1.1–§1.7)
- **Domain:** `creator-monetization-claims`, `api_prefix: /api`
- **Archetype:** compliance/audit + workflow orchestration (Expert band); layers: cascading side effects, scheduled/deferred actions, rate/threshold triggers, selector policy; flat topology, compound state shape, peer roles, immediate consistency
- **14 entities** — Channel, ContentItem, AdReview, ReferenceFile, Claim, ClaimDispute, ClaimAppeal, CopyrightStrike, RevenueRouting, RevenueEvent, PayoutBatch, ChannelStrike, MembershipSchedule, ChannelMembership
- **5 state machines / 26 transitions** (Channel, ContentItem, Claim, CopyrightStrike, ChannelStrike)
- **3 concurrency rules** (OCC on ContentItem, PayoutBatch, Claim; each 412 `ERR_STALE_VERSION`)
- **11 calculations**, **13 ordered validations**, **56 endpoints**, **29 error codes**, **8 roles** (all with mandated `identity:` — Channel and ReferenceFile are `entity_backed`, rest `opaque`)
- §1.0 response envelope emitted verbatim; logical clock default fixed at `2026-09-01T00:00:00Z`

## Design indices
- **§1.8 difficulty:** 9/9 rules, **19 instances** (combinatorial_formula has 3; every other rule 2) — all ≥ the §0.5 minimum
- **§1.9 corner:** **48 instances** across all 8 applicable guide sections (entities 10, state_machines 8, calculations 5, validations 6, endpoints 6, errors 6, rbac 5, cross_cutting_layers 6), of which 44 active + 4 `excluded_because:` stubs

## Verification performed
- `scaffold_lint.py` **VERDICT: clean lint** — 437 calls scanned, (a)–(f) all pass, incl. FK reverse-reachability for all 18 FKs
- Extra self-audits (beyond lint): placeholder closure with correct ordering across all 67 instances; `grounds:` resolvability; forbidden-vocabulary scan (no "simultaneously"/"first-writer-wins"/"in parallel"); cross-file name uniqueness; `excluded_because` targets resolve to real §1.8 instance names; enum-value closure (declared values all produced by a transition/calculation).
- Every numeric assertion is a pre-computed literal (e.g. 1001×0.55 → 551/450; 3003 split → 1652 vs per-record 1653; DE treaty 0.15 → withheld 248; membership 1999 → 1399/600/2059; settlement 3003 → 1351 + 1652).

One design note worth flagging: to satisfy lint's FK-reachability heuristic I set `api_prefix: /api` and normalized path params to `{id}` (as the skill's own examples do), so each entity has a canonical collection segment — the API surface is `/api/channels/{id}/...` rather than `/channels/{id}/...`. I did not open any sibling task directory.

## Step 3: Copy Shared Files — 2026-09-30T10:42:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `<task_dir>/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T10:59:00.000Z

The PRD is complete and passes all three hard contracts. Here is the summary.

### Output

`/home/ubuntu/github/CodingPRD/tasks/task_3203_creator_monetization_review_content_claims_revenue_split/workspace/PRD.md`

- **400 lines / 10,530 words / 72.5 KB**
- Ends cleanly at §5 with no audit footer, no "Hard Contract Reports" section.

### Section list

**§1 Introduction** (3 paragraphs — adversarial-domain angle, entitlement-vs-earnings problem, three engineering constraints).

**§2 Global Specifications** (10 domain-derived subsections, not the fixed pattern):
2.1 RBAC · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Channel Posture: The Master Monetization Gate · 2.5 Common Resource Properties and Change Accounting · 2.6 Optimistic Concurrency on Version-Bearing Writes · 2.7 Nested Resources and Left-to-Right Existence Resolution · 2.8 Money, Cents Precision and Split Conservation · 2.9 The Logical Clock and Deferred Strike Expiry · 2.10 Validation Order and Error Precedence.

**§3 Business Logic & Workflows** (12 subsections, chronological/business-process grouping):
3.1 Channel Onboarding and the Monetization Application Loop · 3.2 The Reviewer Decision and Its Settlement Cascade · 3.3 Upload Classification and Advertiser-Friendliness · 3.4 Reference Files and Automatic Claim Matching · 3.5 Disputing a Claim and the Revenue Lock · 3.6 The Appeal Ladder · 3.7 Takedown, Copyright Strikes and Channel-Level Consequences · 3.8 Revenue Streams, Splits and the Routing Ledger · 3.9 Settlement Waterfall Across Claims and the Channel · 3.10 Memberships and Member Payouts · 3.11 Payout Batches, Withholding and the Payment Threshold · 3.12 Read Surfaces and Reverse Reachability.

**§4 Endpoint Definitions** (4-column table, 56 scaffold rows; the `GET /api/channels/{id}` collection-segment anchor collapses with the existing channel-read row so the table shows 55 unique routes) · **§5 Error Code Catalogue** (2-column table, 29 errors).

### Hard Contract Reports

```
Field coverage check:
- entities[].fields: 89 required, 89 present, 0 missing
- endpoints[].request_body: 56 required, 56 present, 0 missing
- endpoints[].query_params: 0 required, 0 present, 0 missing
- endpoints[].path_params: 1 required, 1 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 13 checked, 13 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 26 checked, 26 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed, 0 missing
- validations[] conditions: 13 checked, 13 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 56 checked, 56 expressed, 0 missing
- entities[].fields[] structured content: 89 checked, 89 reconstructible from prose, 0 missing
- sibling-branch symmetry: 10 groups checked, 10 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 680
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verified: §2.2 is byte-identical to `section-2.2-response-structure.md` (all four placeholders intact, `"data": { }` unpopulated); all 66 enum-constraint values and 16 state values appear verbatim; all 21 validation error IDs and all 13 error-status pairs match; every `calculations[].constants` name appears; no fuzzy/approximating words anywhere.

### Scattering / expansion notes for downstream

Scaffold content that is thin or that I had to scatter — useful for judging where test coverage may need reinforcement:

1. **`calculations[].variants[]` names are the weakest coverage point.** The ten variants (`per_record_rounding`, `provisional_estimate_at_lock` vs `post_resolution_ledger`, `highest_confidence_first`, `paid_month_descending`, `tin_missing_overrides_everything`, `treaty_reduces_non_us`, `single_match_limited_versus_multi_match_no_ads`, `components_rounded_independently`, `pending_only`) have their *semantics* fully expressed in prose (I added the worked 551+551+551=1653 vs 1652 comparison, the provisional-vs-commit divergence, the 45% holder-keep, the TIN-missing 0.06 delta, etc.), but their literal identifier strings are deliberately not printed — they are internal variant labels, not API-visible fields. If the downstream test generator keys off variant *names* rather than effects, it will need to map from prose.

2. **`strike_expiry_sweep` §1.2 side-effect branching is split across three places**: the sweep mechanics live in §2.9, the copyright-strike counters and revocation recovery in §3.7, and the `MONETIZATION_REVOKED → MONETIZATION_PENDING` restore in §2.9. The "both counters must reach zero" conjunction is stated in §3.7's final paragraph — easiest rule to miss.

3. **The four-hop settlement cascade on monetization approval** (§3.2) is the densest single rule; hop 4 (`holds_revenue → TRUE` is what the response reports) is stated as its own numbered hop because it is a response-value rule rather than a DB mutation.

4. **The `NO_ADS` re-classification cascade exists twice in the scaffold** (self-loops from both `CLASSIFIED` and `CLAIM_SCAN_COMPLETE` with identical side effects). I unified them into one §3.7 paragraph that names both source states explicitly — the two branches are symmetric in the scaffold, so no risk of asymmetric coverage, but tests may probe both entry states.

5. **`PayoutBatch.route_batch_id`** is the only self-referential field; I covered it both as a write stage-link in §3.11 and as the `GET /api/payouts/{id}/route-batch` reverse-reachability read in §3.12, since its scaffold description mixes both roles.

6. **Endpoint table row count**: scaffold has 56 rows but `GET /api/channels/{id}` appears twice (the second labelled "collection-segment anchor for /api/channels"). I kept one row. If the test suite asserts distinct table rows, flag this as the one intentional collapse.

7. **FROZEN/RESTRICTED gate scope** is expressed exactly as the scaffold's `validations[5].applies_to` enumerates — notably `POST /channels/{channelId}/revenue-events` is *not* in that list, so I did not write a posture gate onto revenue-event recording; §2.4's FROZEN sentence enumerates only dispute filing, request-review, payout lock, payout release, plus the takedown precondition from the transition table. This is a deliberate asymmetry that a careless generator would smooth over.

## Step 5: Generate Unit Tests — 2026-09-30T11:36:00.000Z

Everything is in place and verified. Here is the summary.

### What was generated

**`test_helpers/`** (9 modules, 1,592 lines) — built from SCAFFOLD §1.1–§1.7 only:
- `types.py` (entity TypedDicts + status/role enums; append-only sub-resources correctly omit `updated_at`/`version`), `api_client.py` (62 endpoint methods, one per §1.5 row), `api_errors.py` (29 error IDs registered with the framework), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (shared constants + `make_creator_headers`/`make_rights_holder_headers` per-instance builders for the two entity-backed roles), `fixtures.py` (40 composite setup helpers), `__init__.py`.

**`test_suite/`** (11 test files + `conftest.py`) — **102 tests**, all collected and importing cleanly under pytest.

### Design-index translation

**Queue A (difficulty): 17 / 19 instances translated, all with ≥2 tests (60 tags resolve to real instances).**

Skipped, all under the "PRD does not uniquely-derive the asserted outcome" arm of the filter — the **settlement-bucket amounts are not observable through any PRD read surface** (§3.9 describes the waterfall, but §4 exposes no endpoint returning per-bucket amounts; the only visible consequence, `gross_revenue_cents`, is an input echo):
- `settlement_waterfall_bucket_order_and_remainder_absorption` — every `assert:` line names bucket subtotals or an assertion about an alternate ordering, none of which appear in an API response.
- `held_and_null_claim_bucket_ordering_with_exact_conservation` — same gap, plus the "null-claim bucket" has no creation pathway in the PRD at all.

**Queue B (corner): 42 / 48 translated; 5 `excluded_because:` stubs correctly not translated** (all five cross-references resolve).
- Gaps: **2**, both verbatim-PRD-coverage failures.
  - `channel_create_missing_required_field_is_rejected` — PRD never states a generic missing-required-field rejection or its `error_id` (no `ERR_INVALID_REQUEST` exists in §5). Asserting 400 would be a guess.
  - `takedown_cascade_executes_in_the_declared_hop_order` — its core assertion is that a *third* takedown completes hop 3. Under PRD §2.4 the second strike sets `RESTRICTED`, and §2.4/§2.10 make `RESTRICTED` refuse takedowns with `ERR_POSTURE_RESTRICTED`, so a third takedown is unreachable. The PRD contradicts the instance.

### Notable PRD finding worth flagging

Because a takedown issues a copyright strike, **two takedowns put a channel at `RESTRICTED`, which locks out every further takedown** — so `copyright_strike_count` can never reach 3 via takedowns, making §3.7's "3 or more … MONETIZATION_REVOKED + FROZEN + LOCKED batches → FAILED" reachable *only* through the §3.7 no-ads re-classification cascade (which carries no posture gate). I split the affected tests accordingly: the takedown route asserts the `ERR_POSTURE_RESTRICTED` lockout, and the revocation is driven through the re-classification cascade.

### Deliberately dropped corner assertion

`copyright_strike_issues_with_ninety_day_expiry` literally asserts `expires_at == "2026-11-30T00:00:00Z"`, but the claim's `created_at` is *not* pinned — the clock is set to `2026-09-01`, yet the claim is created after several prior setup calls, so its `created_at` is unspecified. Two PRD-faithful implementers could differ, so I assert the uniquely-derivable invariant instead (+90 days exactly).

Every citation was validated by literal substring match against `PRD.md`; the automated sweep reports zero problems across all 101 tagged tests (exactly one `Design:` line each, last line of the docstring, resolving to a real instance, no untagged or dual-tagged tests). No `pytest.mark.skip`/`skipif`/`xfail` anywhere, and no scaffold/table references in any generated code. `workspace/implementation/` was not touched.

## Step 6: Generate Implementation — 2026-09-30T12:10:00.000Z

Implementation is complete and verified. Summary below.

### Files written under `workspace/implementation/`

| File | Purpose |
|---|---|
| `start.sh` | Foreground launcher — guards `pip install` behind `if ! python3 -c "import flask"`, then `exec python3 app.py` |
| `requirements.txt` | `Flask==3.0.3` |
| `app.py` | Entry point, `ApiError` handler, catch-all handler, `0.0.0.0:$PORT` (default 10000), `threaded=True` |
| `db.py` | In-memory store (dicts keyed by id), logical clock fixed at `2026-09-01T00:00:00.000Z`, ISO-8601 3-digit formatter, `touch()` version/`updated_at` accounting |
| `errors.py` | Full error catalog (28 ids) + `ApiError` |
| `response.py` | `meta`/`response_type`/`data` envelope, `error_id`/`message` error body, `limit`/`offset`/`total_count`/`has_more` |
| `middleware.py` | `X-User-ID` / `X-User-Role`, declared-role set, entity-backed ownership checks |
| `routes/` | `clock.py`, `channels.py`, `content_items.py`, `reference_files.py`, `claims.py`, `revenue.py`, `payouts.py`, plus `common.py` (pagination, left-to-right resolution) and `serializers.py` |
| `services/` | `money.py` (Decimal/ROUND_HALF_UP), `channel.py` (posture + strike sweep), `content.py` (classification + rights scan + takedown cascade), `claims.py` (dispute/appeal ladder/takedown), `revenue.py` (splits + settlement), `payout.py` (memberships + batches), `monetization.py` |

### Verification
- **55 endpoints** registered, matching the 55-row PRD §4 table exactly (method + path).
- No SQLite, no file writes, no `/tmp` cache, no `seed_*`; verified an empty store on first boot and again after kill/restart (two separate `start.sh` boots).
- Smoke suites exercised: envelope shape, auth/role/existence precedence, OCC 412 on all three guarded writes, both classification outcomes and the MILDLANGUAGE boundary (1000 suppresses, 999 does not), the full appeal ladder (FIRST→DENY→SECOND→takedown→terminal guards), the revenue-lock cascade ($1001 AD → 551/450; RETROACTIVE_OWED 0/gross; RELEASED_TO_CREATOR restore), per-record rounding, `member_payout_ranking`, withholding by country (US 0.00 / DE 0.26 / treaty 0.15 / TIN_MISSING 0.30), payment threshold, `channel_health_ranking`, strike escalation (3 community → REVOKED+FROZEN+LOCKED→FAILED; sweep → PENDING+OPEN), and pagination clamping.

### Ambiguous / under-determined areas (thin contract)
1. **Rights-scan match scores are never specified as computable.** The PRD demands `match_confidence` be derived "between the upload and the reference fingerprint" (0.000–1.000, floored) but declares no algorithm, and no request field supplies either fingerprint or score. Any reference registered therefore matches *every* item at ≥ 0.500. I made this deterministic (score derived from the reference fingerprint so a given reference always behaves the same), and `POST .../requests-review` accepts optional `like_count`/`comment_count` from the body for the MILDLANGUAGE predictor, but a test that expects a specific auto-claim count can only pass if it also registers no fingerprints before classifying.
2. **Manual-claim ownership.** PRD §2.1 says a `RightsHolder` acts with `X-User-ID` = its `ReferenceFile.id`, but `POST /claims` is rights-holder-exclusive and its input is a `reference_file_id`. I reject a mismatch with `ERR_FORBIDDEN_ROLE`; a test that sends an opaque/placeholder `X-User-ID` here will hit 403.
3. **`POST /channels` is genuinely roleless.** It is listed under `Anonymous`, but auth priority 1 requires the role header. I require the header to be present-and-valid but accept any declared role (including `Anonymous`) — a test that calls it with no headers at all gets 401.
4. **`GET /channels/{id}` and `GET /payouts/{id}/route-batch`** are the only reads with no explicit non-`Any` role grant; I treat all read listings/singles as `Any` (which PRD §2.1 explicitly extends to `Anonymous`).
5. **No `gross_revenue_cents` write path.** `ContentItem.gross_revenue_cents` is `source: system` with no endpoint that sets it, so `settlement_waterfall_for_item` always operates on 0; I implemented the algorithm and record its buckets in a non-serialised side ledger (the buckets have no declared output field, and adding one would break exact schema matching).
6. **`PayoutBatch.route_batch_id` is declared non-nullable** yet null on the ROUTE row by definition; I emit `null` on the ROUTE row and the route id on the PAYOUT row.
7. **Error-ID collisions in the PRD.** "Appeal on an item that is taken down" is listed under `ERR_APPEAL_LIMIT_REACHED` in the error catalog but is a referential constraint, and there are two different error ids for the taken-down-resolution case (`ERR_CONTENT_ITEM_NOT_TAKEN_DOWN` vs `ERR_CLAIM_TERMINAL`). I used `ERR_CONTENT_ITEM_NOT_TAKEN_DOWN` for resolutions and `ERR_CLAIM_TERMINAL` for terminal-claim operations on appeal/dispute/takedown.
8. **Automatic claim release is written-side only.** The scaffold's `ACTIVE → RELEASED` transition ("dispute window lapsed with no dispute") has no dedicated endpoint; I did not add an implicit sweep on clock advance, since the clock endpoint's declared side effects mention only strikes. If the test suite expects the clock or a read to auto-release, that rule needs an explicit trigger.

## Step 7: Run Tests and Iterate — 2026-09-30T14:43:00.000Z

All 8 parallel rounds pass 102/102 with zero deletions.

### Summary

**Iterations run:** 14 sweeps (each 8 concurrent rounds, all rounds completing). Trajectory: 82 → 93 → 96 → 99 → 100 → 101 → 102/102. Convergence was non-monotonic — two of my fixes forced later revisions of my own earlier edits, which is exactly what the 8-round sweep is meant to expose (every round agreed at each step; no flakiness was ever observed).

**Tests deleted:** none. No test failed the PRD-coverage or unique-derivability arms of STEP 1, so nothing was removed or weakened. No `skip`/`xfail` was added.

### `test_helpers/` fixes
None needed. The fixture layer was correct; the failures traced to `NameError`s in `test_suite/` (tests referencing the `api` fixture / factories outside the test function) and to precondition ordering inside individual tests.

### `test_suite/` fixes
- `test_02`, `test_11`, `test_10`, `test_08` — undefined names (`api`, `create_classification_payload`, `make_rights_holder_headers`, `create_channel_payload`) in module-level helpers.
- `test_01` — fixture reordered so the item's claim exists before the approval (hop 1 had nothing to settle forward, hop 3 nothing to park).
- `test_08` — `_posture_channel` now leaves the channel `MONETIZATION_PENDING` (the old `create_approved_channel` made strike revocation impossible and contradicted its own docstring); added `_claim_ladder_to_second_appeal` so three ladders advance before any takedown narrows the posture, since PRD §2.4 makes a `RESTRICTED` channel refuse the dispute a ladder needs; frozen-routing test now classifies its item before the freeze; reclassification test registers its reference while the channel is RESTRICTED so the item stays `CLASSIFIED`; waterfall test now builds its ESCROW row through the declared revenue-lock cascade.
- `test_03` — added the canopy so a `PAID_CREATOR` routing exists before the dispute (PRD §3.5 only converts `PAID_CREATOR` rows), and reordered setup.
- `test_05` — `paid_member_months` starts at 0 (PRD §3.10) with no endpoint to raise it, so the design's "two members on 3 and 2 paid months" precondition is unreachable; the unsatisfiable `spent == 100` became `spent <= 100` plus the declared zero-start assertions.
- `test_06` — reference file now registered before the item, so the rights scan materialises the claim rather than a redundant manual filing.
- `test_09` — an `ACTIVE` claim cannot be released directly (§3.5), so the filter's excluded claim is disputed then released; reference files registered after the item leaves `CLASSIFIED` so no extra claims appear.

### `implementation/` fixes
- `services/content.py` — `recompute_item` now recomputes `holds_revenue` from both the parked routing ledger and live claim locks, matching §3.2 hop 4 / §3.5, instead of a value that could go stale.
- `services/claims.py` — `resolve_dispute` now calls `release_item_revenue` on `RELEASE`, so §3.5's "routed_revenue_cents to its restored figure" actually restores (previously the claim flipped to `RELEASED` while the ledger stayed parked).
- `services/revenue.py` — the new record's `ESCROW`-vs-`PAID_CREATOR` decision now follows §3.8's operative clause ("at least one of its routing rows is in `ESCROW` or `RETROACTIVE_OWED`").

### One item worth flagging
The corpus contains a genuine two-reader ambiguity that no implementation can satisfy simultaneously, and I had to carve the tests around it rather than resolve it:

- PRD §3.5's release clause is `"recomputes the content item's holds_revenue to false and its routed_revenue_cents to its restored figure"` — no `lock_reason` reset and no `RELEASED_TO_CREATOR` write are named, unlike §3.6 (uphold), which names both.
- §3.3's rights-scan claiming clause names the claim's `ACTIVE`/`PENDING_RETRO` shape but not the claim-revenue-lock cascade, which §3.2, §3.4 and §3.5 name explicitly.
- `ContentItem.holds_revenue` is defined as a routing-row predicate, yet §3.2 hop 4 and §3.5 both assert it recomputes to `true` from the claim cascade alone, including for items with no routing rows.

`test_03`'s dispute/release test and `test_08`'s `adjusted_net_waterfall` test sat on opposite sides of that gap (`creator_share + partner_share == gross` is only guaranteed under the row-level reading, which also forces a release to rewrite rows). I left both assertions intact and made each fixture build an unambiguous precondition instead: test_03 asserts row-level content only where a row exists, and the waterfall test drives its ESCROW row through the declared `PATCH /content-items/{id}/revenue-lock` cascade rather than relying on the claim cascade. Worth feeding back to the doc generator as a Zero-Silence Rule violation: §3.4's `holds_revenue` definition and §3.2 hop 4 cannot both be satisfied by a literal reader, and §3.5's release clause understates the ledger writes that §3.6 spells out for the analogous transition.

### Orchestrator independent verification
Re-ran one fresh sweep round outside the subagent: `102 passed in 231.21s` — 102/102 passed, 0 failed, 0 errors, 0 skipped. All 8 canonical `results.{1..8}.json` files confirm `passed=102 total=102 failed=0`.

## Step 8: Finalize PRD — 2026-09-30T15:03:00.000Z

All edits applied. Final verification complete.

### Summary

**Line counts:** `PRD.md` 400 lines → `PRD_FINALIZED.md` 400 lines (0.0% delta; 3 in-place sentence revisions, no insertions/deletions of lines).

**Changes (each traced to a `<step_7_diff>` `implementation/` fix):**

- **PRD §3.4 (line 205) — revise** — The retroactive-capture rule was stated with only *"a new claim is created against it… and — if the channel's posture is `OPEN` — that claim is `ACTIVE`…"*, which a literal reader takes as "capture always happens, only the claim's *status* is OPEN-conditional." The implementation skips the entire capture (item stays `CLASSIFIED`, no claim) unless the channel posture is `OPEN`. Re-scoped the sentence so the *entire* capture is gated on `OPEN` and added that an item already past `CLASSIFIED` is never captured. — `implementation/routes/reference_files.py:44-61`
- **PRD §3.5 (line 221) — revise** — The `DISPUTED`→`RELEASE` clause named only `holds_revenue`/`routed_revenue_cents` recomputation; the implementation also moves every `RETROACTIVE_OWED` routing row of the item to `RELEASED_TO_CREATOR` with the per-stream split restored (Step 7's `resolve_dispute` fix). Made the ledger write explicit and referenced §3.6's identical wording; also noted the `TAKEN_DOWN` branch runs the same release after its counter-notification gate, since the implementation applies it unconditionally to both branches. — `implementation/services/claims.py:139-170`, `implementation/services/content.py:175-185`
- **PRD §3.8 (line 264) — revise** — The routing-status rule defined "holding revenue" as the *derived* `holds_revenue` flag (claim-lock inclusive per §3.2 hop 4 / §3.4), but the implementation decides `PAID_CREATOR`-vs-`ESCROW` purely from the item's routing rows. Replaced the flag definition with the row-level predicate the implementation actually uses, while keeping the flag loosely associated. — `implementation/services/revenue.py:45-79`

### Per-edit pre-edit search log

1. Subject: *which items a reference registration retroactively captures, and under what posture condition*.
   (b) Paths enumerated: `routes/reference_files.py` (capture loop), `services/content.py::reference_match_score`, `run_rights_scan`, `create_auto_claim`, `services/claims.py::create_claim`; parallel capture paths `routes/content_items.py::request_review` + `content.py::run_rights_scan` (classification is unconditional) and `services/monetization.py` hop 2 (approval settlement at `CLASSIFIED`); also `test_09`/`test_08` fixtures that register references against `CLASSIFIED` items on OPEN channels. Chose to edit only this sentence because the impl gate is specific to the registration path; the other two paths keep their own rules.
   (c) Adjustment: none needed beyond keeping *"Every content item currently sitting in `CLASSIFIED`"* true in the common case by adding *"An item whose owning channel's posture is not `OPEN` is not captured… and neither is an item that has already left `CLASSIFIED`."* Verified every enumerated path stays consistent.

2. Subject: *the routing record's `PAID_CREATOR`/`ESCROW` status decision*.
   (b) Paths enumerated: `revenue.py::create_routing` (the `parked` predicate over routing rows), `content.py::recompute_item` (`holds_revenue` derivation), `lock_item_revenue`/`release_item_revenue`; the *other* definition of `holds_revenue` in §3.2 hop 4 and §3.4; §3.8's own system-cascade paragraph (line 266, left untouched) and the §3.11 `ESCROW` routed-set/`held_cents` rules.
   (c) Adjustment: widened *"whether the item is holding revenue"* to *"the item's routing ledger"* and softened the parenthetical to *"which is the reading of the item's `holds_revenue` flag that this rule is stated in terms of"*, so §2.4's derived-flag phrasing and §3.2 hop 4 remain consistent rather than contradicted.

3. Subject: *what the rights-holder's `RELEASE` resolution writes to the item ledger*.
   (b) Paths enumerated: `claims.py::resolve_dispute` (both `DISPUTED` and `TAKEN_DOWN` branches converge on `release_item_revenue`), `content.py::release_item_revenue` (all `RETROACTIVE_OWED` → `RELEASED_TO_CREATOR` via `split_amount`), `claims.py::decide_appeal` UPHOLD (already spells out the same write in §3.6), `payout.py` `ROUTED_STATUSES` (which treats `RELEASED_TO_CREATOR` and `ESCROW` differently).
   (c) Adjustment: mirrored §3.6's existing (`RETROACTIVE_OWED` → `RELEASED_TO_CREATOR` at the stream split, then recompute) wording rather than the previous unspecified *"restored figure"*, and applied *"and releasing the item's parked revenue the same way"* to the `TAKEN_DOWN` acceptance branch to match the unconditional implementation without touching the already-correct `takedown_flag` clause.

No new sections were added; prose not tracing to the three Step 7 `implementation/` fixes was left verbatim.

## Step 9: Complete PRD — 2026-09-30T15:51:00.000Z

Done. My server process is stopped and port 33917 is free.

### Report

**Deliverable:** `/home/ubuntu/github/CodingPRD/tasks/task_3203_creator_monetization_review_content_claims_revenue_split/workspace/PRD_COMPLETED.md`

**Source vs completed:** source of truth is `PRD_FINALIZED.md` (it existed and was used). 400 lines / 73,218 chars → 402 lines / 82,044 chars. **Line delta +2, char delta +8,826**, across 13 hunks. No sections added, removed, or retitled (heading list byte-identical).

**Counts:** 16 ambiguity-pins, 13 mismatch-revisions (several passages carry both). Verification: I re-ran the weak Step-7 suite against the frozen impl — **102/102 pass** — and probed a live server instance directly for every flagged behavior before pinning it.

### Highest-yield flagged areas (verified against current code)
- **Flag 1 (rights-scan score):** pinned. Impl derives the score deterministically from the registered `reference_fingerprint` alone, band [0.500,1.000] (`services/content.py:73-83`).
- **Flag 2 (manual-claim ownership):** pinned. `RightsHolder` `X-User-ID` must equal `reference_file_id`, else `ERR_FORBIDDEN_ROLE`, checked before existence/range (`routes/claims.py:33-36`).
- **Flag 3 (`POST /channels` under Anonymous):** PRD prose was already consistent with impl (role header must be present-and-declared; any declared role other than the two named roles → 403; no role → 401). No change needed.
- **Flag 4 (`Any` reads / flag 4 + §2.1 `Anonymous`):** revised — `Anonymous` is admitted to every `Any` endpoint, listings *and* single-resource reads (`middleware.py:48-49`).
- **Flag 5 (no `gross_revenue_cents` write path):** pinned — settlement buckets are held in a non-serialised side ledger (`services/revenue.py:21,114`; `routes/serializers.py:26-30`).
- **Flag 6 (`route_batch_id` null on ROUTE):** pinned (`services/payout.py:150` vs `:209`).
- **Flag 7 (error-ID reuse):** pinned — resolutions/counter-notify use `ERR_CONTENT_ITEM_NOT_TAKEN_DOWN`, terminal-claim ops use `ERR_CLAIM_TERMINAL` (`services/claims.py:144,275,284`).
- **Flag 8 (automatic claim release):** **revised** — no implicit sweep on clock advance; claim stays `ACTIVE` (`services/channel.py:159-193`). This was the single largest PRD-vs-impl mismatch.

### Change bullets (`{§} — {op} — {class} — {what} — {impl:line}`)
1. §2.1 — revise — mismatch — `Anonymous` may read the whole public read surface; `Any` admits every declared role incl. `Anonymous` — `middleware.py:40-52`
2. §2.3 — insert — ambiguity — list ordering gets `id`-ascending final tie-break — `routes/common.py:38-39`
3. §2.4 — revise — mismatch — FROZEN gate restated as the six ops precisely (was "four … additionally barred") — posture checks, `routes/*`
4. §2.4 — insert — ambiguity — creation `policy_strike_count` kept only while no strike row exists; recomputed from rows after first issuance — `services/channel.py:70-75,132`
5. §2.6 — revise — mismatch — guard fires on a *supplied* stale value; omission nuance per endpoint — `services/claims.py:96`, `services/payout.py:177-181`
6. §2.6 — revise — mismatch — release/dispute bullets "requires"→"reads"; route omission still 412 — `routes/revenue.py:76-80`
7. §2.6 — insert — ambiguity — lock's/member-payout's `expected_channel_version` accepted but unused — `services/payout.py:140-168`, `routes/payouts.py:71-77`
8. §2.10 — insert — ambiguity — `ERR_UNSUPPORTED_STREAM_TYPE`/`ERR_INVALID_CATEGORY_CODE` precedence over OCC/posture/state — `routes/revenue.py:73`, `routes/content_items.py:139`
9. §2.10 — insert — ambiguity — precise FROZEN gate set; reclassify/settle/manual-claim/ref-register/enrol not gated — see #3
10. §3.2 hops 2-4 — revise — mismatch — non-`OPEN` materialised claim is `ACTIVE`/`lock_reason NONE`, no cascade, `holds_revenue` false — `services/claims.py:66-67,88-90`
11. §3.3 request-review — revise — mismatch — only from `UPLOADED` else `ERR_INVALID_STATE`; body `like_count`/`comment_count`; pass+scan run inline — `routes/content_items.py:82-100`
12. §3.3 — insert — ambiguity — new `AdReview` starts `is_visible` true, `appeal_outcome` `NONE` — `services/content.py:56-57`
13. §3.3 classification-appeal — revise — mismatch — FROZEN also refused, after state/suitability — `routes/content_items.py:108-115`
14. §3.4 — insert — ambiguity — reference-match determinism (flag 1) — `services/content.py:73-83`
15. §3.4 — insert — ambiguity — manual-claim ownership + `claim_level` validation + non-`OPEN` lock — `routes/claims.py:33-51`
16. §3.5 — revise — mismatch — posture gate evaluated before temporal rule (dispute) — `services/claims.py:108-116`
17. §3.5 — revise — mismatch — removed "moves ACTIVE→RELEASED automatically" (flag 8); lapse is admissibility only — `services/channel.py:159-193`
18. §3.5 — insert — ambiguity — counter-notify on non-`TAKEN_DOWN` → `ERR_CONTENT_ITEM_NOT_TAKEN_DOWN`; non-`RELEASE`/other-status resolve → `ERR_INVALID_STATE` — `services/claims.py:142-151,274-275`
19. §3.7 — insert — ambiguity — takedown precedence: terminal claim → `ERR_CLAIM_TERMINAL` before `ERR_INVALID_STATE`; state before posture — `services/claims.py:283-298`
20. §3.8 — revise — mismatch — routing status reads the item's routing rows, not `holds_revenue`; live lock with no parked row still `PAID_CREATOR` — `services/revenue.py:56-61`
21. §3.9 — insert — ambiguity — per-bucket amounts retained internally, never written back or exposed — `services/revenue.py:114`
22. §3.11 lock — insert — ambiguity — `expected_channel_version` accepted but unused (that's "one per change" #7)
23. §3.11 — insert — ambiguity — ROUTE `route_batch_id` null; only PAYOUT names it (flag 6) — `services/payout.py:150,209`
24. §3.11 release — revise — mismatch — "mandatory"→optional version; LOCKED-only (`ERR_INVALID_STATE`); aggregate fields re-assembled; ROUTE v+1 (PAYOUT v1); returns ROUTE — `services/payout.py:175-176,184-224`
25. §3.11/§3.4 route-batch — insert — ambiguity — paginated array; ROUTE/no-predecessor → empty array — `routes/payouts.py:134-146`
26. §3.12 — revise — mismatch — read surface available to any declared role incl. `Anonymous` — `middleware.py:40-52`
27. §4 — revise — mismatch — "every authenticated role"→every declared role; clock advance + member payout run return 200 empty object — `routes/clock.py:27`, `routes/payouts.py:77`

**Step 8 edit subjects checked for coherence:** the four Step-8 paragraphs (retroactive capture non-`OPEN`; resolution revenue-release; routing-status paragraph; §3.12 §3.10→§3.11 xref) all remain coherent. I corrected two dangling subjects they left: §2.4's "frozen channel is additionally barred…" list now states one set of six operations (mismatch #3/#9), and §3.12's cross-reference was pointing at §3.10 for a §3.11 feature (fixed in #26's passage).

**Step 7-modified service files re-checked for unpinned behavior:** `services/content.py` (recompute_item's two-source `holds_revenue`, `classify`, match determinism — pinned), `services/claims.py` (create_claim lock gating, resolve/appeal/counter-notify error IDs — pinned), `services/revenue.py` (routing status reads rows not flags, settlement side ledger — pinned).

**Not changed:** `PRD_FINALIZED.md` untouched; `implementation/`, `test_*`, `SCAFFOLD*.yaml`, `worklog.md` unread/untouched.
