# Worklog — task_3402_values_led_sourcing_standards_flavor_lifecycle_franchise

## Step 1: Create Task Directory — 2026-10-01T18:25:00.000Z

Task directory pre-allocated by the caller at `./tasks/task_3402_values_led_sourcing_standards_flavor_lifecycle_franchise/` with `workspace/` inside; verified present and empty. No new index computed (caller instruction). Difficulty directive for scaffold generation: "Generate task much harder than expert level!"

## Step 2: Generate Scaffold — 2026-10-01T19:55:00.000Z

All three artifacts are complete, parse-clean, and lint-clean. Final report:

### Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_3402_values_led_sourcing_standards_flavor_lifecycle_franchise/SCAFFOLD.yaml` (673 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_3402_values_led_sourcing_standards_flavor_lifecycle_franchise/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1097 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_3402_values_led_sourcing_standards_flavor_lifecycle_franchise/SCAFFOLD_CORNER_DESIGN.yaml` (2030 lines)

### Parse checks
All three files pass `yaml.safe_load` (re-parsed after every append during construction, and again at the end). Two YAML flow-syntax pitfalls were caught and fixed mid-flight: unquoted `Entity[]` list outputs and `$.data[0].x` / `errors[...]` refs inside flow mappings.

### Lint verdict (verbatim)
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
§1.5 endpoints declared: 66 · §1.1 entities: 12 · §1.8 instances: 18 · §1.9 instances: 70 · calls scanned: 538
```

### Top-level inventory
- **SCAFFOLD.yaml**: `scenario` (verbatim), `domain_name` (values-led-creamery), `api_prefix` (/creamery), `complexity_profile` (compliance_audit × multi_party_negotiation; cyclic machines; segregation_of_duties), `response_envelope` (fixed block), `entities`, `state_machines`, `concurrency_rules`, `calculations`, `validations`, `endpoints`, `errors`, `roles`. No `scaffold_difficulty_design`/`scaffold_corner_design` keys, per spec.
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml**: single key `scaffold_difficulty_design` — 18 instances, exactly 2 per each of the 9 rules.
- **SCAFFOLD_CORNER_DESIGN.yaml**: single key `scaffold_corner_design` — 73 rows (70 active + 3 `excluded_because` stubs) across the 9 taxonomy sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_layers, consistency_model).

### Counts
- **Endpoints: 66** · **Entities: 12** · **State machine entries: 14** (12 entities, with Flavor and Campaign each carrying a parallel second dimension: claim_status and retail_notice_status) · **Calculations: 6** · **Validations: 22** (ordered) · **Errors: 42** · **Roles: 11** (ShopOperator is `entity_backed:ScoopShop`; rest opaque) · **OCC concurrency rules: 2** (commitment-supersede on Supplier.version, claim-substantiate on Flavor.version) · **Difficulty instances: 18** · **Corner instances: 70 active + 3 stubs**

### Difficulty wiring (all replayed against §1.2/§1.4/§1.6, numerics machine-verified)
- Dual-variant calcs in different domains: premium PROVISIONAL vs FINAL (36900 vs 24750 cents), claim coverage DECLARED vs VERIFIED (95.0 vs 85.0).
- Combinatorial modes (a) and (b): tiered premium with deduction/boundary (blended 60 → 16000 → 9600) and pinned round-per-line-then-sum order totals (761, not 762).
- Non-linear machines: Supplier APPROVED↔SUSPENDED cycle; Flavor CORE_LINE→RETIRED→REVIVED→CORE_LINE cycle with an independent claim dimension.
- Cascades: depth-3 audit-fail (supplier→certs→claims, plus commitment lapse) and depth-2 clock-expiry (cert→claim retraction), from different triggers.
- Priority conflicts: state-beats-fiscal on order confirm; safety-beats-referential on claim publish.
- Boundaries: exactly-500 revival signatures qualifies; exactly-95.0 coverage publishes.
- Invariants: single-ACTIVE-commitment cardinality across supersede; plant-day pint-pool conservation across allocate+cancel (6000+4000 > 9000 rejected, then admitted after cancel).
- Governance: independent board vs parent company split (board: campaign decisions/veto, revival adoption, claim challenges; parent: retirement, ops, launch, payment disbursement, logical clock — default `2026-09-01T00:00:00Z`), plus two segregation-of-duties gates (auditor≠verifier, proposer≠decider).

One arithmetic slip in a corner assert (15000 vs correct 16000) was caught by the post-write numeric audit and fixed before delivery. No sibling task directories were read at any point.

Orchestrator verification: re-parsed all three YAMLs independently — parse OK; api_prefix=/creamery, domain=values-led-creamery, 66 endpoints, 12 entities; difficulty/corner top-level keys are lists. Domain confirmed (no foreign-domain contamination).

## Step 3: Copy Shared Files — 2026-10-01T19:57:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes). Workspace previously empty.

## Step 4: Generate PRD — 2026-10-01T20:10:00.000Z

All verification passed. The deliverable is complete.

### Report

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_3402_values_led_sourcing_standards_flavor_lifecycle_franchise/workspace/PRD.md` — **392 lines**, ends complete (final row: `ERR_CLOCK_REGRESSION`).

