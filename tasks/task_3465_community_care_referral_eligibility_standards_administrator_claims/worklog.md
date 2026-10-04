# Worklog — task_3465_community_care_referral_eligibility_standards_administrator_claims

## Step 1: Create task directory — 2026-10-02T08:46:00.000Z

Pre-allocated directory `tasks/task_3465_community_care_referral_eligibility_standards_administrator_claims/` verified to exist with `workspace/` inside (created by the caller per command args; no new index computed, no other task_* directory created). Difficulty instruction for scaffold-generator: "Generate task much harder than expert level!"

## Step 2: Generate scaffold — 2026-10-02T08:46:00.000Z

Done. All three scaffold artifacts are generated, cross-consistent, and lint-clean.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_3465_community_care_referral_eligibility_standards_administrator_claims/SCAFFOLD.yaml` (1303 lines — §1.0–§1.7; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_3465_community_care_referral_eligibility_standards_administrator_claims/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1564 lines — single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_3465_community_care_referral_eligibility_standards_administrator_claims/SCAFFOLD_CORNER_DESIGN.yaml` (2932 lines — single key `scaffold_corner_design`)

## Key facts

- **api_prefix**: `/community-care` (domain: `community-care-referral`)
- **Entities (12)**: CareStation, ThirdPartyAdministrator, CommunityProvider, Veteran, EligibilityAssessment, ReferralAuthorization, ExtensionRequest, Appointment, MedicalDocumentation, Claim, UrgentCareVisit, PrescriptionFillRequest
- **Surface**: 40 endpoints, 32 error codes, 8 roles (3 entity-backed: TPAAdministrator→TPA, ProviderRep→CommunityProvider, Veteran→Veteran; 5 opaque)
- **§1.8**: 19 instances across all 9 rules (≥2 each; combinatorial_formula carries a third instance so modes (a), (b) and (c) are all exercised)
- **§1.9**: 63 instances (54 executable + 9 `excluded_because` stubs citing §1.8 coverage); 852 total calls linted
- **Lint**: `VERDICT: clean lint` on the final run (4 FK-reverse-reachability violations found and fixed mid-way: parent path params renamed to `{id}`, two denormalized FKs demoted to prose, provider reads restructured as `GET /tpas/{id}/providers`, added `GET /veterans/{id}/urgent-care-visits` — endpoint count held at 40)

## Notable design decisions

- **Logical clock**: `POST /community-care/_clock/set_current_utc`, startup default pinned to `2026-09-01T00:00:00Z`; each set runs three ordered sweeps (expiry → doc-overdue suspension cascade → auto-close)
- **Named constants**: drive standards 30/60 min, wait standards 20/28 days (strict `>`), timely filing 180 days inclusive, doc return 30 days + 15-day reject grace, 60-min half-open slots, 5-day scheduling timeliness, visit caps 12/12/365/180, Medicare fallback 10000/18000c, TPA fee 2.5% per-line-round-then-sum, resubmission max 2, denial-rate suspension at ≥5 events AND rate > 0.20, urgent copay tiers 0 / 1500→3000 / 3000→4500 with FY (Oct 1) reset, Rx caps 14d urgent / 90d referral
- **Hardness mechanics**: dual-variant drive time (urban 1.4/40mph vs rural 1.2/55mph — same coordinates give 37.9 vs 23.6 min and opposite eligibility) and contract-vs-Medicare claim pricing (15600c vs 17550c on identical lines); cyclic machines on Claim (resubmission), MedicalDocumentation (reject loop), and ReferralAuthorization (DOCS_SUSPENDED); two depth-3 cascades (clock→doc→auth→extension; decredential→claims→TPA suspension); two OCC rules (`expected_veteran_version`, `expected_referral_authorization_version`); two conserved quantities (visit ledger `authorized+extended == completed+reserved+remaining`; payment buckets `lifetime == current+reversed`)
- **All formula-derived asserts are pre-computed literals** (haversine distances, fee rounding, copay tiers, bucket totals) verified with Python before writing
- One repair during QA: removed unreachable `ERR_URGENT_VISIT_NOT_RECORDED` / `VOID` state (no API path could produce them); all 32 remaining errors are referenced by validations/transitions and covered by at least one design instance

Orchestrator verification: all three files exist, parse as YAML, top-level keys correct (SCAFFOLD.yaml lacks both design keys); spot-grep confirms api_prefix `/community-care` and entities ReferralAuthorization/EligibilityAssessment/ThirdPartyAdministrator/UrgentCareVisit/PrescriptionFillRequest present — no foreign-domain artifact.

## Step 3: Copy shared files — 2026-10-02T08:47:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (53 lines). Orchestrator-measured design-index ground truth for Step 5 queue sizing: difficulty 19 executable (dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2); corner 54 executable + 9 stubs (entities 8, state_machines 12, calculations 4, validations 19, endpoints 3, errors 0 exec/9 stub, rbac 5, cross_cutting_layers 2, consistency 1). Total executable: 73.

## Step 4: Generate PRD — 2026-10-02T08:50:00.000Z

