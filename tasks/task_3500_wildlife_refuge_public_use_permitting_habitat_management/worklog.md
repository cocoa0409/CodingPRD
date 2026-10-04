# Worklog — task_3500_wildlife_refuge_public_use_permitting_habitat_management

## Step 1: Create task directory — 2026-10-02T19:45:00.000Z

Used pre-allocated directory `tasks/task_3500_wildlife_refuge_public_use_permitting_habitat_management/` (already created with `workspace/` inside per command args; no new index computed). Difficulty instruction: "Generate task much harder than expert level!" (applies to scaffold generation only).

## Step 2: Generate scaffold — 2026-10-02T20:41:00.000Z

All three artifacts are complete, parse cleanly, and pass the linter with zero violations.

### Summary

**Files (all parse-verified with `yaml.safe_load`):**
- `/home/ubuntu/github/CodingPRD/tasks/task_3500_wildlife_refuge_public_use_permitting_habitat_management/SCAFFOLD.yaml` — parse OK (§1.0–§1.7 only; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_3500_wildlife_refuge_public_use_permitting_habitat_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — parse OK (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_3500_wildlife_refuge_public_use_permitting_habitat_management/SCAFFOLD_CORNER_DESIGN.yaml` — parse OK (single key `scaffold_corner_design`)

**Counts:** 52 endpoints · 14 entities · 24 errors · 24 prioritized validations · 12 state machines · 8 calculations · 2 OCC concurrency rules · 10 roles · §1.8: 18 non-stub instances (9 rules × 2) · §1.9: 66 non-stub instances + 18 excluded_because stubs (84 total)

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (749 calls scanned, 0 violations.) Additional audits passed: instance names unique across both design files (102), every `grounds` reference resolves, every error code is cited by a validation, every stub cites a real §1.8 instance, no forbidden concurrency vocabulary, endpoint roles ⊆ RBAC.

**Design shape (harder-than-expert via coupling density, not volume):** compliance_audit × temporal_windowing archetype; hybrid topology with a polymorphic Citation subject; hierarchical-override RBAC over 6 staff + 3 public roles. Highlights: dual-variant fees (provisional flat vs tiered/surcharged/clamped) and dual-variant habitat scoring (breeding-weighted vs annual); pinned round-per-period-then-sum cost-share (3004 vs the wrong 3003); cyclic permit revision loop and citation-driven ACTIVE⇄SUSPENDED agreement cycle; depth-3 volunteer-expiry→assignment→program cascade vs depth-2 citation→points→suspension cascade; closure-activation cascade with scope-conditional permit suspension; pinned clock-evaluation order (5 auto-transition classes) with default clock 2026-09-01T00:00:00Z; three distinct interval semantics (14-day nesting buffer, half-open treatment windows, aggregate daily commercial capacity); two OCC rules on CooperativeAgreement that pass the serial-observability filter; fully pinned bid selector (eligibility → rank_score → created_at tie-break → EXPIRED fallback).

One judgment call to flag: 52 endpoints exceeds the Expert band (20–32) — deliberate given the "much harder than expert" instruction; coverage was prioritized over count-trimming (each of the 8 scenario bullets has live surface). No sibling task directories were inspected.

**Orchestrator verification:** all three files exist on disk, parse with yaml.safe_load; `api_prefix: "/refuge"`, `domain_name: "wildlife-refuge-permitting"`, 319 refuge/wildlife/habitat/permit hits in SCAFFOLD.yaml (authentic domain, no foreign contamination). Sizes: SCAFFOLD.yaml 1916 lines, DIFFICULTY 1156 lines, CORNER 2778 lines.

## Step 3: Copy shared files — 2026-10-02T21:01:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T21:20:00.000Z

PRD generation complete and verified. The document is written end-to-end at `/home/ubuntu/github/CodingPRD/tasks/task_3500_wildlife_refuge_public_use_permitting_habitat_management/workspace/PRD.md`.

**File metrics:** 364 lines / 67,785 bytes. The line count is below the 900+ guideline only because paragraphs are unwrapped single lines (~186 bytes/line); density calibration confirms completeness — the reference example PRD is 33KB for a 29-endpoint scaffold, while this one is 67.8KB for a 52-endpoint scaffold (2.0x the bytes for 1.8x the endpoints). Tail-read verification: the file terminates correctly at the final `ERR_OVERPAYMENT` row of §5.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC (all 10 roles named, identity translation per role incl. entity-backed `Volunteer` and the `applicant_ref`/`cooperator_ref` ownership anchors), 2.2 API Response Structure (verified byte-identical to canonical source), 2.3 Pagination, 2.4 Common Resource Properties + two timestamp families, 2.5 Logical Clock (startup `2026-09-01T00:00:00Z`, pinned 5-class auto-transition order), 2.6 Validation Order (all 24 priorities in first-failure-wins prose), 2.7 Nested Retrieval, 2.8 Money/Rounding (round-half-up sites, cap-then-floor, pinned 1502/3004 example), 2.9 OCC (both rules: `expected_agreement_version` + `ERR_STALE_VERSION`/412 on assess and agreement-subject citations), 2.10 Cascades, 2.11 Seasonal Safety (posture derivation, 14-day nesting buffer, half-open windows)
- §3 Business Logic (9 subsections: units/snapshot, determinations/comments, permits, treatments, closures, programs/volunteers/assignments, grazing, agreements/citations, population objectives)
- §4 Endpoint Definitions — 52/52 rows, 4 columns, clock endpoint correctly unprefixed
- §5 Error Code Catalogue — 24/24 rows, 2 columns

**Hard Contract Reports:**
- Contract 1 (Field-Name Coverage): 83 required (entities + request bodies + query params + path params + `current_utc`/`active_closure_count`), 83 present, 0 missing after one repair (`offering_id` added). PASS
- Contract 2 (Rule Coverage): all 36 state transitions' from/to pairs in prose; all 24 validations paired with error IDs in §2.6 order; all 8 calculations with formulas/constants/boundaries (breeding window, tier multipliers, 60-point suspend boundary incl. "exactly 60 stays ACTIVE", 365-day expiry boundary, population 7/10 integer comparison, bid rank score with `created_at` tie-break and empty-pool `EXPIRED` fallback); both OCC rules fully expressed; all cascade hops (closure activate/lift, volunteer expiry, program cancel/complete) with version/`updated_at` semantics; sibling branches symmetric. PASS
- Contract 3 (§3 Path Purity): 531 backtick tokens scanned, 0 path/method/combo violations. PASS

One adjudicated scaffold ambiguity to note for downstream steps: the commercial-capacity rule text is permissive about which permits count ("permits in {APPROVED, ACTIVE}") while the error catalog says "COMMERCIAL_FILMING permits"; the PRD follows the catalog + constant name (`MAX_COMMERCIAL_PERMITS_PER_UNIT_DAY`), i.e., only commercial-filming permits count toward the 2-per-day cap. Also, the grazing-offering create has no `determination_id` input — the PRD expresses the FINAL+COMPATIBLE GRAZING gate as keyed on the refuge's determination covering the `GRAZING` use type, consistent with the scaffold's unit-less determination schema.

**Orchestrator verification:** workspace/PRD.md exists (364 lines / 67,785 bytes), tail terminates at the §5 error catalogue (`ERR_OVERPAYMENT`), 111 refuge/permit/habitat hits (domain-authentic).

**Carried forward to Step 7 prompt:** (1) commercial capacity counts COMMERCIAL_FILMING permits only; (2) grazing-offering create gates on the refuge's FINAL+COMPATIBLE determination for use_type GRAZING (no determination_id input).

## Step 5a: Generate test helpers (Stage 1, frozen) — 2026-10-02T21:50:00.000Z

Stage 1 complete. All nine helper files are written, import cleanly, and pass a formula-level smoke check against the PRD's pinned literals.

### Files written (all under `test_helpers/`)

| File | Lines | Contents |
|---|---|---|
| `__init__.py` | 29 | Barrel: framework generics + all PRD-specific exports |
| `types.py` | 400 | 24 enums (incl. separate `DeterminationUseType` with GRAZING vs `PermitUseType` without) + 15 TypedDicts (all entities carry id/created_at/updated_at/version) |
| `api_client.py` | 244 | `ApiClient(GenericApiClient)` with 52 endpoint methods; `api_client` singleton |
| `api_errors.py` | 66 | `ApiErrorId` (24 ids) + `HTTP_STATUS_CODES` + `set_error_http_status_map` at import |
| `assertions.py` | 233 | 16 `assert_{entity}` fns + `assert_common_fields`, `assert_iso_date` (YYYY-MM-DD family), `assert_agreement_balance_invariants`, `assert_citation_points_match_severity` |
| `factories.py` | 279 | 22 payload factories, input fields only |
| `constants.py` | 279 | Constant families + 14 pure formula helpers |
| `test_users.py` | 70 | `TEST_USERS` (9 entries) + 3 per-instance builders |
| `fixtures.py` | 768 | 55 exported fixture functions, defs ≡ `__all__` exactly |

### Smoke-check output (verbatim)

```
ApiClient public methods: 56
constants formulas: OK
test_users: OK
factories: OK
api_errors: OK (24 ids)
assertions invariants: OK
barrel export: OK
SMOKE CHECK PASSED
```
Plus `py_compile` on all files OK; zero "scaffold"/"§1.x" references in comments; zero `uuid4().hex` occurrences (all minted refs use `str(uuid4())` dashed form); endpoint methods = 56 − 4 inherited convenience (`get/post/put/delete`) = 52, matching the PRD endpoint table exactly.

### Constant families defined (all re-derived from PRD prose)
- **Clock**: `CLOCK_START_ISO = "2026-09-01T00:00:00Z"`, plus standard fixture dates (comment window 09-05→09-20, post-close 09-21; permit 10-10→10-12; closure 10-09→10-20; program 2026-12-01; treatment 10-01→10-10; grazing window 2026-11-01→2027-02-28, deadline 2026-10-01)
- **Permit fees**: `BASE_FEE_CENTS`, `PER_DAY_CENTS` (per use_type), `TIER_SMALL/MEDIUM/LARGE` (1.0/1.25/1.5), tier bounds 9/19, `COMMERCIAL_SURCHARGE_CENTS=10000`, `FEE_FLOOR_CENTS=5000`, `FEE_CAP_CENTS=100000`
- **Capacity**: `MAX_COMMERCIAL_PERMITS_PER_UNIT_DAY=2` (COMMERCIAL_FILMING only, {APPROVED, ACTIVE} — adjudication #1 encoded)
- **Cost share**: `COOP_SHARE_PCT=50` (round-half-up per period, then sum)
- **Compliance**: `INITIAL_COMPLIANCE_POINTS=100`, `SUSPEND_THRESHOLD_POINTS=60` (exactly 60 stays ACTIVE), `POINTS_BY_SEVERITY` 10/25/50
- **Safety/seasonal**: `NESTING_BUFFER_DAYS=14`, `VOLUNTEER_CLEARANCE_VALID_DAYS=365` (boundary day expires)
- **Habitat**: weights 30/50/20, `BREEDING_MULTIPLIER=2`, breeding window Mar 1–Jun 30 of window_start's year
- **Bids**: `RATING_WEIGHT=1000`, stewardship 1–10; **Population**: 7/10 integer ratio; **Pagination**: 10/1/100/0
- **Pure helpers**: `round_half_up_cents`, `parse_date/format_date/add_days/clock_iso`, `trip_days` (inclusive), `compute_tier_multiplier`, `compute_provisional_fee_cents`, `compute_assessed_fee_cents` (verified: 21000, 52500, 36250 vs 37500, floor 5000, cap 100000, 17000 vs 17500), `compute_period_assessment_cents` (1502, 167), `compute_bid_rank_score`, `is_at_target` (700 ✓ / 699 ✗ on target 1000), `breeding_window_dates`, `window_intersects_breeding`

### Role/identity model in test_users.py
- 6 opaque staff roles + PermitApplicant + Cooperator as shared constants (the anchored two marked "fallback for non-ownership tests only")
- `make_permit_applicant_headers(applicant_ref)`, `make_cooperator_headers(cooperator_ref)` — X-User-ID must equal the ref
- `make_volunteer_headers(volunteer_id)` — entity-backed; **no shared Volunteer constant exists** (every Volunteer-role call is self-scoped, so a placeholder id would be a trap)
- `ANONYMOUS_HEADERS` omits X-User-ID entirely (PRD §2.1)

### Interface notes for Stage 2
- **Clock endpoint is UNPREFIXED**: `api_client.set_clock(payload, headers)` → `POST /_clock/set_current_utc` (all other methods carry `/refuge`).
- **Clock only moves forward**; fixtures never rewind. `create_final_determination()` leaves the clock at 2026-09-21 by default — tests needing a `cleared_on` earlier than that must clear volunteers BEFORE finalizing determinations, or pass later window dates. Fixture families needing relative dates: volunteer expiry boundary (cleared_on = clock date at clear time; expiry at +365 inclusive), bid tie-break (advance clock between two bids), closure-lift reinstate-vs-expire (end_date vs clock date).
- **Trickiest factory/fixture signatures**:
    - Permits: `create_permit_payload(management_unit_id, determination_id, **overrides)` — `applicant_ref` auto-mints a dashed UUID; fixtures thread it into `make_permit_applicant_headers`. Chain fixtures: `create_submitted_permit → create_under_review_permit (return+resubmit) → create_approved_permit (assessed fee set) → create_active_permit (pays exact assessed_fee_cents)`.
    - Agreements: **no create endpoint** — only `setup_awarded_agreement(bids=[("coop-1", 2000, 7)], min_stewardship_rating=5, **offering_overrides)` → dict with `{unit, determination, offering, bids, winning_bid, agreement}`. Winner is discovered by scanning post-close bids for WINNING (tie-break safe). Grazing gate per adjudication #2: fixture creates a FINAL COMPATIBLE GRAZING determination; offering payload takes no determination_id.
    - Citations: `create_citation_payload(subject_permit_id=...|subject_agreement_id=..., expected_agreement_version=...)` — raises ValueError on zero/two subjects or a missing OCC version on agreement subjects. `issue_agreement_citation(agreement, severity=...)` reads `agreement["version"]` (must be fresh); `issue_permit_citation(permit_id)` sends no OCC field.
    - Closures: `create_closure → activate_closure / lift_closure`; `setup_closure_cascade_scenario(closure_scope=...)` pre-builds the unit + ACTIVE permit + program + assignment + SCHEDULED closure stage shared by 3 corner instances.
    - Bids: `place_bid(offering_id, cooperator_ref=None, rate_cents_per_aum=2000, stewardship_rating=7)`.
- No by-id GET exists for treatments/programs — `get_treatment(unit_id, id)` / `get_program(unit_id, id)` scan the unit listing (`limit=100`).
- `assess_period`/`issue_agreement_citation`/`post_payment`/`post_refund` return the mutated agreement; each mutation bumps version by 1 (initial version is 1), so refresh via `refresh_agreement` before the next OCC call.
- Success statuses: creates 201 (fixtures pin it via `get_success_data(resp, 201)`); all actions/reads 200. Stage 2 must pass 201 explicitly to `validate_success` on create paths.

**Orchestrator verification:** all 9 helper files present; `import test_helpers` + all submodules import OK (55 fixtures exported); ApiClient has 56 public methods (52 endpoints + 4 inherited); 0 `uuid4().hex`; 0 scaffold references in helpers. Design queues measured by orchestrator from YAML: §1.8 = 18 non-stub, §1.9 = 66 non-stub (84 total).

## Step 5b: Generate test suite (Stage 2, against frozen helpers) — 2026-10-02T22:10:00.000Z

Stage 2 complete. All audits green.

### Summary

**Output**: `test_suite/` — conftest.py + 11 test files, 84 tests total.

**Per-file test counts** (queue split A=Difficulty / B=Corner):
- `test_01_units_envelope_reads.py` — 12 (0A + 12B: entities 8, endpoints 4)
- `test_02_calculations.py` — 7 (3A + 4B: fee tiers/floor/cap, population 70% threshold)
- `test_03_permit_lifecycle.py` — 11 (4A + 7B: revision cycle, priority pair, approve gates, commercial capacity, consistency)
- `test_04_determinations_comments.py` — 6 (1A + 5B)
- `test_05_treatments.py` — 8 (3A + 5B: breeding-vs-annual, blackout buffer, overlap, posture)
- `test_06_closures_cascades.py` — 6 (1A + 5B: suspend/reinstate conservation, scope-conditional cascades, lift non-restoration)
- `test_07_volunteers_programs.py` — 6 (2A + 4B: depth-3 expiry cascade, 365-day boundary)
- `test_08_grazing_bids.py` — 6 (0A + 6B: duplicate bid, deadline, tie-break, eligibility filter, empty-pool expiry)
- `test_09_agreements_ledger.py` — 7 (2A + 5B: round-per-period 3004, pay/refund conservation, suspend blocks assess not payment)
- `test_10_citations_occ.py` — 5 (2A + 3B: citation-driven cycle, depth-2 suspend, OCC 412 on assess and citation)
- `test_11_rbac_auth.py` — 10 (0A + 10B: role denials, manager override, ownership anchors, auth-beats-404)

**Skips: none.** All 84 non-stub instances passed the PRD-first filter — this PRD carries the validation-cascade numbering, OCC field names, boundary inclusivity, and pinned arithmetic examples in prose. The 18 `excluded_because` corner stubs were not translated (verified their `difficulty_instance` pointers all resolve).

**Interpretations applied (PRD-derivable, noted for downstream):**
- `permit_revision_cycle_runs_twice`: the index pins `version == 6`, but PRD §2.4 only pins "increments by one on every modification" without pinning the initial value — the test asserts `version == version_at_create + 5` instead of the literal 6.
- Endpoint quirks honored: creates validated with explicit 201; clock calls only via `advance_clock` (unprefixed endpoint handled inside helpers); ownership-anchored calls thread `make_*_headers(ref)`; volunteer expiry setups avoid `create_final_determination` clock interference; `setup_closure_cascade_scenario` reused for the three closure-cascade tests.

**Mandatory audit results (verbatim):**
- `pytest --collect-only -q test_suite/`: **"84 tests collected in 0.34s"**, zero collection errors.
- AST tag audit (real `yaml.safe_load` of both indices vs docstring `Design:` tags):
  ```
  expected non-stub instances: 84 (18 difficulty + 66 corner; 18 corner stubs excluded)
  emitted unique tags: 84; test functions: 84
  malformed tag counts: []
  duplicate tags: {}
  MISSING: []
  EXTRA: []
  AUDIT: PASS
  ```
- PRD-citation verbatim pass: 116 quoted sentences across all docstrings, all survive whitespace-normalized literal match against `workspace/PRD.md` (20 boundary/markdown-bold mismatches found and fixed before final pass).
- No `skip`/`skipif`/`xfail` markers anywhere.

**Orchestrator verification:** re-ran `pytest --collect-only -q test_suite/` myself → "84 tests collected in 0.23s", zero errors; 84 `Design:` tags across 11 test files + conftest.py.

## Step 6: Generate implementation — 2026-10-02T22:45:00.000Z

All complete. Final state verified: 21 files, `start.sh` executable, no stray server processes, resource IDs all dashed UUIDs (the one grep hit is a comment; the `api_request_id` uses hex only for the `req_` envelope id, not resources).

### Summary

**Deliverable**: complete Python + Flask implementation at `workspace/implementation/`

#### Files (2,122 lines total)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 9 | Foreground launcher, `exec python3 app.py`, `$PORT`/`0.0.0.0`, guarded pip install |
| `requirements.txt` | 1 | flask only |
| `app.py` | 64 | App factory, blueprint registration, ApiError/404/405/500 envelope handlers |
| `store.py` | 92 | Empty-boot in-memory store, logical clock (starts exactly `2026-09-01T00:00:00Z`), `mutate` (one version bump per mutation, only on actual change) |
| `envelope.py` | 79 | Envelope (`meta`/`response_type`/`data`), 24-error catalog with exact HTTP codes |
| `util.py` | 146 | Shape validators, date parsing, pagination (limit 1-100 default 10, offset 0) |
| `auth.py` | 56 | `X-User-Role`/`X-User-ID` auth (401/403), endpoint decorator |
| `calc.py` | 184 | All 8 calculations: fee tiers (cap-then-floor), per-period-then-sum cost share (1502+1502=3004 pinned), habitat breeding/annual scores, posture, visitor days, bid ranking, population threshold |
| `engine.py` | 158 | Clock advance with the 5 pinned transition classes in order; closure activate/lift cascades; volunteer expiry cascade; close-and-select award |
| `units.py` | 66 | 3 endpoints |
| `determinations.py` | 158 | 7 endpoints (incl. comments) |
| `permits.py` | 221 | 8 endpoints |
| `treatments.py` | 117 | 4 endpoints (nesting blackout, half-open overlap) |
| `closures.py` | 87 | 4 endpoints |
| `programs.py` | 184 | 7 endpoints (programs + volunteers + assignments) |
| `grazing.py` | 158 | 6 endpoints |
| `agreements.py` | 132 | 5 endpoints (OCC assess, ledger, complete) |
| `citations.py` | 123 | 4 endpoints (OCC on agreement subjects) |
| `population.py` | 65 | 3 endpoints |
| `clockctl.py` | 22 | `POST /_clock/set_current_utc` — unprefixed, outside `/refuge` |

#### Self-smoke-test transcript
Two boots on dynamic ports (53423/41451/46631/52413/58321 across runs; each PID saved and killed exactly). Final runs: **pass 1 — 90/90 green** (unit→determination→comment→finalize chain, full permit journey SUBMITTED→REVISION_REQUESTED→UNDER_REVIEW→APPROVED→ACTIVE→COMPLETED with fees 15000 provisional/21000 assessed, closure suspend/reinstate invariants 12→0→12 visitor days, treatments, volunteers, grazing award, OCC 412, cost-share 3004 pinned rounding, citations suspend/void-reinstate, population 70/69 boundary, pagination). **Pass 2 — 47/47 green** (finalize 422-from-ADJUDICATION vs 409-from-PUBLIC_COMMENT, ERR_USE_TYPE_MISMATCH / NOT_FINAL / USE_INCOMPATIBLE gate order, FULL closure → EXPIRED on late lift, TRAILS_ONLY→RESTRICTED, posture-gated program create + treatment start, commercial capacity 2/day, empty-pool offering EXPIRED, leap-year 365-day clearance boundary, and the pinned volunteers-before-programs clock race producing CANCELLED not COMPLETED). The 6 initially failing checks were all smoke-script bugs (stale dates, non-intersecting windows, a leap-year miscount); no implementation defects found.

#### PRD ambiguities resolved (interpretations chosen)
1. `current_utc` renders as the clock reads — normalized ISO8601, fractional digits only when the input carried them; audit fields always 3-digit.
2. Malformed date strings (not `YYYY-MM-DD`) → `ERR_INVALID_REQUEST` 400 (shape), not 422.
3. Scalar domain constraints (`acreage>0`, `crew_size>=1`, ratings 1-10, `max>=min`, `target_count>0`) → 400 shape errors.
4. `reason` required on revoke/void, `note` required on return-for-revision, `rationale` required on finalize (scaffold lists them un-`?`ed).
5. `note` on adjudicate/resubmit accepted but not persisted (no entity field exists).
6. Recomputes that land on the same value do not bump `version`/`updated_at` (no modification occurred).
7. Comment create/adjudicate bumps the parent determination's version (unresolved_comment_count changed).
8. Permit/assignment lists: explicit mismatched ownership filter → 403; absent → silently confined to caller.
9. Cooperator reads (bids/offerings/agreements) not ownership-confined — PRD anchors only writes (bid create, PAYMENT).
10. Treatment overlap check consults all treatments on the unit regardless of status (no status qualifier in PRD).
11. Breeding-window intersection uses inclusive bounds on both treatment window dates.
12. GRAZING gate (locked: no `determination_id` on offering create): latest-created FINAL GRAZING determination governs; none FINAL → `ERR_DETERMINATION_NOT_FINAL`; its finding ≠ COMPATIBLE → `ERR_USE_INCOMPATIBLE`.
13. Resource-anchored ownership is checked after existence (missing → 404; existing → 403 before state); shape 400 still precedes 404 per the pinned cascade.
14. Unknown `status` filter values on lists match nothing (empty page), not 400.
15. Invalid `limit`/`offset` → 400 (`must be at least 1 and at most 100`).
16. Clock may be set backward (no rule forbids it).
17. Ledger `amount_cents` and assess `aum_used`/`rate_cents_per_aum` carry no positivity constraint (none stated); the fiscal rules (22/24) bound them.
18. `expected_agreement_version` is required (400 if absent) on agreement-subject citations and ignored on permit-subject citations.
19. No window-in-past check on closure create or permit create (validation 19's applies_to omits both) — deliberately not added.
20. Posture recompute is scope-only (any ACTIVE closure, dates irrelevant); the treatment-start and program-create gates are the date-scoped variants.
21. Commercial capacity counts COMMERCIAL_FILMING permits only (locked adjudication), in {APPROVED, ACTIVE}, per calendar day.

**No guard, check, or state gate was added beyond PRD prose** — every validation traces to scaffold §1.4 / PRD §2.6, and the two PRD-locked adjudications (commercial capacity scope; grazing offering gate without determination_id) are implemented as written.

**Orchestrator verification:** 21 files present in workspace/implementation/; start.sh execs `python3 app.py` in foreground; app.py binds `0.0.0.0` on `int(os.environ.get('PORT', '10000'))`; only `uuid4().hex` occurrence is the `req_` envelope id (non-resource); store.py uses uuid4 for resource ids (dashed). Steps 5 and 6 ran SEQUENTIALLY (per command args — endpoint duplicates parallel tool calls), with the ISOLATION RULE enforced on Step 6.

## Step 7: Run tests and iterate — 2026-10-02T23:04:00.000Z

Summary:
- **Iterations run**: 1 (clean on the first sweep — no fixes needed).
- **Tests deleted**: none.
- **Fixes applied to `test_helpers/`**: none.
- **Fixes applied to `test_suite/`**: none.
- **Fixes applied to `implementation/`**: none.
- **Sweep result**: all 8 parallel rounds passed 84/84 under `--isolation per-test-server`. No flakiness observed across rounds.
- **Deliverables**: `results.1.json` … `results.8.json` remain in `workspace/implementation/` (verified present, not deleted).
- **Unasserted sibling PRD paths**: not applicable — no test-side fixes were made, so no coverage was narrowed this iteration.

**Orchestrator verification:** read all 8 `results.{1..8}.json` myself — each reports `passed: 84, total: 84, failed: 0`. Files present on disk (24.6KB each, mtime 23:03).

## Step 8: Finalize PRD — SKIPPED — 2026-10-02T23:05:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced. Step 9 will start from `PRD.md`.

## Step 9: PRD completeness scan — 2026-10-02T23:28:00.000Z

PRD_COMPLETED.md is complete. Final summary:

### Step 9 Result — task_3500_wildlife_refuge_public_use_permitting_habitat_management

**File:** `workspace/PRD_COMPLETED.md`

**Size:** PRD.md 364 lines / 67,785 chars → PRD_COMPLETED.md 364 lines / 70,328 chars (**+2,543 chars**, 0 line changes — all edits are in-paragraph inserts/revisions; no new sections).

**Counts:** 19 ambiguity-pins (across 17 edit sites) · 0 mismatch-revisions · **2 IMPL BUGs reported** (PRD left unchanged at both sites).

#### Changes (one bullet each)
- §2.3 — insert — ambiguity — invalid/out-of-range `limit`/`offset` rejected with `ERR_INVALID_REQUEST` (400) — `util.py:113-136`
- §2.3 — insert — ambiguity — `created_at` sort ties (common under the logical clock) break by creation order, earliest first — `util.py:139-146` (sorts by `_seq`)
- §2.3 — insert — ambiguity — filter params match exactly; non-matching values yield empty pages, never an error — e.g. `permits.py:99-106`, `programs.py:178-183`
- §2.4 — revise — ambiguity — `version` starts at 1 on creation — `store.py:63-73`
- §2.4 — insert — ambiguity — a derived-field recompute (`access_posture`, `committed_visitor_days`, habitat scores) landing on the existing value is not a modification; `updated_at`/`version` untouched — `store.py:76-88` (`mutate` dirty-check)
- §2.4 — insert — ambiguity — date input accepts any ISO 8601 calendar-date form, canonicalized to `YYYY-MM-DD` — `util.py:13-20,96-101` (Python 3.14 `date.fromisoformat` accepts compact/week forms)
- §2.5 — insert — ambiguity — clock target need not be later than current reading; no rewind of fired transitions; missing/unparseable `to_iso8601` → `ERR_INVALID_REQUEST` — `clockctl.py:14-22`
- §2.6 item 2 — insert — ambiguity — resource-bound anchors (applicant_ref / cooperator_ref / volunteer_id) evaluate once the resource loads; a nonexistent path id surfaces `ERR_NOT_FOUND` and the anchor never fires — `permits.py:78-82,127-137`, `programs.py:157-163`
- §2.6 item 3 — insert — ambiguity — undeclared body members are ignored, not rejected — `util.py:38-44` + per-endpoint getters
- §3.3 — revise — ambiguity — revoke's `reason` is required request input, not persisted on the permit (PRD named no persistence target, unlike `revision_note`) — `permits.py:204-221`
- §3.6 — insert — ambiguity — `max_volunteers` < `min_volunteers` → `ERR_INVALID_REQUEST` (error id previously unnamed) — `programs.py:50-51`
- §3.7 — insert — ambiguity — with multiple GRAZING determinations, only FINAL ones are consulted and the latest-created FINAL governs — `calc.py:168-175`
- §3.7 — insert — ambiguity — close-and-select response carries the updated offering; the created agreement is read via the agreement endpoints (e.g. `winning_bid_id` filter) — `grazing.py:149-158`, `engine.py:124-158`
- §3.8 — insert — ambiguity — assess's `aum_used`/`rate_cents_per_aum` validated as integers only, no range bound — `agreements.py:58-61`
- §3.8 — insert — ambiguity — ledger `amount_cents` validated as integer only, no bound beyond the fiscal guards — `agreements.py:85`
- §3.8 — revise — ambiguity — citations issuable against agreements in any standing, incl. `COMPLETED` (debit applies, status unchanged) — `citations.py:45-75`
- §3.8 — revise — ambiguity — void's `reason` is required request input, not persisted on the citation — `citations.py:103-123`
- §3.9 — insert — ambiguity — `survey_count` validated as integer only, no range bound — `population.py:58`
- §4 — insert — ambiguity — undeclared method on a declared path → `ERR_NOT_FOUND` (404) — `app.py:48-50`

#### IMPL BUGs (PRD untouched at these sites)
1. **`store.py:76-88` × `agreements.py:74-77,105-107,114-116`** — §2.4 verbatim: "recording a period assessment, posting a ledger entry, issuing an agreement-subject citation, and voiding such a citation each increment the agreement's `version` by exactly one" — a zero-amount assessment (`aum_used=0` or `rate=0`, both legal), zero `PAYMENT`, or zero `REFUND` changes no stored total, so `mutate()`'s dirty-check leaves `version` unchanged. (Citation issue/void always move `compliance_points` by ≥10, so they comply.) — *Fix direction: force exactly-one version increment on the four pinned write paths regardless of value change (e.g. `force` flag in `mutate`).*
2. **`determinations.py:147`** — §3.2 verbatim: "adjudicates each submitted comment, recording a `disposition` of `ACCEPTED`, `REJECTED`, or `NOTED` along with an optional `note`" — the `note` is accepted (`opt_str`) but never persisted or returned; the comment entity has no note field. ("Recording … along with" governs the note; contrast §3.3 resubmit's "may carry … an optional note", which is request annotation and correctly unpersisted.) — *Fix direction: add a nullable note field to the comment record, set it at adjudication, expose it in comment responses.*

#### Dead-check sweep (24 §2.6 business validations)
All 24 have live callsites — **no NOs**. (7 `treatments.py:43-52`; 8 `programs.py:57`, `treatments.py:101`; 9 `permits.py:169`, `grazing.py:51-54`; 10 `permits.py:172`, `grazing.py:56`; 11 `programs.py:132`; 12 `permits.py:52`; 13 `grazing.py:118-121`; 14 `programs.py:135-139`; 15 `programs.py:141-145`; 16 `permits.py:175-178`→`calc.py:140-158`; 17 `determinations.py:100`; 18 `determinations.py:43`, `permits.py:55,144`, `treatments.py:54`, `closures.py:39`, `grazing.py:60`; 19 `determinations.py:46,82`, `treatments.py:57`, `programs.py:60`, `grazing.py:64,123`; 20 `treatments.py:60-65`; 21 `permits.py:197`; 22 `agreements.py:110-112`; 23 `agreements.py:129`; 24 `agreements.py:102`.) Reverse direction also clean: every catalog error_id has a callsite. Note: `app.py:56` maps unexpected exceptions to a non-catalog `ERR_INTERNAL` — crash-only fallback, unreachable under spec-compliant operation; §5 deliberately left unchanged.

#### Nullable-field crash-path sweep
Enumerated every read of PRD-nullable fields: `assessed_fee_cents` (read only under APPROVED state gate, `permits.py:197`; None would yield clean 402, not a crash), `revision_note`/`suspended_by_closure_id` (render-only or `.get`-compare, `engine.py:116`, `permits.py:216`), `finding` (read only after FINAL check, `permits.py:169-173`, `grazing.py:56`), `cleared_on` (None-guarded, `engine.py:36`), `disposition`, `current_survey_count`, `notes` (render-only), citation subject ids (`.get`+truthiness, `citations.py:114`). **No crash paths found.**

#### Locked adjudications
Commercial capacity counts COMMERCIAL_FILMING-only in APPROVED/ACTIVE per unit-day (`calc.py:140-158`) ✓; grazing-offering create gated on the refuge-level FINAL+COMPATIBLE GRAZING determination with no request-supplied determination_id (`grazing.py:48-58`) ✓. Clock start 2026-09-01T00:00:00Z confirmed (`store.py:25`); fixture dates (Sept–Oct 2026, 365-day expiry via advance) reachable ✓.

#### Verified-matching (no change needed, spot-checked)
Nesting-blackout boundary (end exactly 14 days ahead passes, `treatments.py:50`); half-open treatment-overlap across **all** treatment statuses — matches PRD's unqualified "any strict intersection between two windows"; full §2.6 priority order at every multi-rule site (incl. state-before-window on open-comment, ownership-before-shape on create); fee math with cap-then-floor and single half-up rounding; per-period round-then-sum (1502×2=3004); rank score with earliest-created tie-break (`engine.py:138`); boundary-day volunteer expiry; volunteers-before-programs clock order; closure cascade asymmetry (programs never restored); resubmit's use-type rule is vacuous (fields immutable) — `permits.py:140-145`.

**Orchestrator verification:** PRD_COMPLETED.md on disk (364 lines / 70,328 chars = PRD.md +2,543 chars, matches report). No PRD_FINALIZED.md (Step 8 correctly skipped).

## Step 9b: Fix Step-9 impl defects + re-sweep — 2026-10-02T23:38:00.000Z

All done. Final summary:

### Diff summary per file touched (all under `workspace/implementation/`)

**`store.py`** — `mutate(rec, force=False, **changes)`: added the `force` keyword. When `force=True`, `updated_at` and `version` bump exactly once even when no field value changed; default `False` preserves the dirty-check for all unpinned mutations (recompute no-ops elsewhere still do not bump).

**`agreements.py`** — three call sites now pass `force=True`:
- `assess()` (line ~74): zero-amount assessment (aum_used=0 or rate=0) now bumps version exactly once.
- `ledger_entry()` PAYMENT branch (line ~105): zero payment bumps exactly once.
- `ledger_entry()` REFUND branch (line ~114): zero refund bumps exactly once.

**`citations.py`** — two call sites now pass `force=True`:
- `create_citation()` agreement-subject point debit (line ~74): the version-bump guarantee is now explicit rather than accidental-via-points-always-moving.
- `void_citation()` point credit-back (line ~122): same explicit guarantee.

**`determinations.py`** — Fix 2:
- `COMMENT_FIELDS` gained `'note'` (serialization).
- `create_comment()` initializes `'note': None` on the record (null before adjudication).
- `adjudicate()` captures `note = opt_str(body, 'note')` and includes it in the mutate changes only when supplied (stays null when omitted). Resubmit/permit note handling untouched.

### Verification of Fix 1 (manual boot, dynamic port, PID saved and killed exactly via SIGTERM/wait)
Scripted full chain (unit → GRAZING determination → comment → finalize → offering → bid → award) then drove the four pinned paths on a fresh agreement at version 1:
- Zero assessment (aum_used=0): version 1→2, assessed stays 0
- Zero-rate assessment: 2→3
- Zero PAYMENT (amount 0): 3→4
- Zero REFUND (amount 0): 4→5
- Citation issue (agreement subject): 5→6, points 100→90
- Citation void: 6→7, points restored to 100

Each step bumped by exactly +1 — not 0, not 2.

### Verification of Fix 2
- Comment creation returns `"note": null`.
- Adjudication without note: note stays null.
- Adjudication with `note: "incorporated into finding"`: persisted and returned in both the adjudicate response and the list-comments endpoint.

### Final sweep result
All 8 rounds: **84/84 passed, 0 failed, 0 errors** (results.1.json through results.8.json, all retained in `workspace/implementation/`). First attempt after the fixes — no iteration needed.

### Test-side fixes
None. The helpers' shape checks are indeed subset-based, so the new comment `note` field passed cleanly.

No stray processes remain (smoke server PID killed exactly; sweep servers managed by prd-bench-local-run). PRD_COMPLETED.md, test_suite/, and test_helpers/ were not touched.

**Orchestrator verification:** read all 8 fresh `results.{1..8}.json` (mtime 23:37, post-fix) — every round `passed: 84, total: 84, failed: 0`. Post-Step-9 impl writes are covered by this re-sweep (results newer than both the fixes and PRD_COMPLETED.md). Final tree complete: SCAFFOLD.yaml + both design YAMLs, worklog.md, test_helpers/ (9 files), test_suite/ (conftest + 11 files, 84 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_COMPLETED.md, implementation/ incl. start.sh + results.1-8.json}.

## Pipeline complete — 2026-10-02T23:38:00.000Z

End state: 84/84 tests × 8 parallel rounds green under per-test-server isolation, after one fix-free baseline sweep and one post-Step-9b sweep. Step 8 skipped (zero-fix Step 7). Step 9: 19 ambiguity-pins, 0 mismatch-revisions, 2 impl bugs fixed in 9b with re-sweep.