**Section inventory**:
- §1 Introduction (3 paragraphs: business context, governance tension, logical-clock determinism)
- §2 Global Specifications: 2.1 RBAC (11 roles, identity prose per role — `ShopOperator` entity-backed by `ScoopShop`, other 10 opaque), 2.2 API Response Structure (**byte-identical to the canonical fixed block** — verified by diff), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), 2.4 Common Resource Properties, 2.5 The Logical Clock (default `2026-09-01T00:00:00Z`, 3 clock cascades with strict-inequality semantics), 2.6 Nested Retrieval + 9-rung validation precedence ladder, 2.7 OCC (both rules with endpoint, `expected_*_version`, `ERR_STALE_VERSION`/412), 2.8 Precision/Rounding/Money, 2.9 Mission Governance + both SoD rules, 2.10 Plant Capacity Pools (both pools, all 6 plant constants, compensating releases)
- §3 Business Logic (8 subsections): suppliers/commitments/certifications, audits, dairy farm program + premium formula (both variants), flavor lifecycle + production slots, claims substantiation/publish/challenge, fan revival, campaigns, scoop shops + supply orders
- §4 Endpoint table: 66 rows, 4 columns
- §5 Error catalogue: 42 rows, 2 columns

**Coverage statement** — all scaffold sections fully translated to prose:
- **Contract 1 (Field-Name Coverage): PASS** — 100 entity field entries, 61 request-body identifiers, query params (scaffold folds them into `input` with `?`): 0 missing after two patches (`supplier_id`, `enrollment_id` path-derived FKs added to §3.1/§3.3)
- **Contract 2 (Rule Coverage): PASS** — all 14 state machines (every transition, precondition→error pairing, side effect incl. depth-3 audit-fail cascade, retire cascade, clock cascades), all 6 calculations with constants and rounding order (tier bounds 60/75/90 inclusive-lower, 2pt/NC deduction, excess +1pt bonus, per-line-then-sum pinning, ceil capacity, 500/730 revival, 95/100/90/100 claim thresholds, 0.4/0.3/0.3 weights, 70/2 pass bar), all 22 validations matchable to error_ids, explicit evaluation orders for commitment-create, cert-create (overlap before window validity), publish-claim (4 gates), order-confirm (3 gates), slot-create (date before capacity), revival-create (state before window); sibling branches (void CALCULATED vs APPROVED, substantiate from 3 states, veto from 3 states, cancel from 3 states) rendered with equal density
- **Contract 3 (§3 Path Purity): PASS** — 531 backticked tokens in §3, zero paths, zero bare HTTP methods, zero method+path combos
- All 42 error IDs appear in §2/§3 prose; all 78 enum values and 52 state names appear verbatim

The two forbidden design-index files were never opened.