The PRD is complete and all verification passes. Final summary:

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3465_community_care_referral_eligibility_standards_administrator_claims/workspace/PRD.md` — **324 lines**. The two test-targeting design files were never opened.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC (8 roles with per-role identity prose), 2.2 API Response Structure (byte-identical verbatim block, verified programmatically), 2.3 Pagination (limit 10/1/100, offset 0, created_at ascending), 2.4 Common Resource Properties, 2.5 Logical Clock & Scheduled Sweeps, 2.6 OCC, 2.7 Units/Precision/Rounding, 2.8 Validation Pipeline & Error Precedence (12 ordered stages), 2.9 Nested Resource Retrieval, 2.10 Conserved Ledgers
- §3 Business Logic: 3.1 Network build-out & credentialing, 3.2 Veteran enrollment & eligibility determination, 3.3 Referral authorizations, 3.4 Extension requests, 3.5 Appointments, 3.6 Medical documentation loop, 3.7 Claims lifecycle, 3.8 Urgent care & pharmacy
- §4 Endpoint Definitions (40 rows, 4 columns), §5 Error Code Catalogue (32 rows, 2 columns)

**Error IDs in prose:** **32/32** grep-able verbatim in the §2/§3 prose (in addition to the §5 table), each at the rule that raises it, with the scaffold's priority ordering rendered as the explicit 12-stage pipeline in §2.8.

**Constant pinning confirmation:** all verified present with concrete values by script — drive-time 30/60 min (strictly-greater boundary stated), wait-time 20/28 days (equal passes), timely filing 180 days inclusive, documentation 30-day return + 15-day reject grace, 60-minute half-open slots, 5-day scheduling timeliness (inclusive, negative lag within), visit caps 12/12/365/180, Medicare fallbacks 10000/18000 cents, TPA fee 2.5% per-line round-half-up-then-sum (sum-then-round explicitly non-conformant), resubmission max 2, suspension at ≥5 events AND rate strictly > 0.20 (exactly 0.20 does not suspend), copay tiers 0 / 1500→3000 / 3000→4500 cents with Oct 1 fiscal-year reset, Rx caps 14/90 days, haversine variants 1.4/40mph vs 1.2/55mph with 3958.8-mile earth radius (2.1000 vs 1.3091 min/mile), logical clock endpoint `POST /community-care/_clock/set_current_utc` with startup default 2026-09-01T00:00:00Z and the three ordered sweeps.

**Hard Contract reports:**
- Contract 1 (Field-Name Coverage): 93 required identifiers (12 entities' fields + all endpoint input/query/path params + `units`/`unit_billed_cents` line sub-fields), 93 present, 0 missing — **PASS**
- Contract 2 (Rule Coverage): 12 validation stages ordered in prose; 2 OCC rules with endpoint + expected-version field + `ERR_STALE_VERSION`/412; 37 state-machine transitions fully expressed (including Claim DENIED→RECEIVED loop, documentation REJECTED→AWAITED loop, DOCS_SUSPENDED oscillation with remembered return state, and the decredential→auto-deny→TPA-suspension cascade chain); 9 calculations reconstructible from prose; all endpoint side effects and applies_to scopes covered; sibling branches (urban/rural, MID/HIGH bands, PAID/DENIED, ACCEPTED/REJECTED) at equal density — **PASS**
- Contract 3 (§3 Path Purity): 517 backtick tokens scanned in §3, 0 violations (endpoints referenced only via state-pair framing, role+verb, or capability) — **PASS**

Orchestrator spot-check: PRD.md is 324 lines; grep confirms `set_current_utc`, `2026-09-01T00:00:00Z`, 71 `ERR_` mentions, 30/60-min drive standards with strict-greater semantics (line 166), "2.5 percent" per-line fee (line 222), haversine 3958.8/1.4/40/1.2/55 (line 162), 20/28-day wait standards, 180-day filing. Constants pinned.

## Step 5a: Generate test helpers (Stage 1 of split Step 5) — 2026-10-02T08:55:00.000Z

Stage 1 is complete and frozen. Summary:

## Files written (all under `.../task_3465_community_care_referral_eligibility_standards_administrator_claims/test_helpers/`)

| File | Lines | Contents |
|---|---|---|
| `types.py` | 332 | 20 enums + 14 entity TypedDicts. All entities carry `id/created_at/updated_at/version` — PRD §2.4 states "No entity in this contract omits `updated_at` or `version`", so no append-only omissions apply here. |
| `constants.py` | 115 | Full constant table (below) + shared fixture geography. |
| `api_errors.py` | 82 | `ApiErrorId` (32 ids) + `HTTP_STATUS_CODES`, registered via `set_error_http_status_map` at import. |
| `api_client.py` | 241 | `ApiClient(GenericApiClient)`, one method per endpoint (34 endpoints), all paths carrying the `/community-care` prefix; `api_client` singleton. |
| `factories.py` | 201 | 21 payload factories, input fields only; required FKs are positional parameters so no payload can silently lack a parent. |
| `assertions.py` | 236 | `assert_{entity}` × 12 plus invariant checkers `assert_visit_ledger_conserved` and `assert_payment_buckets_conserved`; assessment assertion re-derives `eligible` as OR of its four legs. |
| `test_users.py` | 43 | `TEST_USERS` for all 8 roles + per-instance builders `make_tpa_admin_headers` / `make_provider_rep_headers` / `make_veteran_headers` for the 3 entity-backed roles. |
| `fixtures.py` | 608 | 5-tier composite fixtures (details below). |
| `__init__.py` | 25 | Barrel export of framework generics + all PRD-specific modules. |

## Clock endpoint decision
`POST /community-care/_clock/set_current_utc` — **under the api_prefix**, unanimous across sources: PRD §2.5 (line 94) and §4 table (line 246), SCAFFOLD.yaml endpoint row (line 846) and PlatformAdmin role row (line 1236), plus 51 call sites in the corner design and every difficulty recipe. Baked into `ApiClient.set_clock`.

## Clock-start consistency
Startup default `2026-09-01T00:00:00Z` frozen as `CLOCK_START_ISO`. Default fixture dates are all forward-reachable from it (start 2026-09-05, requested 2026-09-02, appointments from 2026-09-06). Helpers that need past deadlines advance the clock explicitly: `make_documentation_overdue` (complete at a known clock, then set clock to `complete_at + 31d`, asserts OVERDUE), `record_urgent_visits_on_days` (one clock set per day, respecting the same-day rule), `set_clock`/`reset_clock` exposed for Stage 2.

## Constants table (all 29 literals grep-verified against PRD prose — "ALL 29 CONFIRMED")
Drive 30/60 min (strict >), wait 20/28 d (strict >), choice max PG 4; haversine R=3958.8, urban 1.4/40, rural 1.2/55; visits 1..12 initial, duration ≤365, extension ≤12 visits/≤180 d; doc deadline 30d + 15d reject grace; slot 60 min half-open; timeliness ≤5 d inclusive; filing ≤180 d inclusive; resubmission max 2; Medicare fallback 10000/18000c; TPA fee 2.5% per-line round-half-up; suspension ≥5 events AND rate strictly > 0.20 (4dp); copays LOW 0 / MID 1500→3000 / HIGH 3000→4500 at visit index ≤3, bands 1-3/4-6/7-8, FY resets Oct 1 (month ≥ 10 → year+1); Rx caps 14d urgent / 90d appointment. Shared geography: station (40.0, −75.0), home (40.2609, −75.0) → 37.9 urban min (fails primary standard) / 23.6 rural (passes), matching both design indices' fixture anchors.

## Compile/import smoke
`python3 -m py_compile` — 9/9 OK. Package smoke `import test_helpers.fixtures` with task dir on sys.path — OK (32 errors registered, client exposes 46 attrs). No `test_suite/` created.

## PRD ambiguities resolved in helpers
1. **No single-provider GET exists** — `get_provider()` reads through `GET /tpas/{id}/providers` roster.
2. **Scheduler caller selection** — `schedule_appointment` auto-picks `make_tpa_admin_headers(auth["tpa_id"])` vs CareCoordinator from `scheduling_responsibility`; explicit `headers=` override reserved for wrong-caller tests.
3. **OCC fields** — `run_assessment` and `decide_extension_request` re-read the parent's current `version` internally, so fixtures never thread stale versions.
4. **Claim `service_date`** defaults to the completed appointment's scheduled date (PRD requires the COMPLETED-appointment date match).
5. **Documentation GET returns a 0/1-element array** — `get_documentation_for_appointment` unwraps to record-or-None.
6. **Extension create** defaults to CareCoordinator; `as_provider=` threads a ProviderRep identity for the shared role.
7. **Identity threading everywhere ownership-gated**: onboard→TPA id, complete/submit/claim/resubmit/rx→provider id, urgent-visit/veteran-cancel→veteran id, adjudicate/reverse→TPA id; shared `TEST_USERS` constants documented as non-ownership-only for entity-backed roles.

Stage 2 can now be launched against this frozen interface; it should read `fixtures.py` for exact return-dict keys (`station/tpa/provider/veteran/assessment/authorization`, plus `appointments`/`documentations`/`claim` on composites) and pass `expected=201` to `validate_success` on creates.

Orchestrator verification: 9 helper files present (1883 lines total), `import test_helpers.fixtures` OK; `api_client` singleton binding verified via importlib (module has ApiClient + api_client; plain-import binds the instance — known benign pattern).

## Step 5b: Generate test suite (Stage 2 of split Step 5) — 2026-10-02T09:05:00.000Z

Stage 2 is complete. Final summary:

## Stage 2 Complete — test_suite for task_3465

### Files written (14, all under `/home/ubuntu/github/CodingPRD/tasks/task_3465_community_care_referral_eligibility_standards_administrator_claims/test_suite/`)

| File | Lines | Tests |
|---|---|---|
| conftest.py | 40 | — |
| test_01_eligibility_standards.py | 126 | 4 |
| test_02_reference_data_and_envelope.py | 193 | 8 |
| test_03_referral_creation.py | 172 | 6 |
| test_04_episode_lifecycle.py | 96 | 4 |
| test_05_episode_close_and_cancel.py | 168 | 5 |
| test_06_extensions_and_occ.py | 170 | 5 |
| test_07_appointments.py | 214 | 7 |
| test_08_documentation.py | 190 | 6 |
| test_09_claims_payment.py | 254 | 7 |
| test_10_claims_validations.py | 177 | 6 |
| test_11_tpa_surveillance.py | 141 | 3 |
| test_12_urgent_care_and_rx.py | 196 | 6 |
| test_13_rbac.py | 142 | 6 |

Total: **73 tests**.

### Coverage per queue / rule / section

Queue A (Difficulty, 19): dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.

Queue B (Corner, 54): entities 8, state_machines 12, calculations 4, validations 19, endpoints 3, rbac 5, cross_cutting_layers 2, consistency 1. The 9 `errors`-section `excluded_because:` stubs were not translated (their difficulty-instance owners carry the assertions; all 9 cross-references resolve).

### Skipped instances

**None.** All 73 executable instances passed the PRD-first two-condition filter (verbatim coverage + unique derivability).

### Two adjudications made during translation (flagged, not skips)

1. **`Corner/state_machines/referral_expiry_cascade_on_clock_crossing`** — the recipe asserts final status `EXPIRED`, but the episode has zero documentation records (its only appointment is SCHEDULED, never completed). PRD §3.3 states "the authorization falls straight through to `CLOSED`" when no documentation is in AWAITED/RECEIVED/OVERDUE, and §2.5's auto-close sweep runs in the same clock set. The test asserts `CLOSED` (the unique PRD answer) while keeping all cascade assertions (appointment CANCELLED, extension DENIED/AUTH_CANCELLED, reserved 0, remaining 2).
2. **Timestamp formatting** (`test_04` ×2, `test_08` ×1) — `authorized_at`/`deadline_at` are asserted by parsed-instant equality against the recipe's literal instant rather than raw string equality: PRD pins the instant ("stamped with the current logical clock", "plus a 15-day resubmission grace") but §2.4's three-fractional-digit rule applies only to `created_at`/`updated_at`, so string formatting is a two-reader design space.

### AST tag-audit output (verbatim)

```
expected executable: 73 (A=19, B=54); corner stubs not translated: 9
emitted tests: 73 over 73 unique tags
missing: 0  extra: 0  duplicate tags: 0
PRD quote sweep: 122 quoted spans, 0 missing
```

(Every docstring ends with exactly one `Design:` tag copied verbatim from the source YAML `name:`; every quoted PRD span survives a whitespace-normalized literal grep of PRD.md.)

### pytest collect-only output

```
73 tests collected in 0.30s
```

Zero collection errors, zero warnings. Run from the task dir with `PYTHONPATH=$PWD`; no server was started (collection-only, per stage scope). Interface discipline held throughout: 201 on creates via `validate_success(resp, 201)` or fixture `get_success_data`, per-instance `make_tpa_admin_headers/make_provider_rep_headers/make_veteran_headers` for every ownership-gated call, frozen constants/fixtures (`setup_episode*`, `make_documentation_overdue`, `record_urgent_visits_on_days`, `set_clock`) reused instead of re-implemented, and recipe literals (37.9/23.6 min, 15600/17550/198/4875c, 0.25 rate, 180/181 filing days) asserted as pre-computed.

Orchestrator re-verification (independent): own AST walk of test_suite vs both YAMLs — expected 73, emitted 73, unique 73, missing 0, extra 0, dups 0. Own `pytest --collect-only -q` run: 73 tests collected, 0 errors.

## Step 6: Generate implementation — 2026-10-02T09:15:00.000Z

All files written, compiled, and verified by four smoke runs. Final state is clean (no `__pycache__`, smoke scripts were in /tmp and are removed).

## Summary

**Implementation complete**: 40 endpoints, 12 entities, 32-error catalog, 3 cyclic state machines, logical clock with 3 ordered sweeps — all under `/home/ubuntu/github/CodingPRD/tasks/task_3465_community_care_referral_eligibility_standards_administrator_claims/workspace/implementation/`.

**Files written (line counts)**:
- requirements.txt (1), start.sh (10) — guarded pip install, `exec python3 app.py`, 0.0.0.0:$PORT
- constants.py (90) — every PRD numeric pinned
- errors.py (51) — full 32-id catalog + ApiError
- logical_clock.py (57) — 2026-09-01T00:00:00Z default, 3-fractional-digit Z rendering
- db.py (70) — dict stores, version=1 at create, touch() per mutation, insertion-seq tiebreak
- response.py (87) — exact envelope (meta/response_type/data; pagination fields in meta)
- middleware.py (41) — X-User-ID/X-User-Role stage 1-2 decorator + ownership helper
- validate.py (170) — stage 3 FK existence + stage 4 shape (bool-safe int checks)
- services.py (252) — haversine/drive-time, eligibility rule composition, ledger recompute, cascades, 3 sweeps, per-line claim pricing, copay tiers
- routes_network.py (137) — stations, TPAs, provider onboarding, credential-decision + decredential cascade
- routes_veterans.py (115) — veterans + OCC-guarded assessments with supersession
- routes_referrals.py (244) — authorizations + extension requests/decisions
- routes_appointments.py (218) — appointments + documentation + review loop
- routes_claims.py (221) — claims, adjudicate, resubmit, reverse-payment
- routes_urgent_rx.py (154) — urgent care + prescription fills
- routes_platform.py (24) — clock endpoint
- app.py (58) — blueprint registration, ApiError/404/405/500 envelope handlers

**Boot proof** (smoke boot log): `* Running on all addresses (0.0.0.0)` — clean startup on a dynamic port, killed by saved PID only.

**Smoke outputs (all passed)**:
- Missing headers → 400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` in the exact error envelope
- Clock set → `{"current_utc": "2026-09-01T00:00:00.000Z"}`; advance to 2026-11-05 correctly ran expiry sweep (auth ACTIVE→EXPIRED) then overdue sweep (doc AWAITED→OVERDUE, no suspension since auth already EXPIRED) in pinned order
- Station create 201 with full envelope; provider PENDING→CREDENTIALED 200
- Eligibility end-to-end: drive 91.3 min (urban, ~43.5 mi × 2.1), drive_failed true, eligible true; stale `expected_veteran_version` → 412 `ERR_STALE_VERSION`
- Claim adjudication: contract rate 12000 beats billed 15000 → paid 11700 (fee 300); buckets lifetime/current 11700/0; TPA adjudicated=1, rate 0.0
- Multi-line rounding: fees 500 + 250 (249.975 → half-up 250 per line) → 29249; reversal → buckets 29249/0/29251-corrected (lifetime 29249, current 0, reversed 29249)
- Urgent care: MID-band copays 1500/1500/1500/3000 across 4 visits, same-day → `ERR_SAME_DAY_URGENT_VISIT`, foreign veteran → `ERR_OWNERSHIP_MISMATCH`, Oct-1 FY reset → index 1, fy 2027
- TPA surveillance: exactly 5/5 denials → rate 1.0 → SUSPENDED at the 5th event; new claim → `ERR_TPA_SUSPENDED`; decredential cascade auto-denied a RECEIVED claim with `PROVIDER_DECREDENTIALED`
- Resubmit limit: count 1, 2 OK; third → `ERR_RESUBMISSION_LIMIT`
- Rx: both-ids → 404 (existence stage precedes exactly-one-of per pipeline), neither → 400, non-string id → 400 (found and fixed a TypeError-500 hole here), 15-day urgent-linked → `ERR_DAYS_SUPPLY_EXCEEDED`, controlled → `ERR_CONTROLLED_RX_NOT_ALLOWED`, re-decide → `ERR_INVALID_STATE`, appt-not-completed → `ERR_INVALID_STATE`, foreign provider → `ERR_OWNERSHIP_MISMATCH`

