# Worklog — task_3417_long_lifecycle_analog_supply_direct_sales_inventory

## Step 1: Create Task Directory — 2026-10-01T21:49:00.000Z

Task directory pre-allocated by command args; verified `./tasks/task_3417_long_lifecycle_analog_supply_direct_sales_inventory/workspace/` exists. No new index computed, no other task_* directory created.

## Step 2: Generate Scaffold — 2026-10-01T22:50:00.000Z

Scaffold generation complete for `task_3417_long_lifecycle_analog_supply_direct_sales_inventory` — a Texas Instruments-style analog semiconductor direct-sales/supply domain, built purely from the scenario text plus the skill spec (no sibling tasks consulted).

**(a) Output files (all parse as YAML):**
- `/home/ubuntu/github/CodingPRD/tasks/task_3417_long_lifecycle_analog_supply_direct_sales_inventory/SCAFFOLD.yaml` — 1131 lines (§1.0–§1.7 + `domain_constants`; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_3417_long_lifecycle_analog_supply_direct_sales_inventory/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1019 lines (single top key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_3417_long_lifecycle_analog_supply_direct_sales_inventory/SCAFFOLD_CORNER_DESIGN.yaml` — 1700 lines (single top key `scaffold_corner_design`)

**(b) Endpoint count:** 40 (at the cap). 12 entities, 33 error codes, 6 roles, 8 calculations, 2 OCC concurrency rules (pricing publish on `Part.version`, capacity invest on `CapacityPool.version`).

**(c) Design instances:** §1.8 = 18 instances (exactly 2 per rule × 9 rules; all differentiation clauses honored — e.g. dual variants on Part buffer vs DesignWin tail; combinatorial modes (a) waterfall vs (b) per-line rounding; cascades from EOL-create vs run-publish triggers; closed vs half-open overlap semantics; physical-units vs monetary-exposure invariants). §1.9 = 53 instances (44 active + 9 `excluded_because` stubs) across all 9 taxonomy sections.

**(d) Parse confirmation:** all three files `yaml.safe_load` clean; re-parsed after every incremental append.

**(e) Domain vocabulary check passed:** lifecycle/EOL (71 hits), allocation/shortage (39), tier/channel (66), qualification/automotive (46), lifetime-buy/last_order (41), part_number/process/package (15). Forbidden concurrency vocabulary: none. Union of instance names across both design files: 71 unique.

**Lint verdict (verbatim tail):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (392 calls scanned). A separate grounds-resolution audit confirmed all 163 `grounds:` references resolve to declared §1.1–§1.7 elements.

Notable design decisions: every numeric literal in asserts was pre-computed by executing the formulas (e.g. trailing target 1560 vs forward 3510; per-line rounding 5198×2 = 10396 vs sum-round 10395; 80/20/0 waterfall with scores 125/70/40; ramped 200000 vs flat 250000 recognized at one anniversary; EOL dates 2026-09-01/2027-02-28/2027-05-29). All named thresholds are pinned in `domain_constants` and per-calc `constants`. One authoring-time catch: the logical clock is fixed by default, so the allocation tie-break recipe separates the two orders' `created_at` via an explicit clock-set, and the calc documents this.

Orchestrator verification: re-parsed all three files independently; `api_prefix: ""` is a documented inline decision (flat multi-root API, root-relative paths); 40 endpoints confirmed via yaml load; domain grep hits 141.

## Step 3: Copy Shared Files — 2026-10-01T22:51:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-01T23:10:00.000Z

PRD generation is complete and all hard contracts pass.

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_3417_long_lifecycle_analog_supply_direct_sales_inventory/workspace/PRD.md` — **320 lines**, written incrementally in 10 appends (title/§1/§2.1 → §2.2–2.4 → §2.5–2.7 → §2.8–2.10 → §3.1–3.2 → §3.3–3.4 → §3.5–3.6 → §3.7–3.8 → §4 → §5).

**Coverage self-audit (scaffold §1.1–§1.7)**:
- **§1.1 Entities**: all 12 entities rendered in prose with every field name in backticks, including defaults (`automotive_grade` false, `demand_rate_units_per_week` 0, `buffer_multiple` 1.5, `discount_pct` 0, `validity_months` 24), initial values, nullability-while-DRAFT fields, and computed response attributes (`reserved_units`, `posture`, `open_exposure_cents`, `at_risk_design_win_count`, `allocated_units`, `qualified_for_automotive`, `shortage_part_ids`, `awards`, the three `recognized_*_cents` fields, inventory-position and quote output shapes). Mechanical audit: 87 required tokens, 0 missing.
- **§1.2 State machines**: all 26 transitions across 8 machines expressed with from/to states, guards paired to error ids, and full side-effect cascades (EOL announce/rescind → `at_risk` + customer count recompute; submit fork; ship/cancel releases; run publish; qualification↔pool `qualified_for_automotive` cascades; sweep transitions incl. PLANNED→CLOSED jump). Both §1.2.1 OCC rules fully expressed (`expected_part_version` on pricing publish, `expected_capacity_pool_version` on pool investment, `ERR_STALE_VERSION`/412, non-optional, no other endpoint takes a version field).
- **§1.3 Calculations**: all 7 in precise prose — tier quote (inclusive `min_qty`, all-units, channel-invariant, first tier `min_qty` 1), order totals (pinned 5-step order, per-line round-half-up nested rounding, fee 500 when SMALL + DIRECT_ONLINE + subtotal strictly under 10000), buffer position (26-week horizon, 0.5 pipeline weight, thresholds 1.0/0.75 with inclusive lower bounds, zero-target → `NORMAL`, 4-dp coverage), priority score (100/70/40/10 + 25 bonus conditions), waterfall allocation (part_number ASC, score DESC / order `created_at` / line `created_at` / lines-array position, zero-award entries), credit exposure (inclusive boundary), LTB historical price lock (latest `effective_from` ≤ `notice_date`, SUPERSEDED allowed, earliest `created_at` tie-break), revenue tail (4 years, ramped 20/40/25/15 vs flat 25%×4, per-year round-half-up, year 4 absorbs remainder, canonical = ramped iff `automotive_grade`).
- **§1.4 Validations**: all 10 priority rows in §2.8 in priority order with explicit lowest-number-wins precedence and per-row `applies_to` scopes.
- **§1.5 Endpoints**: all 40 in §4's 4-column table; roles mechanically diffed against scaffold — 0 mismatches; status-code rule pins 201 for creations including receipts, 200 otherwise.
- **§1.6 Errors**: all 33 in §5's 2-column table with statuses matching scaffold; every id also mentioned in §2/§3 prose.
- **§1.7 Roles**: all 6 exact spellings; identity semantics per role in §2.1 (five opaque, `Customer` entity-backed with foreign-key ownership comparison).

**Contract reports**: Contract 1 — 87/87 field names, PASS. Contract 2 — 10/10 priorities, 2/2 OCC rules, 26/26 transitions, 7/7 calculations, 33/33 error ids, side effects and sibling branches symmetric, PASS. Contract 3 — 585 §3 backtick tokens, 0 path/method violations, PASS. §2.2 byte-identical to the canonical block, PASS. No pseudocode operators, no fuzzy wording.

**Design-file confirmation**: I did not open, grep, or reference `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml` at any point — only the SKILL.md, its verbatim §2.2 source, the example PRD (style reference), and `SCAFFOLD.yaml`.

Orchestrator spot-check: 320 lines confirmed; header/§1/§2.1 read clean and on-domain; 72 `ERR_` mentions; pinned constants (10000/500/26-week/1.5/0.75) present in prose.

## Step 5: Generate Unit Tests — 2026-10-01T23:55:00.000Z

Generation complete. All quality gates pass.

### (a) File inventory
**test_helpers/** (9 files, ~1130 lines): `types.py` (266) — 12 entity TypedDicts + 13 status/role enums; `api_client.py` (152) — one method per each of the 40 PRD §4 endpoints, subclassing `GenericApiClient`; `api_errors.py` (80) — all 34 error ids with PRD §5 HTTP map, registered via `set_error_http_status_map`; `assertions.py` (169) — per-entity structural assertions honoring nullable computed fields; `factories.py` (157); `constants.py` (37 after pruning) — only live date literals, each derived from the PRD clock; `test_users.py` (29) — 5 opaque-role header constants + `make_customer_headers(customer_id)` builder (entity-backed Customer role, no shared constant); `fixtures.py` (278) — composite builders (`make_stocked_priced_part`, `make_ltb_ready_part`, `make_active_design_win`, `qualify_site`, `make_allocation_run`, etc.), all built from PRD endpoints via `get_success_data`; `__init__.py` barrel.

**test_suite/** (19 files, ~2500 lines): `conftest.py` (45) + 18 test files (78–228 lines each) holding 80 test functions.

### (b) AST tag audit (real `ast` parse, not grep)
- §1.8 Difficulty: 18 instances, all non-stub → **36 tests emitted (exactly 2 per instance), 0 shortfalls**
- §1.9 Corner: 53 instances total = 44 non-stub + 9 `excluded_because` stubs → **44 tests emitted (exactly 1 per non-stub), 0 shortfalls**; stubs correctly not translated (all 9 cross-references resolve to real difficulty instances)
- **Skipped by PRD-first filter: 0** — every instance's asserted outcome is verbatim-PRD-covered and uniquely derivable. Notable adjudications: absolute `version == 1` assertions from recipes were replaced by relative `+1` checks (PRD pins only the increment); `subtotal_cents null while DRAFT` was dropped (PRD pins only `submitted_at`/line-price nullity); within-line partial auto-award ambiguity was resolved to the all-or-nothing reading (the only PRD-grounded one); a REGISTERED win's `at_risk` under EOL was avoided as non-derivable.
- 0 unknown tags, 0 dual/untagged tests.

### (c) pytest --collect-only
`80 tests collected in 0.23s`, zero import errors (PYTHONPATH = task dir).

### (d) Constants & clock fidelity
Every constant in `constants.py` is referenced by code and was grep-verified against its PRD pinning sentence (fee 500/10000 threshold, 180/90-day windows, ×52 LTB floor, 26-week horizon, 1.5 buffer default, 0.5 pipeline weight, 1.0/0.75 posture bounds, 100/70/40/10 tier weights, +25 bonus, 4-year tail, 24-month default validity, clock `2026-09-01T00:00:00Z`). Unreferenced constants were deleted rather than left as dead drift vectors. All fixture dates derive from the PRD's declared clock: canonical EOL window (2026-09-01 / 2027-02-28 / 2027-05-29 = notice+180d / +90d) and pool windows are anchored at the default clock; the 179-day and boundary-touch fixtures re-derive from those anchors. Creation endpoints assert `validate_success(..., 201)` everywhere; docstring citations: 128 PRD quotes verified verbatim against `workspace/PRD.md` (0 failures). No servers started, no pytest execution beyond collection.

Orchestrator verification: independent `pytest --collect-only` → 80 tests, 0 errors; 62 unique `Design:` tags = 18 difficulty instances + 44 corner instances ✓; helper file inventory matches.

## Step 6: Generate Implementation — 2026-10-02T00:35:00.000Z

All verification passes. The implementation is complete.

### (a) File inventory — `workspace/implementation/` (2,384 lines total)

| Lines | File | Role |
|---|---|---|
| 68 | `constants.py` | every PRD-pinned constant, defined once |
| 48 | `errors.py` | `ApiError` + all 33 catalog error ids |
| 39 | `timeutil.py` | ISO8601 parse/format (3 fractional digits), year arithmetic |
| 54 | `store.py` | in-memory dicts + logical clock + seq; blank on boot |
| 72 | `envelope.py` | success/error envelopes, pagination (limit/offset/total_count/has_more) |
| 114 | `validate.py` | schema checks (unknown fields, types, enums, tiers) |
| 29 | `auth.py` | X-User-ID / X-User-Role auth + role/ownership gates |
| 67 | `lookups.py` | entity-specific 404s |
| 253 | `derive.py` | all derived fields + the 8 calculations |
| 186 | `serialize.py` | per-entity public representations |
| 37 | `sweep.py` | clock sweep (part EOL chain, notice completion, win completion) |
| 185/90/92/260/87/114/99/141/89/158/31 | `routes_{parts,customers,pricing,orders,capacity,allocation,eol,ltb,qual,designs,clock}.py` | all 40 endpoints |
| 60 | `app.py` | bootstrap, blueprint registration, error handlers |
| 10 | `start.sh` | guarded install + `exec python3 app.py` on `$PORT`/`0.0.0.0` |
| 1 | `requirements.txt` | `flask>=2.2,<4` |

### (b) Compile/import
`py_compile` OK on all 22 modules; `python3 -c "import app"` succeeds and the URL map lists all 40 PRD endpoint rules.

### (c) Constants cross-check
All 28 `C.*` names referenced in code are defined in `constants.py` with exact PRD values (fee 500, subtotal 10000, horizon 26, buffer 1.5, weight 0.5, thresholds 1.0/0.75, tier weights 100/70/40/10, bonus 25, tail 4, validity 24, EOL 180/90 days, clock 2026-09-01T00:00:00Z, LTB 52 weeks). No referenced-but-undefined constant.

### (d) Live-check sweep
All 33 PRD error ids have a reachable raise site (verified by grep against every route module): the 11 entity 404s via `lookups.py`, auth 401/403 via `auth.py`, `ERR_INVALID_REQUEST` via `validate.py`, and each business error (`ERR_STALE_VERSION`, `ERR_DUPLICATE_PART_NUMBER`, `ERR_POOL_PERIOD_OVERLAP`, `ERR_EOL_NOTICE_ACTIVE_EXISTS`, `ERR_QUALIFICATION_OVERLAP`, `ERR_EOL_WINDOW_INVALID`, `ERR_LAST_ORDER_DATE_PASSED`, `ERR_POOL_NOT_OPEN`, `ERR_SITE_NOT_QUALIFIED`, `ERR_PART_NOT_ORDERABLE`, `ERR_NO_PUBLISHED_PRICING`, `ERR_EOL_NOTICE_NOT_ACTIVE`, `ERR_NOTICE_PART_MISMATCH`, `ERR_REFERENCE_DESIGN_NOT_PUBLISHED`, `ERR_LTB_QUANTITY_BELOW_MIN`, `ERR_INSUFFICIENT_INVENTORY`, `ERR_POOL_CAPACITY_EXCEEDED`, `ERR_CREDIT_LIMIT_EXCEEDED`, `ERR_INVALID_STATE`) raised on its request path.

### (e) Self-smoke-test transcript
Fresh `start.sh` boot on dynamic port 43571; 55 assertions ALL PASS covering every module: auth 401/403, part CRUD + duplicate-409, schedule publish + OCC 412, quote tier boundary (qty 100 → tier min_qty 100), pool OPEN/overlap-409/adjacency-allowed, receipts, inventory position (target_trailing 1560, coverage 0.0641, SHORTAGE), order submit → BACKORDERED with locked prices (subtotal 2000), second-submit 409, allocation run (award 10, score 100, shortage_part_ids) → publish → ALLOCATED, ship (on_hand 90, reserved 0), qualification workflow + illegal-transition 409, reference design publish, design win activate, forward target 3510 (canonical fixture values reproduced), EOL notice → part EOL_ANNOUNCED + at_risk cascade + customer count 1, window-invalid 422, LTB min/inventory 422s, LTB success with historical tier price (150 × 500 = 75000), clock set → sweep to LAST_TIME_BUY, revenue recognition (ramped 200000 / flat 250000 / canonical 250000 at 1 year), last-order-passed 422, LTB cancel, all list endpoints with pagination meta, 404 and unknown-field 400. Server killed by exact listener PID (3119193); port confirmed free. No other pipeline processes touched.

### (f) Interpretation choices (Step 8/9 candidates)
1. `reserved_units` includes **BACKORDERED** order lines (PRD §3.4 "still holds its reservations" overrides the scaffold field text naming only ALLOCATED).
2. Derived fields computed at read (reserved, posture, exposure, at_risk, pool status, qualified_for_automotive, recognized_*); sweep mutates only stored states.
3. `at_risk` derives from part lifecycle for **all** win statuses; `at_risk_design_win_count` counts only ACTIVE wins.
4. Submit with zero lines → `ERR_INVALID_STATE` (409); no error id pinned in PRD.
5. EOL-notice creation on a DISCONTINUED part → `ERR_INVALID_STATE`; on EOL_ANNOUNCED/LAST_TIME_BUY with non-overlapping window → allowed (keeps `ERR_EOL_NOTICE_ACTIVE_EXISTS` reachable, since a LAST_TIME_BUY part still holds an ANNOUNCED notice).
6. LTB row-9 order: pricing-existence → notice-ANNOUNCED → part-match (validation-row written order, not §3.7 narrative order); row-8 clock check first.
7. Design-win activate: part-orderable checked before ref-design-published (row written order).
8. OCC check placed after schema, before business rules.
9. Pool PATCH allows lowering `total_units` down to `allocated_units` (error catalog pins only the below-allocated case).
10. Submit auto-award evaluates lines sequentially, counting same-request pending reservations.
11. Allocation publish applies frozen entries blindly (0-award entries are stamped; only BACKORDERED orders flip).
12. `coverage_trailing` is `null` when target_trailing_units == 0 (posture NORMAL).
13. `current_utc` echoes the client's `to_iso8601` verbatim; system timestamps always emit 3 fractional digits.
14. Pagination clamps out-of-range limit/offset; non-integer → 400; filter params never 404.
15. Reference-design creation does not require the featured part to exist (string match, not id reference); publish enforces with `ERR_PART_NOT_ORDERABLE` 422.
16. Design-win registration has no status gates (existence only); activation carries the gates.
17. Version bumps only on stored-field mutations (keeps the two OCC guards consistent with their descriptions).
18. Schema ranges not pinned by PRD enforced as: discount_pct ∈ [0,1], buffer_multiple ≥ 0, demand_rate ≥ 0, validity_months ≥ 1, tier price ≥ 0.
19. Action endpoints reject unknown body fields when a body is supplied (row 4 applies to all POST/PATCH).
20. Customer-role list endpoints force-scope to the caller's own customer_id (conflicting filter → empty page, not 403).

Isolation rule honored: only SKILL.md, INSTRUCTION.md, SCAFFOLD.yaml, PRD.md were read; no test-suite files opened, no tests run.

Orchestrator verification: independent `py_compile` of all 22 modules OK; start.sh reads `$PORT` via app.py with guarded flask install; 2,373 source lines on disk.

## Step 7: Run Tests and Iterate — 2026-10-02T00:55:00.000Z

Clean sweep: all 8 parallel rounds pass 80/80 with the evidence files preserved.

**Summary**

- **Iterations run:** 2 (initial sweep: 78/80 in all 8 rounds, same 2 failures everywhere — deterministic, not flaky; post-fix sweep: 80/80 in all 8 rounds).

- **Tests deleted:** none.

- **Fixes applied to `test_suite/`** (both in `/home/ubuntu/github/CodingPRD/tasks/task_3417_long_lifecycle_analog_supply_direct_sales_inventory/test_suite/test_16_lifetime_buy_rejections.py`):
  - `test_ltb_against_rescinded_notice_rejected` — added `publish_price(part["id"])` before notice creation.
  - `test_ltb_notice_part_mismatch_rejected` — added `publish_price(part_b["id"])` for the requested part.
  - **Why (STEP 2, test-was-wrong):** both tests' setups left *two* row-9 checks failing simultaneously — no pricing schedule effective by the notice date (`ERR_NO_PUBLISHED_PRICING`) plus the asserted notice-status/part-match check. PRD §2.8 pins the collision explicitly: "Within a single priority row, the row's listed checks evaluate in the order written", and row 9's written order places published-pricing *before* the LTB notice checks. So PRD uniquely determines `ERR_NO_PUBLISHED_PRICING` wins — the opposite of the assertions. The asserted rules themselves are PRD-verbatim (§3.7: "The referenced notice must be `ANNOUNCED`, else `ERR_EOL_NOTICE_NOT_ACTIVE`… the notice's part must be the requested `part_id`, else `ERR_NOTICE_PART_MISMATCH`"), so per STEP 1c/2 the fixtures were repaired (publish pricing effective 2026-08-01, before the 2026-09-01 notice date) so the asserted check becomes the unique highest-priority failure. Assertions unchanged.

- **Fixes applied to `test_helpers/`:** none (fixture helpers were already PRD-consistent; the bug was in the test bodies' setup composition).

- **Fixes applied to `implementation/`:** none. The implementation's LTB check order (pricing → notice-ANNOUNCED → part-match, clock check first) is the faithful reading of PRD §2.8 row 9's written order — worklog interpretation #6 confirmed correct.

- **Sibling unasserted paths (per constraint E):** the two tests previously exercised the pricing-vs-notice precedence collision implicitly and got it wrong; after the fix, the precedence outcome "both pricing and notice checks fail → `ERR_NO_PUBLISHED_PRICING`" is no longer asserted anywhere. The implementation enforces it per §2.8 row-9 written order (pinned, not silent), but no test now covers that collision — a candidate for the next pipeline step to cover explicitly.

Orchestrator verification: all 8 `results.${i}.json` on disk with passed=80/total=80 each; no `.py` file under implementation/, test_suite/, or test_helpers/ is newer than the final sweep (mtime check clean, __pycache__ excluded).

## Step 8: Finalize PRD — 2026-10-02T01:05:00.000Z

Done. PRD_FINALIZED.md is a byte-identical copy of PRD.md — the zero-edit outcome, verified rather than assumed.

**Line counts / delta:** PRD.md 320 lines, PRD_FINALIZED.md 320 lines, 0% delta. `diff -q` reports the files identical (no output).

**Changes:** Zero. This is the explicitly-permitted zero-edit outcome, and the evidence supports it:

- The `<step_7_diff>` contains only two pure test-fixture repairs in `test_suite/test_16_lifetime_buy_rejections.py` (adding `publish_price(...)` to setups; assertions unchanged), no implementation fixes, no test deletions, no test_helpers fixes. There is no impl-pinned-but-PRD-silent behavior for Step 8 to trace.
- The collision the fixtures were repaired around (no pricing effective by notice date + notice-status/part-match failure → `ERR_NO_PUBLISHED_PRICING` wins) is uniquely pinned by PRD.md already:
  - §2.8 line 118: "Within a single priority row, the row's listed checks evaluate in the order written."
  - §2.8 row 9 (line 128) lists `ERR_NO_PUBLISHED_PRICING` before `ERR_EOL_NOTICE_NOT_ACTIVE`/`ERR_NOTICE_PART_MISMATCH`, and its closing sentence explicitly names lifetime-buy placement among the guarded operations.
  - §3.7 (line 221): "If no schedule was effective by the notice date, creation fails with `ERR_NO_PUBLISHED_PRICING`"; line 219 pins the notice ANNOUNCED and part-match checks.
- Impl check sites read and matching: `routes_ltb.py:57-83` (row 8 clock check first; row 9 in written order: pricing → notice-ANNOUNCED → part-match; row 10: min-qty → inventory → credit), `derive.py:180-190` (`ltb_price_schedule` implements §3.7's historical lock, any-status candidates, latest `effective_from`, tie-break to earliest created).

**Per-edit pre-edit search log:** No edits were committed, so there are no per-edit (a)/(b)/(c) entries. The global enumeration justifying the zero-edit outcome: subject = LTB-creation error precedence between the pricing check and the notice checks; paths enumerated = `create_lifetime_buy` in `implementation/routes_ltb.py` (the only LTB creation path), `derive.ltb_price_schedule` in `derive.py` (the only LTB pricing-selection helper), and a grep of all three error ids across `implementation/*.py`, which surfaced the only other `ERR_NO_PUBLISHED_PRICING` raise sites — `routes_orders.py:147` (order submission, pinned by §3.4 line 179) and `routes_pricing.py:83` (quoting, pinned by §3.3 line 173). Every related path is already uniquely determined by existing PRD wording, so any edit would have risked manufacturing a new mismatch rather than repairing a silence.

**Output file:** `workspace/PRD_FINALIZED.md`

Orchestrator verification: independent `diff -q PRD.md PRD_FINALIZED.md` → identical; both 320 lines.

## Step 9: Complete PRD — 2026-10-02T01:35:00.000Z

The file is complete — tail intact, diff confirms exactly the intended changes landed.

**Source vs. output:** `PRD_FINALIZED.md` (320 lines, 57,790 chars) → `PRD_COMPLETED.md` (320 lines, 60,748 chars; +2,958 chars). All changes are in-paragraph inserts/revisions; no sections added, no lines deleted. Diff verified: 20 line-level changes, document tail intact.

**Counts:** 18 ambiguity-pins, 2 mismatch-revisions.

### Ambiguity pins

- §2.2 — insert — ambiguity — `api_request_timestamp` reads the logical clock, never wall clock — `envelope.py:12-16`
- §2.3 — insert — ambiguity — out-of-range `limit` clamped to [1,100] and negative `offset` clamped to 0 (not rejected); non-integer values fail with `ERR_INVALID_REQUEST` 400 — `envelope.py:43-67`
- §2.3 — insert — ambiguity — `created_at` ties break by creation order; filter params match on exact equality and unmatched values yield an empty page, not an error — list handlers sort by `seq` (e.g. `routes_orders.py:109`)
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — `store.py:44`
- §2.4 — insert — ambiguity — a validating-but-no-op PATCH still refreshes `updated_at` and increments `version` — `routes_parts.py:124`, `routes_customers.py:89`
- §2.5 — revise — ambiguity — clock set returns the accepted `to_iso8601` string verbatim as `current_utc` (echo, not reformat) — `routes_clock.py:31`
- §2.7 — insert — ambiguity — stale-version check precedence: immediately after request-schema validation (row 4), before rows 5–10 — `routes_pricing.py:45-50`, `routes_capacity.py:70-75`
- §2.8 row 4 — insert — ambiguity — numeric bounds: `demand_rate_units_per_week`/`credit_limit_cents`/`expected_lifetime_revenue_cents`/`annual_volume_units` integers ≥ 0; `buffer_multiple` number ≥ 0; `discount_pct` number in [0,1]; `validity_months` integer ≥ 1 — `routes_parts.py:62-68`, `routes_customers.py:27-31`, `routes_qual.py:45`, `routes_designs.py:98-99`
- §2.8 row 4 — insert — ambiguity — action endpoints accept no request fields; any supplied body field is an unknown-field 400 — e.g. `routes_orders.py:203`, `routes_allocation.py:90`
- §3.1 — insert — ambiguity — `coverage_trailing` serializes as null when the trailing target is zero (unbounded) — `derive.py:76-77`
- §3.3 — insert — ambiguity — schedule list ties on `effective_from` keep creation order — `routes_parts.py:143`
- §3.4 — insert — ambiguity — DRAFT order exposes `subtotal_cents`/`total_cents` null and `service_fee_cents` 0 — `routes_orders.py:72-74`
- §3.4 — insert — ambiguity — submitting an order with no lines → `ERR_INVALID_STATE` 409 — `routes_orders.py:126-127`
- §3.4 — insert — ambiguity — same-part lines within one submission: earlier lines' auto-awards count against later lines' posture and availability evaluation, in array order — `routes_orders.py:177-185`
- §3.4 — insert — ambiguity — shipping is gated solely on order status `ALLOCATED`; part lifecycle and notice dates do not block it — `routes_orders.py:214-215`
- §3.6 — insert — ambiguity — cross-order allocation ties (identical `created_at` at both levels) break by earlier-created order — `routes_allocation.py:44`
- §3.6 — revise — ambiguity — publish applies every frozen award entry, including zero-award entries, stamping their `allocation_run_id`/`rank`/`priority_score` — `routes_allocation.py:94-102`
- §3.7 — insert — ambiguity — issuing a notice on an `EOL_ANNOUNCED`/`LAST_TIME_BUY` part leaves lifecycle unchanged; on a `DISCONTINUED` part → `ERR_INVALID_STATE` 409 — `routes_eol.py:46-47,77-79`
- §3.7 — insert — ambiguity — with multiple disjoint `ANNOUNCED` notices, the sweep and last-order-date gate read the earliest `last_order_date`, ties by creation order — `derive.py:244-253`
- §5 — insert — ambiguity — unmatched routes/methods yield `ERR_NOT_FOUND` 404 / `ERR_METHOD_NOT_ALLOWED` 405 outside the workflow catalog — `app.py:41-47`

### Mismatch revisions (with guardrail justification)

- §3.5 — revise — mismatch — "Investment can only raise installed capacity" → investment may set `total_units` to any value not below `allocated_units`, including lowering toward it. Justification: the same sentence's operative rule (floor at `allocated_units` with named error `ERR_POOL_CAPACITY_EXCEEDED`) is exactly what impl enforces (`routes_capacity.py:77-78` rejects only `total_units < allocated_units`); "can only raise" names no error and contradicts its own floor clause; no test exercises rejection of a lower-but-above-floor value. The floor is the deliberate contract; the "raise" phrasing was loose narrative.
- §3.7 — revise — mismatch — "a `last_ship_date` after which nothing ships" → "at which the clock sweep retires the part". Justification: §3.4 already pins the shipping gate exhaustively ("only from `ALLOCATED`"), the error catalog contains no ship-date violation id, and no test exercises a ship gate; impl ships any `ALLOCATED` order regardless of dates (`routes_orders.py:214`). The date's enforceable consequence (sweep → `DISCONTINUED` + notice → `COMPLETED`) is already pinned in the same paragraph, so the phrase was program description, not a gate. Companion §3.4 pin above removes residual ambiguity.

### Impl-omission candidates (PRD kept, impl diverges)

None. Every other PRD rule traced cleanly to impl: validation precedence (rows 1–10, including row-6-before-8-before-10 on receipts and the row-9 written order on LTB/activation), existence-before-schema ordering, derived-field semantics (`reserved_units`, posture, exposure, at-risk), rounding and tier rules, OCC mechanics, cascade side effects, and all 31 endpoint role assignments.

Orchestrator adjudication of the 2 mismatch revisions against SCAFFOLD.yaml (orchestrator-side check, subagents remain scaffold-blind):
1. §3.5 "can only raise": scaffold L874 endpoint description says "raise total_units (never below allocated_units)" but the scaffold error catalog (L1072) defines ERR_POOL_CAPACITY_EXCEEDED only for "PATCH would set total_units below allocated_units" — no error pathway exists for lowering-above-floor, so the original PRD sentence was not uniquely implementable as written (no named rejection). Revision aligns PRD with the enforceable contract; ACCEPTED, no impl fix.
2. §3.7 "nothing ships after last_ship_date": scaffold ship gate (L679 row 5) is order-state-only; ERR_LAST_ORDER_DATE_PASSED applies to submit/LTB only (L682, L1062); the last_ship_date's sole scaffold consequence is the LAST_TIME_BUY→DISCONTINUED sweep (L252). No ship-date violation error exists anywhere in the 33-error catalog. Revision is correct; ACCEPTED, no impl fix.

Orchestrator verification: `diff -q PRD_FINALIZED.md PRD_COMPLETED.md` → differ (exit 1, changes landed); 320 lines both, 57,790 → 60,748 chars (+2,958, matches claim exactly); document tail intact (§5 error table closes the file).