Orchestrator verification: PRD.md is 392 lines, tail ends on final error-catalogue row (ERR_CLOCK_REGRESSION) — no truncation; 112 table rows, 76 ERR_ mentions, 69 /creamery mentions.

## Step 5: Generate Unit Tests — 2026-10-01T20:40:00.000Z

All checks pass. Final report.

### Deliverables

**`test_helpers/` (Stage 1, frozen)** — 9 files, 1439 lines:
- `types.py` (346) — 12 entity TypedDicts (all carry common fields per PRD §2.4), 14 status/role enums
- `api_client.py` (212) — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (66 methods, all under `/creamery`)
- `api_errors.py` (97) — all 40 PRD §5 error ids with HTTP map, registered via `set_error_http_status_map`
- `assertions.py` (98), `factories.py` (154), `constants.py` (64), `test_users.py` (68 — shared constants for 10 opaque roles + mandatory `make_shop_operator_headers(shop_id)` for the entity-backed role), `fixtures.py` (368 — composite helpers: `create_approved_supplier` via full audit flow, `fail_supplier_audit`, `make_verified_certification`, `make_published_claim_flavor`, `make_retired_flavor`/`make_qualified_revival`, `make_assessed_enrollment`/`make_final_payment`/`make_approved_payment`, `make_operating_shop`/`make_confirmed_order`/`make_allocated_order`, campaign chain helpers), `__init__.py` (32)
- `test_suite/conftest.py` (69) — session-scoped `api` fixture + 11 role-header fixtures; no server lifecycle (runner-owned), hence no port handling

**`test_suite/` (Stage 2)** — 17 test files, 105 tests, ~2270 lines, grouped by concern (`test_01_entity_defaults` … `test_17_security`).

### AST tag audit (real `ast` parse, not grep)
- 105/105 tests carry exactly one `Design:` docstring line; zero tags point at non-existent instances; no tag has >2 tests
- **Queue A (difficulty): 18/18 instances covered at exactly 2 tests each** (36 tests)
- **Queue B (corner): 69/70 active instances covered at ≥1 test** (69 tests); 3 `excluded_because:` stubs not translated, cross-references all resolve
- **Skipped (1)**: `Corner/state_machines/audit_complete_before_start_rejected` — completing a SCHEDULED audit trips PRD §2.6 rung 3 (ownership: `auditor_user_id` is null, so any caller mismatches) before rung 8 (state legality), so the instance's expected `ERR_INVALID_STATE` is not uniquely derivable; a ladder-faithful implementer would return `ERR_FORBIDDEN_OWNERSHIP`
- **Verbatim citation pass**: 164 quoted spans across all docstrings, **0 failures** against PRD.md (whitespace-normalized literal match)

### pytest --collect-only
`105 tests collected in 0.34s`, zero collection errors (PYTHONPATH=. from task dir); `test_helpers` imports cleanly.

### Constants diff vs PRD
ALL MATCH — tiers 60/75/90→5/8/12, deduction 2, excess bonus 1, weights 0.4/0.3/0.3, pass ≥70/findings ≤2, claim thresholds 95/100/90/100, plant-shift units 1000/800/600, plant-day pints 12000/9000/7000, partner discount 0.15, fees 3500000/0, revival 500/730, pagination 10/1/100, clock default `2026-09-01T00:00:00Z`. No skip/xfail markers; no scaffold references in generated code.

### Judgment calls to be aware of
- **`version == 1` at creation** is asserted in 3 tests (`supplier_creation_applies_defaults`, `version_increments_on_mutation` v0, others relative-only). PRD §2.4 says "starts at its initial value" without pinning 1; I kept the design-index value since all instances assume 1-based. If the impl is 0-based, those two absolute assertions fail.
- **Logical-clock timestamps** (`qualified_at`, `retired_at`) are asserted with a `startswith("2026-09-01")` prefix rather than full-string equality, tolerating fractional-second formatting differences the PRD leaves open.
- Mid-generation I caught and fixed a structural bug worth noting: f-string docstrings (`f"""..."""`) are invisible to `ast.get_docstring`, which silently untagged 42 tests in the first audit. All rule-constant interpolation was inlined into plain docstrings, then the verbatim and tag audits re-ran clean.

