# Worklog — task_3372_teacher_classroom_project_funding_vendor_fulfillment_donor

## Step 1: Create Task Directory — 2026-10-01T09:48:00.000Z

Task directory was pre-allocated by the caller: `./tasks/task_3372_teacher_classroom_project_funding_vendor_fulfillment_donor/` with `workspace/` inside. Verified existence; no new index computed, no other task_* directory created.

## Step 2: Generate Scaffold — 2026-10-01T11:38:03.282Z

(Resumed after host-session interruption; first Step 2 subagent died mid-flight leaving zero files — rerun from scratch.)

All three artifacts are written, parse as YAML, and pass `scaffold_lint.py` clean.

**Lint verdict (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
  §1.5 endpoints declared:    41
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     38
  Calls scanned (§1.8+§1.9):  773
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files:**
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single `scaffold_difficulty_design:` key
- `SCAFFOLD_CORNER_DESIGN.yaml` — single `scaffold_corner_design:` key

**Counts:**
- Entities: 13 (School, Teacher, Vendor, CatalogItem, Project, ProjectItem, Donor, Donation, MatchCampaign, PurchaseOrder, ThankYouPackage, FraudCase, EquityFund)
- State machines: 8 (Project cyclic revision loop; Donation branching fork; Teacher suspension cycle; PO lifecycle; MatchCampaign/EquityFund auto-exhaust/reopen cycles; FraudCase fork; ThankYouPackage)
- Calculations: 12 (incl. dual-variant project quote provisional-vs-pinned, dual-variant school equity banded-vs-weighted, nested min/max/clamp shipping quote, per-donation-then-sum match rounding, two compensating invariants)
- Validations: 27 (priority 0–26, spanning auth/existence/OCC/state/safety/temporal/constraint/referential/fiscal)
- Endpoints: 41 (2 test-driving `/_clock`, `/_sweeps` + 39 business; one over the round 40 — the extra is `GET /giving/donors/{id}`, required by donor-aggregate asserts in three recipes; every endpoint is load-bearing)
- Errors: 27, all referenced by at least one validation and exercised by at least one recipe
- Roles: 6 (Anonymous, Teacher, Donor — entity-backed; Reviewer, PlatformAdmin — opaque; Vendor — entity-backed), segregation-of-duties between SCREEN and VET reviewers
- Concurrency: 3 OCC rules (project item-add, project submit, donation reallocation), all lint-verified `${var}`-driven

**Difficulty design:** 18 instances, exactly 2 per rule across all 9 rule_ids; names unique; all fixture arithmetic pre-computed in code (e.g., goal 10959 = 10000 + 959 shipping; match rounding 51+51=102 vs forbidden 101; equity inversion 83.0 weighted vs 100 banded; shipping cap 4999 from raw 323129).

**Corner design:** 49 instances total — 38 active across all nine taxonomy sections + 11 `excluded_because:` stubs, all resolving to real difficulty instances.

Notable design choices for the "harder than expert" directive: density over volume — clock-driven two-phase expiry sweep with inclusive boundaries, donor reallocation OCC with clawback chains, fraud-confirm cascade of depth 4 (case → teacher → project → donations → match budget), half-open vs closed interval overlap semantics on two different resources, and a ranking inversion fixture that proves which equity-score variant the selector uses. No sibling task directories were read at any point.

**Orchestrator verification (files on disk):** SCAFFOLD.yaml 1464 lines / 77323 bytes; SCAFFOLD_DIFFICULTY_DESIGN.yaml 1327 lines / 66686 bytes; SCAFFOLD_CORNER_DESIGN.yaml 1669 lines / 78520 bytes. All three parse as YAML; SCAFFOLD.yaml top-level keys = scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules (no design keys); 41 endpoint entries confirmed; tails complete (no truncation).

## Step 3: Copy Shared Files — 2026-10-01T11:38:38.405Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (53 lines / 1424 bytes).

## Step 4: Generate PRD — 2026-10-01T11:55:51.561Z

All three hard contracts pass. The PRD is complete.

**Output**: `workspace/PRD.md` — 315 lines (subagent count; on-disk wc = 314 lines / 51064 bytes).

**Sections**:
- §1 Introduction (2 paragraphs)
- §2 Global Specifications (2.1 Roles/RBAC with per-role identity prose, 2.2 Response Structure emitted verbatim from `section-2.2-response-structure.md`, 2.3 Pagination, 2.4 Logical Clock & Expiration Sweep, 2.5 Common Resource Properties incl. the ThankYouPackage `common_fields: false` exception, 2.6 Money/Precision/Rounding, 2.7 OCC, 2.8 Validation Order & Nested Retrieval with the full 27-rule priority ladder, 2.9 Conservation Invariants)
- §3 Business Logic (9 subsections: registry layer, vendor catalog & shipping economics, project composition/submit, screening/vetting, donations/matching/funding, expiration/choice/reallocation, fulfillment/thank-you gate, fraud clawback, match campaigns & equity programs)
- §4 Endpoint Definitions (4-column table, all 41 endpoints defined in the scaffold — the scaffold header comment says "39" but 41 endpoint entries are actually present; all 41 are in the table)
- §5 Error Code Catalogue (2-column table, all 27 errors)

**Coverage attestation** (verified mechanically against SCAFFOLD.yaml):
- Contract 1 field coverage: 99 required identifiers (all `entities[].fields[].name`, all endpoint `input`/`query_params`, all path params) — 99 present, 0 missing. PASS
- Contract 2 rule coverage: all 8 state machines (every transition's preconditions, error_ids, and side effects in prose); all 12 calculations with constants, boundaries, and rounding (shipping tiers 32/128 oz, 299/599/899 bases, zone rates 120/180/260, 350 fragile flat, 199/4999 clamp; banded score 90/75/50 thresholds; weighted 0.7/0.3 half-up to 1 decimal; per-donation match rounding pinned with the 101-cent example; inclusive funding boundary; sweep's 4-phase order with process orderings and equality boundaries; fraud clawback's 5-step order); all 3 OCC rules with endpoint + `expected_*_version` + `ERR_STALE_VERSION`/412; all 27 validations with priority ordering expressed as an explicit ladder (incl. `ERR_NO_ITEMS` before `ERR_GOAL_OUT_OF_RANGE`, not-verified before suspended); all endpoint `applies_to` scopes enumerated in narrative. PASS
- Contract 3 §3 path purity: 537 backticked tokens scanned, 0 path/method violations. PASS
- All 27 `errors[].id` strings appear in §2/§3 prose; all state/enum values verified present as backticked UPPERCASE strings (one gap found and fixed: `SCREEN`).
- The two withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, and no sibling task directories were consulted.

**Orchestrator verification (file on disk):** PRD.md 314 lines / 51064 bytes; head shows proper title + §1 intro; tail shows complete §5 error table ending `ERR_NO_ELIGIBLE_PROJECT` (no truncation).

## Step 5: Generate Unit Tests — 2026-10-01T12:35:28.584Z

All checks pass. Generation complete — final state verified.

**Task:** `task_3372_teacher_classroom_project_funding_vendor_fulfillment_donor`

### Coverage
- **Queue A (difficulty):** 18/18 instances covered, **36 tests** (exactly 2 per instance — audit confirmed `difficulty tag counts: [2]×18`).
- **Queue B (corner):** 38/38 non-stub instances covered, **38 tests** (exactly 1 each). 11 `excluded_because:` stubs not translated; all 11 cross-references resolve to real difficulty instances.
- **Total collected: 74 tests, 0 collection errors** (`pytest --collect-only` clean).
- **Skipped instances: none.** Every non-stub instance passed the PRD-first two-condition filter.

### Adjudication notes (PRD-first filter applied)
- In `rejected_project_is_terminal_for_submit`, the design's sub-assertion `vetted_by_id == "rev-ben"` was **omitted**: PRD §3.4 attributes `vetted_by_id` recording only to vetting `APPROVE`, so it is not uniquely derivable for `REJECT`. The terminal-state claim itself (fresh OCC + `ERR_INVALID_STATE`) is fully covered and kept.
- In `test_full_revision_cycle_terminates_in_funding` I corrected my own draft assertion: attribution clears at **resubmit**, not at VET `RETURN` (PRD §3.3), so the test now asserts `screened_by_id == "rev-ana"` after the return and `None` after resubmission.
- Clock arithmetic re-derived from PRD §2.4's clock start (`2026-09-01T00:00:00Z`): deadline `2026-10-01` (+30d), choice deadline `2026-10-15` (+14d sweep), both inclusive boundaries exercised.
- Timestamp comparisons use a `canonical_instant` normalizer so `...T00:00:00Z` and `...T00:00:00.000Z` compare equal (PRD renders 3 fractional digits).
- All PRD docstring citations pass a verbatim whitespace-normalized `grep` of PRD.md (audit: 0 missing). No `skip`/`xfail` markers, no scaffold references in generated code.

### `test_helpers/` file list
- `test_helpers/__init__.py` — barrel export (framework + PRD-specific)
- `test_helpers/types.py` — 13 status enums + 13 entity TypedDicts (ThankYouPackage omits `updated_at`/`version`)
- `test_helpers/api_client.py` — `ApiClient(GenericApiClient)`, all 39 endpoints + `canonical_instant`
- `test_helpers/api_errors.py` — 27 `ApiErrorId` values + HTTP map registered with the framework
- `test_helpers/assertions.py` — per-entity assertions, `assert_instant`/`assert_cents`/`assert_one_dp`, donor + campaign conservation checkers
- `test_helpers/factories.py` — payload factories with auto-unique emails; named item specs (book/lab/pencil/rug/centrifuge)
- `test_helpers/constants.py` — goal range, shipping tiers/zones/clamp, equity weights/bands, fixture geometry (goal 10959), clock instants
- `test_helpers/test_users.py` — opaque headers (admin/anonymous/rev-ana/rev-ben) + entity-backed builders `make_teacher_headers`/`make_donor_headers`/`make_vendor_headers`
- `test_helpers/fixtures.py` — 5 tiers: clock/sweep/creators → canonical world → lifecycle walks (`setup_draft_project`, `setup_funding_project`, `setup_funded_project`, `setup_two_vendor_funded_project`, `setup_fulfilled_project`) → `setup_expired_project` (clock driven to the project's own `funding_deadline` + sweep) → fraud/suspension worlds

### `test_suite/` (16 files)
`conftest.py` + `test_01..test_09_difficulty_*.py` (9 files, 36 tests, one per rule) + `test_10_corner_entities.py` (6), `test_11_corner_state_machines.py` (5), `test_12_corner_calculations.py` (3), `test_13_corner_validation_gates.py` (9), `test_14_corner_validation_windows.py` (9), `test_15_corner_api_surface.py` (6). No server was started; tests were collection-validated only.

**Orchestrator verification (files on disk):** all 9 test_helpers + 16 test_suite files present; independent `pytest --collect-only` = **74 tests collected, 0 errors**; 56 unique `Design:` tags (18 difficulty + 38 corner — consistent with 2 tests per difficulty instance sharing a tag); 0 test files lacking a `Design:` tag.

## Step 6: Generate Implementation — 2026-10-01T13:07:53.274Z

Implementation complete. Summary:

## Files created (workspace/implementation/, 2363 lines total)

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 10 | Foreground launcher, `exec python3 app.py`, guarded pip install, `$PORT`/0.0.0.0 |
| `requirements.txt` | 1 | flask only |
| `app.py` | 43 | Flask entry, error handlers, route registration |
| `store.py` | 71 | In-memory dicts (13 entity tables), logical clock (default 2026-09-01T00:00:00Z), base_record/touch with OCC version |
| `errors.py` | 41 | ApiError + catalog helpers |
| `envelope.py` | 59 | `meta`/`response_type`/`data` envelope, error body, pagination meta |
| `security.py` | 26 | X-User-ID/X-User-Role auth, six roles |
| `validators.py` | 103 | Priority-0 body validation, pagination parsing |
| `serializers.py` | 213 | Per-entity serializers (ThankYouPackage: no `updated_at`/`version`) |
| `util_time.py` | 35 | ISO-8601 3-fractional-digit output, second-precision parsing |
| `services/pricing.py` | 110 | po_shipping_quote (tier/ceil-pounds/zone-max/fragile/clamp), provisional quote, equity scores (banded + weighted round-half-up) |
| `services/matching.py` | 44 | Per-donation round-half-up match, budget clawback, EXHAUSTED↔ACTIVE |
| `services/funding.py` | 106 | Derived funded_cents, FUNDED tip (inclusive boundary), PO issuance (line_items sorted by catalog-item created_at), thank-you gate |
| `services/sweeps.py` | 94 | 4-phase expiration sweep in pinned order |
| `services/fraud.py` | 52 | CONFIRMED cascade: suspend → cancel pipeline (created_at ASC) → refund + clawback → cancel ISSUED/SHIPPED POs |
| `routes/` | 1151 | 11 modules: clock, schools, teachers, vendors, projects, donors, campaigns, orders, fraud, equity |

## Endpoints
**41/41** implemented (the scaffold's §1.5 comment says "39" but actually lists 41; all present, verified via Flask url_map), including `POST /_clock/set_current_utc` and `POST /_sweeps/expiration_run`.

## Smoke test
Server booted via `bash start.sh` on a chosen port (PID saved, killed exactly). Verified: empty-list envelope, 404 `ERR_NOT_FOUND`, 401 `ERR_UNAUTHENTICATED`, plus a full happy path (school → teacher verify → vendor/item → project → item → submit (goal 15419 = items 15000 + shipping 419 ✓) → SCREEN/VET → donations tipping at exact equality → FUNDED, PO ISSUED with correct snapshot, PENDING package, post-goal donation → 409). A second boot confirmed completely fresh state. Test suite was not run (per isolation rule); SCAFFOLD_DIFFICULTY_DESIGN / CORNER_DESIGN / test_suite / test_helpers were not read.

## PRD ambiguities resolved
1. **created_at/updated_at use wall-clock; business timestamps use the logical clock.** PRD marks only funding_started_at/issued_at/shipped_at/delivered_at/submitted_at/choice_deadline as "logical-clock"; created_at needs distinct values for the "created_at ASC, id never used" equity tie-break.
2. **Validation ladder**: priority-0 body checks precede auth (401), per scaffold priorities 0<1 and PRD §2.8. Path-id existence is checked before ownership (ownership is unevaluable otherwise); ownership precedes body-FK existence (priority 2 < 3).
3. **Nonexistent `catalog_item_id` on item add → 422 ERR_CATALOG_ITEM_UNAVAILABLE** (PRD §3.3 "must exist … otherwise ERR_CATALOG_ITEM_UNAVAILABLE" overrides generic 404).
4. **REALLOCATE `equity_fund_id`**: absent → 422 ERR_INVALID_REALLOCATION_TARGET; present-but-unknown → 404 (it's a body-referenced FK per §2.8 existence rule).
5. **RETURN transitions clear the pinned face** (items' pinned_unit_price_cents → null, project pinned totals/goal → null) per "pinned … null while project IN {DRAFT, RETURNED}"; screened_by_id/vetted_by_id cleared at resubmit only (PRD pins that to resubmission).
6. **Donation `matched_cents` zeroed at clawback** so derived funded_cents matches "refund moves only principal; match left at expiry".
7. **Duplicate teacher/donor email and duplicate SKU → 400 ERR_INVALID_REQUEST** (no catalogued error exists for these).
8. **SCREEN+REJECT → 400** (enum-combination invalid); **DISCONTINUED→ACTIVE PATCH → 409 ERR_INVALID_STATE**; same-status PATCH is a no-op.
9. **Vendor suspend and catalog PATCH on suspended vendor**: suspend is idempotent 200; item-create on a suspended vendor → 409 ERR_INVALID_STATE ("blocks adding new catalog items").
10. **Pagination out-of-range values clamp** (limit to [1,100], offset to ≥0) rather than 400 — "minimum of 1 and maximum of 100" read as bounds, and ERR_INVALID_REQUEST's catalog condition doesn't list pagination.
11. **PO creation order for multi-vendor projects**: vendors ordered by their earliest catalog-item created_at (spec pins line order within a PO only).
12. **Version starts at 1**; every mutation (including sweep transitions and cascades) bumps version + refreshes updated_at, matching the §2.7 stale-observation scenarios.
13. **Donation/donor GETs**: `GET /donations/{id}` has no "(self)" annotation in PRD §4 → no ownership restriction; `GET /donors/{donor_id}` is annotated "Donor (self)" → enforced.

**Orchestrator verification (files on disk):** implementation/ tree complete (app.py, store.py, errors.py, envelope.py, security.py, validators.py, serializers.py, util_time.py, services/ 5 modules, routes/ 11 modules, start.sh executable, requirements.txt); every .py parses via `ast`; 41 route decorators counted — matches 41 scaffold endpoints.

## Step 7: Run Tests and Iterate — 2026-10-01T13:16:44.335Z

Clean 8-round parallel sweep achieved. Summary:

**Iterations run:** 2 (initial sweep + verification sweep after one fix)

**Tests deleted:** None.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `test_suite/`:** None.

**Fixes applied to `implementation/`:**
- `workspace/implementation/store.py`, `new_id()` — changed `uuid.uuid4().hex` (32-char hex, no dashes) to `str(uuid.uuid4())` (canonical dashed UUID). PRD §2.5 states verbatim: "`id` — a server-minted UUID with no type prefix." The canonical string form of a UUID is the dashed 8-4-4-4-12 form; "no type prefix" rules out only `school_`-style prefixes, not dashes. Both failing tests (`test_school_create_computes_both_equity_score_variants`, `test_catalog_item_defaults_fragile_false_and_cap_null` in `test_10_corner_entities.py`) tripped the shared `assert_has_common_fields` UUID check; the tests were faithful to the PRD, and the single fix healed both since `new_id()` is the sole ID-minting site for all 13 entity tables.

**Failure profile:** Deterministic, not flaky — identical 2 failures in all 8 initial rounds; zero flakiness observed across 16 total round-runs.

**Final sweep evidence (passed/total per round):**
- Round 1: 74/74
- Round 2: 74/74
- Round 3: 74/74
- Round 4: 74/74
- Round 5: 74/74
- Round 6: 74/74
- Round 7: 74/74
- Round 8: 74/74

All 8 `results.{1..8}.json` files remain in place in `workspace/implementation/` as required output artifacts.

**Orchestrator verification (files on disk):** all 8 `results.{1..8}.json` present (mtime 13:16), each independently parsed: passed=74, total=74, failed=0.

## Step 8: Finalize PRD — 2026-10-01T13:20:24.762Z

(Not skipped: Step 7 had 1 `implementation/` fix.)

Done. `PRD_FINALIZED.md` produced at `workspace/PRD_FINALIZED.md`.

**Line counts / delta:** PRD.md 314 lines, PRD_FINALIZED.md 314 lines — 0% line-count delta; exactly one line modified in place (verified via `diff`: single-line change at line 98).

**Changes (one edit, tracing to the single Step 7 fix):**
- §2.5 Common Resource Properties — revise — appended ", rendered in the canonical dashed 8-4-4-4-12 string form (e.g., `550e8400-e29b-41d4-a716-446655440000`)" to the `id` bullet — `implementation/store.py:34-35` (`new_id()` returns `str(uuid.uuid4())`).

**Rationale:** The PRD prose "a server-minted UUID with no type prefix" demonstrably did not uniquely determine the wire format — the original implementer chose `uuid.uuid4().hex` (dashless 32-char), and Step 7 had to flip the implementation to the dashed canonical form. Since `id` strings appear in every response body, the dash-vs-no-dash choice is externally observable behavior; the minimal clause pins it without touching anything else.

**Per-edit pre-edit search log (NO-NEW-MISMATCH RULE):**
- (a) Subject: the wire format of every server-minted `id` field across all 13 entity tables.
- (b) Impl paths enumerated and read/grepped:
  - `implementation/store.py` (read in full): `new_id()` at lines 34-35 is the sole ID-minting site; it feeds exactly two record factories — `base_record()` (lines 50-60, all 12 standard resources) and `bare_record()` (lines 63-65, ThankYouPackage, matching §2.5's own exception note which still carries `id`).
  - Repo-wide grep for `uuid.`/`UUID(`/`re.compile`/`re.match` across `implementation/**/*.py`: the only `uuid` usage in the entire codebase is `store.py:35`. No inbound-ID format validation exists anywhere — all consumers (path params, FK fields like `school_id`/`donor_id`/`project_id`/`match_campaign_id`/`equity_fund_id`, query-string filters in `routes/donors.py`, sweeps, matching service) treat IDs as opaque strings via dict `.get()`/equality, so the new wording cannot contradict any lookup or cascade path.
  - §2.5's exception sentence ("ThankYouPackage … carries only `id` and `created_at`") confirms the revised bullet still applies to that resource, and `bare_record()` confirms the impl matches.
- (c) Wording adjustment: kept the original clause "with no type prefix" verbatim and only appended the format clause; deliberately did not pin a UUID version (e.g., v4) since that is not observable behavior the PRD needs to constrain — looser wording preferred per the rule. No enumerated path is mis-described.

**Note:** `test_helpers/` and `test_suite/` are not present under `workspace/` (only `INSTRUCTION.md`, `PRD.md`, `PRD_FINALIZED.md`, `implementation/`), consistent with Step 7 reporting zero test/test-helper changes; the implementation was treated as the sole alignment target.

**Orchestrator verification (files on disk):** PRD_FINALIZED.md 314 lines / 51168 bytes; `diff PRD.md PRD_FINALIZED.md` shows exactly the single claimed line-98 change; 0 `implementation/*.py`/`*.sh` files modified after the 13:16 clean sweep — sweep evidence remains valid.

## Step 9: Complete PRD — 2026-10-01T13:50:59.670Z

All edits are applied and verified. PRD_COMPLETED.md is complete at `workspace/PRD_COMPLETED.md`.

## Summary

**Source vs output:** PRD_FINALIZED.md 314 lines / 51,168 chars → PRD_COMPLETED.md 315 lines / 56,373 chars (+1 line, +5,205 chars). 34 edit sites total.

**Counts:** 26 ambiguity-pins, 8 mismatch-revisions.

### Changes (section — insert/revise — ambiguity/mismatch — what — impl ref)

- §2.3 — revise — ambiguity — limit clamped to [1,100], offset clamped to ≥0, non-integer → 400 — validators.py:89-103
- §2.4 — insert — ambiguity — clock setter accepts any parseable instant (no monotonic guard), unparseable → 400, echo at whole-second precision — clock.py:14-24, util_time.py:16-35
- §2.4 — insert — ambiguity — sweep phase 1 processes donations per project in created_at ASC; phases 3/4 process in created_at ASC — sweeps.py:41,71,82
- §2.5 — revise — ambiguity — created_at/updated_at are wall-clock; logical clock governs only business timestamps; version starts at 1 — store.py:50-71
- §2.7 — revise — mismatch — non-OCC endpoints ignore a supplied version field (not "do not accept") — all routes (json_body ignores unknown keys)
- §2.8 rung 1 — insert — ambiguity — extended well-formedness enumeration (JSON-object body, non-empty strings, unit_price/weight_oz/budget mins, min_donation ≥0, max_quantity ≥1, min_poverty range, parseable timestamps, SHIP tracking_number, REJECT-only-VET) — validators.py, orders.py:54-57, projects.py:277-278
- §2.8 rungs 3-5 — revise — **mismatch** — old ladder put ownership before existence; impl does role-permission → path existence (left-to-right, nested belong-to) → ownership → body-FK; actor backing entity (Teacher on create, Donor on donate) → 404; catalog_item_id and equity_fund_id explicitly deferred — e.g. projects.py:157-176, vendors.py:146-151, donors.py:64-74
- §2.8 rung 7 — insert — ambiguity — vendor must be ACTIVE to accept new catalog items; campaign/fund ACTIVE clause scoped to donation/allocation (reallocation target lives at rung 12) — vendors.py:92-93
- §2.8 rung 11 — insert — ambiguity — duplicate teacher/donor email and duplicate SKU → ERR_INVALID_REQUEST (400) — teachers.py:42-43, donors.py:29-30, vendors.py:94-98
- §2.8 rung 12 — revise — mismatch — nonexistent catalog item folds into 422; REALLOCATE absent→422 / unknown→404 / invalid→422 split — projects.py:176-178, donors.py:196-207
- §3.1 — revise — **mismatch** — state_code validated only as non-empty string, format not enforced — schools.py:16
- §3.1 — insert — ambiguity — teacher email dup → 400; school_id unknown → 404; REINSTATE from other states → 409 — teachers.py:40-43, 93-94
- §3.1 — insert — ambiguity — vendor suspend idempotent 200 no-op; item-add on suspended vendor → 409 ERR_INVALID_STATE — vendors.py:64-67, 92-93
- §3.2 — insert — ambiguity — duplicate SKU → 400; max_quantity_per_project ≥1 when supplied — vendors.py:86,94-98
- §3.2 — insert — ambiguity — DISCONTINUED→ACTIVE PATCH → 409; same-status/no-change PATCH is a 200 no-op with no version bump — vendors.py:153-163
- §3.3 — revise — mismatch — nonexistent catalog_item_id on item add → 422 ERR_CATALOG_ITEM_UNAVAILABLE, not 404 — projects.py:176-178
- §3.4 — insert — ambiguity — RETURN at either stage nulls pinned totals/goal/item prices, keeps screened_by_id/vetted_by_id (cleared only at resubmit) — projects.py:53-62, 264-266
- §3.4 — insert — ambiguity — SCREEN+REJECT → 400 ERR_INVALID_REQUEST (well-formedness, before auth) — projects.py:277-278
- §3.5 — insert — ambiguity — donor email dup → 400; donation reads/list carry no ownership restriction — donors.py:29-30, 133-162
- §3.6 — insert — ambiguity — clawback resets donation's matched_cents to 0 — matching.py:44
- §3.6 — revise — **mismatch** — REALLOCATE: absent fund id → 422, unknown id → 404, inactive/out-of-window → 422; DEPLETED flip-back cannot occur — donors.py:196-216
- §3.7 — insert — ambiguity — multi-vendor PO issuance ordered by each vendor's earliest catalog-item created_at — funding.py:30-35
- §3.8 — revise — ambiguity — diversion reason optional, null when absent — orders.py:122
- §3.8 step 4 — insert — ambiguity — fraud clawback resets donation matched_cents to 0 — fraud.py:36, matching.py:44
- §3.9 — insert — ambiguity — campaign target_value stored verbatim, no existence/enum validation — campaigns.py:32
- §3.9 — revise — mismatch — fund state_code validated only as non-empty string — equity.py:26
- §3.9 — insert — ambiguity — allocate responds 200 with the grant donation (action endpoint) — equity.py:144
- §3.9 — revise — **mismatch** — DEPLETED fund never returns to ACTIVE (target must be ACTIVE) — donors.py:203 vs 211-216
- §4 — insert — ambiguity — allocation 200 carve-out from the create→201 rule — equity.py:144
- §5 — insert — ambiguity — transport-level outcomes: unknown path → ERR_NOT_FOUND 404; unsupported method → ERR_NOT_FOUND w/ 405; unexpected failure → ERR_INTERNAL 500 — app.py:24-36

### Checklist verdicts

1. Wall-clock created_at/updated_at vs logical business timestamps — **newly-pinned** (§2.5)
2. Priority-0 body before 401; path-existence → ownership → body-FK — **newly-pinned** via ladder rewrite (old ladder was a mismatch: it ordered ownership before existence)
3. Nonexistent catalog_item_id → 422 — **newly-pinned** (§3.3 + rung 12)
4. REALLOCATE absent→422 / unknown→404 — **mismatch-found** and revised (§3.6; old text lumped "missing fund id" under 422 and was silent on unknown ids)
5. RETURN clears pinned face; reviewer ids cleared at resubmit only — **newly-pinned** (§3.4; §3.3 resubmit clause was already correct)
6. matched_cents zeroed at clawback — **newly-pinned** (§3.6, §3.8)
7. Duplicate email/SKU → 400 — **newly-pinned** (§3.1/§3.5/§3.2 + rung 11)
8. SCREEN+REJECT → 400; DISCONTINUED→ACTIVE → 409; same-status PATCH no-op — **newly-pinned** (§3.4, §3.2)
9. Vendor suspend idempotent 200; item-create on suspended vendor → 409 — **newly-pinned** (§3.1)
10. Pagination clamping — **newly-pinned** (§2.3)
11. PO creation order (earliest catalog-item created_at) — **newly-pinned** (§3.7)
12. Version starts at 1; mutations bump version + refresh updated_at — start-at-1 **newly-pinned**; bump-on-mutation **already-pinned**
13. GET /donations/{id} no ownership restriction — **newly-pinned** (§3.5); GET /donors/{id} self-enforcement — **already-pinned** (§4 table)
14. Dead-check audit — every helper in implementation/ has a live callsite. **Loud flag:** the DEPLETED→ACTIVE flip-back branch in `reallocation_choice` (donors.py:211-216) is unreachable because the ACTIVE gate (donors.py:203) rejects DEPLETED targets first — PRD §3.6/§3.9 claimed this resurrection happens; both passages revised to state DEPLETED persists until the sweep closes the fund. Also, PRD's "two-letter uppercase state_code" implied format validation impl never performs (schools.py:16, equity.py:26) — revised to impl.

No files other than PRD_COMPLETED.md were modified.

**Orchestrator verification (files on disk):** PRD_COMPLETED.md 315 lines / 56373 bytes (char delta +5205 matches claim exactly: 51168+5205=56373); `diff -q` confirms it differs from PRD_FINALIZED.md; 0 implementation source files and 0 test source files modified after the 13:16 clean sweep — sweep evidence remains valid; all 8 `results.{1..8}.json` still present.

## PIPELINE COMPLETE — 2026-10-01T13:50:59.670Z

All 9 steps done. Final state: 74/74 tests passing across all 8 parallel sweep rounds; zero test deletions; zero test/helper fixes; one implementation fix (UUID wire format); PRD_FINALIZED.md (1-line patch) and PRD_COMPLETED.md (34-site completeness patch) produced.