**Constants module**: `workspace/implementation/constants.py` — all values cross-checked against PRD prose (drive 30/60, wait 20/28, choice max 4, filing 180, doc 30+15, slot 60, timeliness 5, caps 12/12/365/180, Medicare 10000/18000, fee 0.025 per-line half-up, resubmit max 2, suspension ≥5 events AND rounded rate > 0.20, copays 0/1500→3000/3000→4500 with lower-tier max 3 and Oct-1 FY reset, Rx 14/90, R=3958.8 urban 1.4/40 rural 1.2/55, clock start 2026-09-01T00:00:00Z).

**Interpretations chosen** (PRD admitted more than one reading; consumed downstream):
1. `version` starts at 1; +1 per mutation including cascade-driven ones.
2. All timestamps (created_at/updated_at/meta timestamp included) read the logical clock, never wall clock; rendered with 3 fractional digits + Z; stored datetime strings compare lexicographically.
3. List sort: created_at ascending, insertion sequence as tiebreak.
4. Pagination out-of-range values clamped to [1,100]/[0,∞) (PRD names min/max but no error); non-integer limit/offset → ERR_INVALID_REQUEST.
5. Referral `authorized_visits` outside 1..12 / `duration_days` outside 1..365 → ERR_INVALID_REQUEST (catalog has no dedicated creation-cap error; ERR_EXTENSION_CAP exists only for extensions).
6. Extension asks below minimum (visits < 1, days < 0) → ERR_INVALID_REQUEST; above cap → ERR_EXTENSION_CAP.
7. No check that `assessment.veteran_id` equals the referral's `veteran_id` (PRD silent — no invented guard).
8. No ProviderRep ownership check on extension-request create (PRD stage-6 ownership list names only appointments/claims/documentation for ProviderRep).
9. No authorization-state gate on appointment create (PRD defines none; only window/visits/slot gates); AUTHORIZED→ACTIVE flips on any appointment creation while AUTHORIZED.
10. No ownership check on appointment cancel (PRD names none; scheduler-match applies to scheduling only).
11. Extension request under a non-parent authorization → 404 ERR_NOT_FOUND.
12. OCC (stage 5) evaluated before the PENDING state check (stage 7) on extension decide, per the PRD pipeline.
13. Claim resubmit ordering follows the PRD §2.8 pipeline (state → TPA → temporal → RESUBMISSION_LIMIT → referential → fiscal), not the scaffold state-machine's precondition listing order.
14. Resubmit clears `denial_reason`, resets `submitted_at`, leaves `paid_amount_cents` null.
15. `denial_reason` enum-validated whenever present; stored only on DENIED.
16. `note` (documentation submit) and `rejection_note` (review) are accepted and type-checked but not stored (entity has no such fields).
17. Review REJECT clears `content_ref` but preserves `submitted_at` (PRD names only content_ref as cleared).
18. DOCS_SUSPENDED restore clears `docs_suspension_return_state` to null; no EXHAUSTED/EXPIRED re-check on unsuspension (no PRD trigger).
19. Cascade version granularity: each mutated entity +1 per mutation event; system auto-denial of extensions does not bump the authorization version (scaffold attributes that bump to reviewer decisions only); TPA +1 per finalization event including a same-event suspension flip.
20. EXPIRED→CLOSED fall-through fires inline at expiry and is re-checked in sweep 3; EXHAUSTED→CLOSED at completion time can never fire because completion always creates an AWAITED doc (mechanical consequence).
21. Rx create: JSON null counts as absent for exactly-one-of; urgent-linked requests have no ownership check; a ProviderRep caller whose id matches no provider entity → ERR_NOT_FOUND (needed for the CREDENTIALED check).
22. Rx safety order: controlled-substance check before provider credentialing (PRD listing order).
23. Claim create stage-7 order: `ERR_REFERRAL_NOT_ACTIVE` before `ERR_TPA_SUSPENDED`.
24. Appointment create constraint order: `ERR_NO_VISITS_REMAINING` before `ERR_APPOINTMENT_SLOT_CONFLICT` (same stage, unspecified).
25. Timely filing and window checks use whole calendar dates; (today − service_date) ≤ 180 inclusive; future service dates pass timely filing (PRD silent).
26. `drive_standard_failed` compares the rounded 1-decimal stored `drive_time_minutes` against the standard (strict >).
27. `denial_rate` stored as float of the 4-decimal half-up Decimal; suspension compares the rounded rate > 0.20.
28. Veteran coordinate ranges are not validated (PRD gives lat/lon ranges only for care stations; station ranges are enforced at shape stage).
29. `contract_rates` values must be non-bool ints; no sign check (PRD silent).
30. Headers empty after whitespace strip → ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
31. `reason` / `denial_reason` / `refusal_reason` must be present, string, non-empty.
32. Body FK fields with non-string types defer to stage 4 (400), not stage 3 (404).
33. GET appointment documentation returns an array with pagination meta despite no documented pagination inputs.
34. Trailing slashes tolerated; unmatched routes → envelope 404; wrong method → envelope 400.