Orchestrator verification: independently re-ran `pytest --collect-only` (105 collected, 0 errors) and a real AST tag audit (105 tags; 36 Difficulty + 69 Corner — matches report). Constants spot-check: CLOCK_DEFAULT_ISO/PARTNER_DISCOUNT_PCT/REVIVAL_* in constants.py match PRD prose ("the 15 percent partner discount", 500/730 revival, clock default 2026-09-01T00:00:00Z).

## Step 6: Generate Implementation — 2026-10-01T21:05:00.000Z

Done. The implementation is complete, compiles, imports cleanly, and passed two fresh-boot smoke passes.

### File inventory — `workspace/implementation/` (2,369 lines total)

| File | Lines | Responsibility |
|---|---|---|
| start.sh | 10 | Foreground launcher, guarded `pip install`, `exec python3 app.py` on `$PORT` (default 10000), `0.0.0.0`; executable |
| requirements.txt | 1 | flask>=3.0 |
| timeutil.py | 39 | ISO 8601 parse/format (Z-suffixed, 3-fractional-digit wall format) |
| errors.py | 62 | Full 42-entry error catalog (id → HTTP status) + `ApiError` |
| db.py | 77 | In-memory dict stores (empty at boot, no seeding), logical clock at `2026-09-01T00:00:00Z`, UUID ids, strictly-increasing timestamps, `version` (starts 1) + `touch()` |
| envelope.py | 80 | `{meta, response_type, data}` envelope; error envelope; `limit`/`offset` pagination (default 10/0, clamp 1–100) with `total_count`/`has_more` in meta |
| auth.py | 39 | `X-User-ID`/`X-User-Role` auth (401 `ERR_UNAUTHENTICATED`), role authorization (403 `ERR_UNAUTHORIZED`), 11 declared roles |
| validate.py | 170 | Payload validation (400 `ERR_INVALID_REQUEST` / `ERR_INVALID_ENUM`) and all enum domains |
| cascades.py | 68 | Audit-fail depth-3 cascade, cert-revoke claim challenge, cert-expiry claim retraction, flavor-retire cascade |
| clockops.py | 57 | `POST /creamery/_clock/set_current_utc` (regression → 422), time-driven sweep (cert EXPIRED, commitment LAPSED, slot COMPLETED) also run lazily via `before_request` |
| suppliers.py, commitments.py, certifications.py | 77/77/120 | PRD §3.1 (incl. supersede + OCC `expected_supplier_version`, half-open overlap before window validity) |
| audits.py | 150 | PRD §3.2 (composite round-half-up 0.4/0.3/0.3, PASS ≥70 ∧ ≤2 findings, auditor ownership, SoD on verify) |
| farms.py, payments.py | 77/183 | PRD §3.3 (blended score, tiered premium 5/8/12 with bounds 60/75/90 inclusive, +1pt excess bonus, 2pt/NC deduction floored at 0, PROVISIONAL vs FINAL, approve/pay/void with compensating reversal) |
| flavors.py, claims.py | 116/125 | PRD §3.4–3.5 (promote pairs only, retire cascade, OCC `expected_flavor_version`, 2dp coverage bases, 4 publish gates in PRD order) |
| revivals.py | 129 | PRD §3.6 (730-day window inclusive, one signature per email, inclusive 500 threshold, board adopt → REVIVED) |
| slots.py | 173 | PRD §3.4/2.10 (ceil capacity units, 1.5/1.25 factors at 20/15% thresholds, plant-shift pool 1000/800/600, date check before capacity) |
| campaigns.py | 136 | PRD §3.7 (dual governance, proposer SoD, retail-notice gate on launch, board veto) |
| shops.py, orders.py | 117/213 | PRD §3.8 (franchise fee 3,500,000/0, nonprofit open gate, ShopOperator ownership = shop id, per-line-round-then-sum with 15% partner discount, confirm gate order OPERATING→flavors→credit, plant-day pint pool 12000/9000/7000) |
| app.py | 73 | App factory, blueprint registration under `/creamery`, error handlers, `0.0.0.0:$PORT` |

### Verification results

- **py_compile**: all 22 `.py` files compile (`ALL_COMPILED`); `bash -n start.sh` OK.
- **Import check**: `python3 -c "import app"` → `IMPORT_OK`; all 66 scaffold routes present in the URL map (verified against the endpoint table).
- **Smoke test 1** (port 46339, PID 2717991, killed exactly that PID): 401 unauthenticated error-envelope shape confirmed (meta = only `api_request_id` + `api_request_timestamp`, `req_` prefix); supplier create 201 with `response_type:"object"`, `version:1`, `PROSPECT`; 403 `ERR_UNAUTHORIZED` for wrong role; clock advance 200 `{current_utc:"2026-09-02T00:00:00Z"}`; regression 422 `ERR_CLOCK_REGRESSION`; audit schedule→start→complete (composite 76 = round-half-up 75.5, PASS)→verify; SoD 403 `ERR_SOD_AUDITOR_VERIFY`; PASS approved supplier (score 76 written, version 2); OCC 412 `ERR_STALE_VERSION` then 201 commitment `ACTIVE`; list envelope `total_count:1, has_more:false`; 422 `ERR_COMMITMENT_WINDOW_INVALID`.
- **Smoke test 2** (port 43335, PID 2719111, killed): payment on unassessed enrollment 409; blended 75 → tier 8, PROVISIONAL gross 41000 (8000·50·8% + 2000·50·9%); approve-PROVISIONAL 409 `ERR_PAYMENT_NOT_FINAL`; FINAL with 1 non-conformance → eff 6, gross 27500; approve added 27500 to `total_approved_cents`; claim substantiate (declared 100.0, verified 95.0, 2dp) → publish PUBLISHED; clock past `valid_until` → cert EXPIRED and PUBLISHED claim auto-RETRACTED (depth-2 cascade); slot capacity `ceil(10000/100×1.5)=150` units.

### Coverage statement (PRD §3 → modules)

§3.1 → suppliers.py, commitments.py, certifications.py; §3.2 → audits.py; §3.3 → farms.py, payments.py; §3.4 → flavors.py, slots.py; §3.5 → claims.py; §3.6 → revivals.py; §3.7 → campaigns.py; §3.8 → shops.py, orders.py; §2.5 clock → clockops.py; §2.1/2.9 RBAC + both SoD rules → auth.py + route-level checks; §2.2/2.3 envelope/pagination → envelope.py; §2.4 common fields/versioning → db.py; §2.7 OCC → commitments.py + claims.py; §2.10 pools → slots.py + orders.py (derived from live statuses, released by cancellation/retire cascade); all cross-aggregate cascades → cascades.py. Validation ladder order implemented: auth → role → ownership → SoD → path existence (left-to-right) → body-reference existence → OCC → state-machine legality → business rules, with per-endpoint business-rule ordering as stated in each PRD subsection (e.g. publish: lifecycle → coverage → cert status → scope; confirm: OPERATING → flavor availability → credit limit).

Orchestrator verification: independently ran `python3 -m py_compile` on all 22 modules (ALL_COMPILE_OK), `start.sh` is executable, `db.py` initializes `version: 1`, blueprints registered under `/creamery` in app.py:56. ISOLATION RULE was enforced (no design-index/test reads in scope).

## Step 7: Run Tests + Iterate — 2026-10-01T21:30:00.000Z

Clean 8-round parallel stability sweep on the first iteration — no fixes required.