Orchestrator verification: 17 files (1999 lines) compile clean; boot smoke on dynamic port 56609 OK (clock endpoint answered with proper envelope; killed saved PID 1416955 only); clock field name `to_iso8601` consistent across PRD/helpers/scaffold/impl; constants diff impl-vs-helpers clean (34 common names, 4 cosmetic literal-style diffs only).

## Step 7: Test-fix iteration loop — 2026-10-02T13:00:00.000Z

Clean sweep: all 8 rounds at 73/73. Exiting with the summary.

## Summary

**Iterations run:** 2 (baseline sweep → fix → verification sweep; all 8 rounds green on the second).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:** none — the fixture itself was correct; its docstring even documents the trap ("pass an explicit authorized_visits == num_appointments to reach EXHAUSTED").

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_3465_community_care_referral_eligibility_standards_administrator_claims/test_suite/test_10_claims_validations.py` — `test_claim_state_error_beats_untimely_filing`: changed the setup call from `authorized_visits=1` to `authorized_visits=2` (with an explanatory comment). The test cancels the authorization to reach CANCELLED, but with 1-of-1 visits completed the episode was EXHAUSTED, and PRD §3.3 permits cancel only from `AUTHORIZED`, `ACTIVE`, or `DOCS_SUSPENDED` ("from any other status the attempt is rejected with `ERR_INVALID_STATE`"). The setup was issuing a PRD-illegal request, so the PRD-faithful implementation correctly 409'd before the assertion under test was ever reached. One spare visit keeps the auth ACTIVE, the cancel is legal, and the intended check — PRD §2.8/§3.7 pipeline order, where the state gate (`ERR_REFERRAL_NOT_ACTIVE`) masks the later timely-filing failure (`ERR_UNTIMELY_FILED`) — now executes as designed.

**Fixes applied to `implementation/`:** none — the implementation was verified PRD-faithful on both relevant rules (cancel source-state gate in §3.3; claim-pipeline stage order state-before-timely-filing in `routes_claims.py` lines 69-80).

**Feedback note for unit-test-generator:** the failing instance was `Difficulty/priority_pair_validation_conflict/claim_state_error_beats_untimely_filing` — a priority-pair design whose setup must reach state X (CANCELLED) via a transition whose own source-state gate (§3.3) forbids X's predecessor chosen by the generator (EXHAUSTED). Setup-state reachability against the target transition's source gate is a general constraint the generator should check when the design requires "be in state S" and the only path to S has its own preconditions.

Orchestrator verification: all 8 `results.{1..8}.json` present and parse, each `passed 73/73 failed 0`; `authorized_visits=2` fix confirmed at test_10_claims_validations.py:32; zero impl/test source files newer than the sweep results (no post-sweep edits).

## Step 8: Finalize PRD — 2026-10-02T13:05:00.000Z

Byte-identical confirmed. **Zero-edit outcome.**

## Summary

**Line counts:** PRD.md = 324 lines, PRD_FINALIZED.md = 324 lines, 0% delta — **zero-edit outcome** (verified with `diff -q`: byte-identical).

**Changes:** none.

### Why zero-edit is correct

The `<step_7_diff>` contains exactly one item: a `test_suite/` setup fix in `test_10_claims_validations.py::test_claim_state_error_beats_untimely_filing` (`authorized_visits=1` → `2`). No implementation changes, no helper fixes, no deletions. My evidence reads confirm it is a pure test-setup bug — every behavior it touches is already uniquely pinned by PRD.md, and `implementation/` is PRD-faithful on each:

**(a) EXHAUSTED transition on zero remaining visits**
- PRD: §3.3 (line 180) — "whenever a completion or cancellation recompute drives `remaining_visits` to exactly zero, an `ACTIVE` authorization becomes `EXHAUSTED`"; §3.5 (line 200) repeats it.
- Impl: `routes_appointments.py:128-134` (completion settles ledger, calls `maybe_exhaust`); `services.py:98-103` (`maybe_exhaust`: ACTIVE + `remaining_visits == 0` → EXHAUSTED); `services.py:61-63` (ledger recompute matches §2.10). With `authorized_visits=1` and one completion, remaining hits 0 → EXHAUSTED (the auto-created AWAITED doc blocks immediate CLOSE).

**(b) Cancel source-state gate**
- PRD: §3.3 (line 182) — cancel permitted only from `AUTHORIZED`, `ACTIVE`, or `DOCS_SUSPENDED`; "from any other status the attempt is rejected with `ERR_INVALID_STATE`".
- Impl: `routes_referrals.py:149-151` rejects exactly that complement set with `ERR_INVALID_STATE`. The original test's cancel against an EXHAUSTED auth was a PRD-illegal request, correctly 409'd in setup before the assertion under test.

**(c) Claim-pipeline order: state gate masks timely filing**
- PRD: §2.8 (lines 117-130) — fixed pipeline, first failing stage masks later ones; stage 7 = `ERR_REFERRAL_NOT_ACTIVE` state gate (claim creation requires `ACTIVE`/`EXPIRED`/`EXHAUSTED`/`CLOSED`); stage 9 = `ERR_UNTIMELY_FILED`. §3.7 (line 218) — 180-day inclusive window.
- Impl: `routes_claims.py:69-71` (state gate runs first; CANCELLED → `ERR_REFERRAL_NOT_ACTIVE`) precedes line 80's temporal check (`routes_claims.py:40-44`, `lag > TIMELY_FILING_DAYS`); `constants.py:33` pins `TIMELY_FILING_DAYS = 180`.

**(d) Fixture side**: `test_helpers/fixtures.py:447-461` docstring documents the trap — the default `authorized_visits = num_appointments + 1` exists precisely so completion does not exhaust; passing `== num_appointments` reaches EXHAUSTED. The test overrode the safe default against the fixture's own documentation.

No PRD silence and no PRD/impl mismatch exists at the Step 7 site, so `workspace/PRD_FINALIZED.md` is a byte-identical copy of PRD.md.

Orchestrator verification: `diff -q workspace/PRD.md workspace/PRD_FINALIZED.md` → byte-identical confirmed independently; both 324 lines.

## Step 9: PRD completeness scan — 2026-10-02T13:15:00.000Z

All changes verified. The diff shows 23 revised paragraphs plus one inserted sentence pair, all matching the intended pins.

## Summary

**Source vs output:** `PRD_FINALIZED.md` (identical to `PRD.md`) 324 lines / 56,666 chars → `PRD_COMPLETED.md` 326 lines / 59,999 chars (**+2 lines, +3,333 chars**). Output at `/home/ubuntu/github/CodingPRD/tasks/task_3465_community_care_referral_eligibility_standards_administrator_claims/workspace/PRD_COMPLETED.md`.

**Counts:** ambiguity-pins **23**, mismatch-revisions **0**, impl-bugs-reported **2**, dead-checks-found **1**.

**Changes (all insert/revise of ambiguity to match impl):**
- §2.1 — revise — ambiguity — header rejection now covers all-whitespace values — `middleware.py:18`
- §2.2 — insert — ambiguity — undefined path → `ERR_NOT_FOUND` 404; unsupported method on a defined path → `ERR_INVALID_REQUEST` 400 — `app.py:40-46`
- §2.3 — revise — ambiguity — out-of-range `limit`/`offset` clamped (not rejected); non-integer pagination or integer-typed filters (`priority_group`, `fiscal_year`) → `ERR_INVALID_REQUEST`; equality filters; no-match → empty page; same-instant ties ordered by insertion sequence — `response.py:52-68`, `db.py:60-66`, `validate.py:162-170`
- §2.4 — revise — ambiguity — `version` begins at 1 on creation — `db.py:42`
- §2.5 — revise — ambiguity — clock may be set to any valid instant, including earlier than current — `routes_platform.py:18-19`
- §2.8 stage 4 — revise — ambiguity — body fields beyond those an endpoint names are ignored — `validate.py:14-22`
- §2.9 — revise — ambiguity — existing-but-wrong-parent nested identifier → `ERR_NOT_FOUND` — `routes_referrals.py:208-209`
- §3.1 — revise — ambiguity — station coordinate-range / negative-wait violations → `ERR_INVALID_REQUEST` — `routes_network.py:25-30`
- §3.1 — revise — ambiguity — malformed `contract_rates` (non-object or non-int values) → `ERR_INVALID_REQUEST` — `routes_network.py:74-82`
- §3.2 — revise — ambiguity — `priority_group` outside 1..8 → `ERR_INVALID_REQUEST` — `routes_veterans.py:25-26`
- §3.2 — revise — ambiguity — dangling `home_station_id` at assessment creation → `ERR_NOT_FOUND` — `routes_veterans.py:72-74`
- §3.4 — revise — ambiguity — extension asks below the minimums (visits < 1, days < 0) → `ERR_INVALID_REQUEST` 400 — `routes_referrals.py:169-172`
- §3.4 — revise — ambiguity — `denial_reason` supplied with an `APPROVED` decision is ignored — `routes_referrals.py:216-217,231`
- §3.5 — revise — ambiguity — stored `scheduled_start` normalized to UTC with 3 fractional digits — `routes_appointments.py:72`
- §3.5 — revise — ambiguity — within stage 10, no-visits-remaining precedes slot-conflict; appointment creation applies **no lifecycle state gate** to the authorization (a booking on `PENDING_REVIEW` leaves status unchanged) — `routes_appointments.py:51-59,82-83`
- §3.5 — revise — ambiguity — appointment cancellation carries no network-ownership check — `routes_appointments.py:138-151`
- §3.6 — revise — ambiguity — submission `note` accepted but not stored — `routes_appointments.py:169`
- §3.6 — revise — ambiguity — `rejection_note` accepted but not stored; `submitted_at` retained across a rejection — `routes_appointments.py:204,211-217`
- §3.7 — revise — ambiguity — negative timely-filing lag (future `service_date`) files on time — `routes_claims.py:40-41`
- §3.7 — revise — ambiguity — `denial_reason` on a `PAID` decision is enum-validated but ignored — `routes_claims.py:124,137-145`
- §3.7 — revise — ambiguity — resubmission clears `denial_reason` to null — `routes_claims.py:196`
- §3.8 — revise — ambiguity — `facility_name` recorded as supplied, no registry validation — `routes_urgent_rx.py:22,42`
- §3.8 — revise — ambiguity — explicit null link counts as absent; no lower bound on `days_supply`; unknown ProviderRep `X-User-ID` → `ERR_NOT_FOUND`; urgent-care-linked requests carry no ownership gate — `routes_urgent_rx.py:75-99`

## IMPL BUGS
1. `implementation/routes_referrals.py:214-215` — PRD §3.4: "supplying a `decision` of `APPROVED` or `DENIED`, an optional `denial_reason`" — impl makes `denial_reason` **required non-empty** on DENIED extension decisions (`v.req_nonempty_str` → `ERR_INVALID_REQUEST` when omitted), contradicting "optional" (contrast §3.7/§3.8 which explicitly say "must carry" where required) — minimal impl fix: use `v.opt_str` for extension `denial_reason`. PRD_COMPLETED.md keeps "optional". Untested by the suite, so the fix is sweep-safe.
2. `implementation/routes_appointments.py:63` + `logical_clock.py:36-39` — PRD §2.2: "All error API responses (4xx status codes) follow this standard envelope" and §5 maps `ERR_INVALID_REQUEST` to 400 — scheduling on a `PENDING_REVIEW` authorization whose `scheduling_responsibility` is `TPA` dereferences `authorized_at=None` via `parse_dt`, raising an uncaught `ValueError` that surfaces as HTTP 500 with `error_id` `ERR_INVALID_REQUEST` (`app.py:48-50`) — minimal impl fix: guard the null anchor (reject with a catalogued 4xx such as `ERR_INVALID_STATE`) so no request yields an uncatalogued 500. Reachable: create auth under a `TPA`-scheduling provider, owner TPA posts an in-window appointment before authorize.

## DEAD CHECKS
- `implementation/validate.py:153` — `opt_object()` defined but never called from any route (the only unused helper; not a PRD-mandated validation, no behavior gap). All 33 catalogued error_ids have at least one raising site, and every guarded field (`docs_suspension_return_state`, TPA denial counters, provider payment buckets) has a verified writer — no PRD-required check is defined-but-never-called or called-but-never-defined.

## Step 9b: Orchestrator impl-defect fix + re-sweep — 2026-10-02T13:30:00.000Z

Step 9 named 2 impl bugs; per the impl-defect terminal sequence the orchestrator adjudicated both against source, fixed the implementation toward the PRD, and re-swept. PRD_COMPLETED.md kept the PRD's rules intact for both items (impl moved toward PRD, not the reverse).

**Adjudication:**
- Bug 1 CONFIRMED — PRD.md:188 says extension decisions carry "an optional `denial_reason`" (contrast PRD.md:220 for claims: "a denial must carry a `denial_reason`"); impl used `v.req_nonempty_str` on DENIED extension decisions. Genuine impl contradiction of an unambiguous PRD sentence.
- Bug 2 CONFIRMED — `routes_appointments.py` TPA-anchor branch called `parse_dt(auth["authorized_at"])` with `authorized_at=None` on PENDING_REVIEW auths (PRD.md:176 keeps it null until authorize; PRD §3.5 + PRD_COMPLETED pin no lifecycle state gate on booking, so the path is PRD-legal); `parse_dt(None)` raises ValueError → uncaught → HTTP 500. PRD was silent on the anchor for this combination — residual ambiguity, not a rule to preserve.

**Impl fixes applied (orchestrator, targeted):**
1. `workspace/implementation/routes_referrals.py` (decide_extension) — `denial_reason = v.opt_str(b, "denial_reason")` unconditionally; APPROVED still accepts-but-ignores, DENIED now honors PRD's "optional". 
2. `workspace/implementation/routes_appointments.py` (create_appointment TPA anchor) — when `authorized_at` is null (PENDING_REVIEW), the AUTHORIZED_AT lag falls back to the booking's `requested_date`; anchor label stays scheduler-determined per PRD §3.5. No state gate added.

**PRD_COMPLETED.md edit (ambiguity-pin for bug 2 only):** §3.5 — inserted one sentence inline: "When the administrator schedules against an episode still in `PENDING_REVIEW`, `authorized_at` is still null, so the `AUTHORIZED_AT` lag is measured from the booking's `requested_date` until authorization stamps the anchor." Bug 1 required no PRD edit (PRD_COMPLETED already keeps "optional"). Verified counts: PRD.md 324 / PRD_FINALIZED.md 324 / PRD_COMPLETED.md 326 lines (Step 9's +2-line edits; my bug-2 sentence was inserted inline into an existing paragraph, so it added no line); FINALIZED→COMPLETED diff is 46 changed lines total.

**Verification:**
- `python3 -m py_compile routes_referrals.py routes_appointments.py` → OK.
- Full 8-round parallel re-sweep (orchestrator-run, same flags as Step 7): all 8 rounds `passed 73/73 failed 0` — no regression from the fixes.
- Live smoke of both fixed paths (untested by the suite) against a dynamic-port server (pid saved, killed exactly): (a) TPA-scheduled booking on PENDING_REVIEW → 201 SCHEDULED, anchor AUTHORIZED_AT, within_standard computed — no 500; (b) extension DENIED without denial_reason → 200 DENIED, denial_reason null.
- Dead check `opt_object` (validate.py:153): unused non-PRD-mandated helper, no behavior gap — left in place deliberately (removal is cosmetic, and touching validate.py post-sweep would invalidate the sweep evidence).