- Command: 8x concurrent prd-bench-local-run, --isolation per-test-server, --timeout 120, --test-timeout 30, results.N.json per round.
- Result: rounds 1-8 each 105/105 passed, 0 failed, 0 errors, 0 skipped (~176s wall per round under 8-way concurrency).
- No flakiness surfaced: union of failing tests across all 8 rounds is empty.
- All 8 results.N.json files left in place under workspace/implementation/ as deliverables.
- No test deletions, no test_helpers/test_suite/implementation edits this step.

## Step 7: Run Tests and Iterate — 2026-10-01T21:35:00.000Z

Step 7 complete — the exit condition (all 8 parallel rounds with `passed == total`) is met on the first iteration.

### Summary

- **Iterations run**: 1 (single 8-round parallel sweep; all rounds 105/105 passed, 0 failed, 0 errors, 0 skipped; ~176s wall per round under 8-way concurrency).
- **Tests deleted**: none.
- **Fixes applied to `test_helpers/`**: none.
- **Fixes applied to `test_suite/`**: none.
- **Fixes applied to `implementation/`**: none — the Step 6 implementation passed the full suite on the first sweep with no flakiness surfacing across any of the 8 concurrent rounds.
- **Sibling unasserted paths worth naming for PRD-finalization**: none flagged by this loop (no test-side fixes occurred, so no shadowed sibling paths were exposed). Note from the Step 5 worklog that one corner instance (`audit_complete_before_start_rejected`) was deliberately never translated into a test because the ownership rung (ERR_FORBIDDEN_OWNERSHIP) pre-empts the state rung — that path remains unasserted by design.

Deliverables in place: `workspace/implementation/results.{1..8}.json` (all 8 retained, each showing 105/105).

Orchestrator verification: independently re-read all 8 `results.${i}.json` — every round passed: 105 total: 105 failed: 0 errors: 0. ALL_CLEAN.

## Step 8: Finalize PRD — SKIPPED

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced.

## Step 9: Complete PRD — 2026-10-01T21:55:00.000Z

All 16 pins are in place and the diff is verified clean. Task complete.

### Summary

**Produced** `workspace/PRD_COMPLETED.md` (396 lines / 61,079 chars) as a patch over `PRD.md` (392 lines / 58,548 chars): **+4 lines, +2,531 chars**.

**Counts:** 16 ambiguity-pins · 0 mismatch-revisions · 0 impl-gaps · 5 dead-code flags.

The clean Step-7 sweep held up under scrutiny: every concrete PRD rule (all formula constants, thresholds, state machines, check orderings, cascade depths, the 45-route table with role matrices, and the 42-entry error catalog) matched the implementation exactly — no mismatches and no PRD-required behavior omitted. All edits pin prose that admitted multiple readings.

#### Ambiguity-pins (one bullet per change)

- **§2.3** — insert — ambiguity — out-of-range `limit`/`offset` are clamped (limit to [1,100], negative offset to 0), not rejected; non-integer values fail `ERR_INVALID_REQUEST` — `implementation/envelope.py:32-56`
- **§2.3** — insert — ambiguity — a `status`/filter value matching nothing yields an empty page, never an error — `implementation/commitments.py:71-74` (same pattern in certifications, revivals, slots, orders lists)
- **§2.4** — revise — ambiguity — `version` starts at **1** on creation (PRD said only "its initial value", undefined) — `implementation/db.py:48-58`
- **§2.4** — insert — ambiguity — an enum field whose value is not a string at all is malformed (`ERR_INVALID_REQUEST`); only a string outside the declared set is `ERR_INVALID_ENUM` — `implementation/validate.py:129-138`
- **§2.5** — revise — ambiguity — time-driven evaluations are applied lazily at the start of **every request** (reads and writes), not only when an affected resource is read — `implementation/app.py:32-36`, `clockops.py:22-43`
- **§2.6** — insert — ambiguity — payload well-formedness (§2.4 checks) sits between ladder rungs 5 and 6: after path existence, before body-reference existence/OCC/state/business — e.g. `implementation/commitments.py:26-44`, `claims.py:44-59`
- **§3.1** — insert — ambiguity — `premium_over_commodity_pct` is a non-negative number — `implementation/commitments.py:31`
- **§3.2** — insert — ambiguity — audit verification has **no supplier-state guard**: the `composite_score` write is unconditional; PASS moves only PROSPECT/SUSPENDED (APPROVED/TERMINATED unchanged); FAIL runs the cascade even for SUSPENDED/TERMINATED but moves status only from PROSPECT/APPROVED/SUSPENDED — `implementation/audits.py:126-150`
- **§3.3** — insert — ambiguity — FINAL recomputation reads the enrollment's `blended_score`/`baseline_volume_liters` as they stand **at finalization time**, not snapshotted at creation — `implementation/payments.py:126-132`
- **§3.4** — insert — ambiguity — `target_state` is an enum over exactly {TEST_BATCH, LIMITED_RUN, CORE_LINE}; other values fail `ERR_INVALID_ENUM`, valid-but-illegal steps fail `ERR_INVALID_STATE` — `implementation/flavors.py:82`, `validate.py:29`
- **§3.4** — insert — ambiguity — `planned_pints` must be a positive integer — `implementation/slots.py:87`
- **§3.5** — insert — ambiguity — substantiation accepts any declared `claim_type` including `NONE`; `certification_ids` must be a non-empty array — `implementation/claims.py:46-47`
- **§3.5** — insert — ambiguity — no coverage threshold exists for a `NONE` claim, so publishing one always fails gate 2 with `ERR_CLAIM_COVERAGE_INSUFFICIENT` — `implementation/claims.py:89-94`
- **§3.6** — insert — ambiguity — sign `count` defaults to 1 when omitted and must be a positive integer when present — `implementation/revivals.py:86`
- **§3.6** — insert — ambiguity — if the flavor is no longer RETIRED at adoption time (e.g. double-adoption), the request still moves to ADOPTED and the flavor is left unchanged — `implementation/revivals.py:112-115`
- **§3.8** — insert — ambiguity — order `lines` must be a non-empty array; each `quantity_pints` a positive integer — `implementation/orders.py:42-63`

#### Mismatch-revisions
None. Every concrete PRD rule matched the implementation.

#### Impl-gaps (PRD-required but unimplemented)
None found — no PRD rule is absent from the implementation, so no prose was preserved under the hard rule.

#### Dead-code flags (defined-but-unreachable guards; green sweep never exercises them)
- `implementation/claims.py:98` — publish gate 3's `c is None` disjunct is unreachable: certifications are never deleted and their existence was verified at substantiation.
- `implementation/orders.py:149` — confirm's `flavor is None` disjunct is unreachable: flavors are never deleted and creation already verified each line's flavor.
- `implementation/revivals.py:113` — adopt's `flavor is not None` half-guard is always true (flavors never deleted); the adjacent `status == "RETIRED"` condition is reachable (double-adoption), only the None-check is dead.
- `implementation/audits.py:79`, `audits.py:140`, `certifications.py:96` — `supplier is not None` guards always true (suppliers never deleted; children always reference an existing supplier).
- `implementation/validate.py:63-69` — `opt_str` helper is defined but never called by any endpoint.

Orchestrator verification: `diff -q PRD.md PRD_COMPLETED.md` confirms a real diff (396 vs 392 lines — not a silent no-op copy); spot-read of the diff shows substantive pins. `find implementation -name "*.py" -newer implementation/results.1.json` is empty — implementation untouched after the clean sweep, sweep remains valid. All 8 `results.{1..8}.json` retained.

## Pipeline Complete — 2026-10-01T21:57:00.000Z

All 9 steps done (Step 8 skipped per its zero-fix condition). Final state: SCAFFOLD.yaml + both design indices (parse-clean, domain-verified), PRD.md (392 lines), PRD_COMPLETED.md (396 lines, 16 ambiguity pins), test_helpers/ (9 files) + test_suite/ (17 files, 105 tests, 18/18 difficulty + 69/70 corner instances), implementation/ (22 modules, 2,369 lines), 8/8 sweep rounds at 105/105.
