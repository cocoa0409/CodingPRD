# Worklog — task_3459_food_facility_registration_import_alert_detention

## Step 1: Create Task Directory — 2026-10-02T07:48:00.000Z

Task directory pre-allocated by the invocation args: `./tasks/task_3459_food_facility_registration_import_alert_detention/` with `workspace/` inside. Verified present; no new index computed and no other task_* directory created.

## Step 2: Generate Scaffold — 2026-10-02T09:40:00.000Z

All checks pass. The scaffold package is complete and verified.

## Report

**Task**: `task_3459_food_facility_registration_import_alert_detention` — FDA human-foods facility registration & import-alert detention, generated at substantially-harder-than-expert difficulty (density-first: deep cross-coupling, not entity sprawl; endpoint count deliberately capped at the ≤40 impl-gen safety bound).

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3459_food_facility_registration_import_alert_detention/`):
- `SCAFFOLD.yaml` — §1.0–§1.7: 10 entities, 8 state machines, 10 calculations, 12 ordered validation priorities, 40 endpoints, 41 errors, 7 roles, 2 OCC concurrency rules. Flat topology under `/registry`, `segregation_of_duties` role model (alert creator cannot adjudicate its petitions), logical clock with mandatory default `2026-09-01T00:00:00Z` living outside the api prefix at `POST /_clock/set_current_utc`, whose advance atomically runs the ops checkpoint (biennial expiry sweep + detention-deadline auto-refusal).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 18 instances, 2 per rule, all differentiated per §0.5 (e.g., rule 2 spans modes (a) screening-score threshold routing and (b) per-lot-then-sum bond rounding with the divergence literal 33 vs 32; rule 4 pairs a depth-3 inspection-refusal cascade with a depth-2 alert-activation cascade; rule 5 pairs state×temporal and temporal×constraint).
- `SCAFFOLD_CORNER_DESIGN.yaml` — 49 entries (44 active + 5 `excluded_because` stubs) across all nine claim-extraction sections; every one of the 41 error codes is exercised by at least one instance across the two design files.

**Lint verdict (verbatim)**:
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(40 endpoints, 10 entities, 18 §1.8 + 44 §1.9 instances, 473 calls scanned.)

**Key design decisions and traps engineered in**:
- All date/formula literals were computed and verified in Python before being pinned in asserts (expiry 2026-09-01+730d = 2028-08-31; window-open renewal → 2030-08-31; grace renewal → 2030-09-01; VESSEL 8h/720h boundaries; bond 33/15100/1533; screening scores 30/38/40/46/93; recall pcts 55.0/89.0/90.0).
- Replay fixes caught during authoring: the detention-deadline error would have been dead code (sweep fired at the same threshold) — fixed with a 24h sweep grace so `ERR_DETENTION_RESPONSE_DEADLINE_PASSED` is reachable; cascade link 3 originally targeted CONSUMED (terminal) notices — retargeted to the facility's CONFIRMED unconsumed notices; the streak boundary instance initially let two same-scope alerts coexist (ambiguous `detained_under_alert_id` and a contaminated 5-streak) — restructured so A1 is lifted before A2 is created, and a deterministic multi-match selector rule was pinned in §1.2; standing thresholds were validated against the ratio math (first-refusal ratio 1.0 would REVOKE immediately, so progression tests stage releases before refusals).
- Verified beyond lint: grounds references resolve, instance names unique across both design files, enum-value closure, forbidden-vocabulary scan clean, OCC hard constraints (both write endpoints take `expected_*_version` and bump parent version).

Orchestrator verification: all three files exist, parse as YAML, SCAFFOLD.yaml carries neither design key, design files carry their single top-level keys (1293 + 1097 + 2115 lines).

## Step 3: Copy Shared Files — 2026-10-02T09:41:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3459_food_facility_registration_import_alert_detention/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-10-02T10:04:00.000Z

PRD generated and all three hard contracts pass. Output: `/home/ubuntu/github/CodingPRD/tasks/task_3459_food_facility_registration_import_alert_detention/workspace/PRD.md` (343 lines). Neither design index file was opened at any point.

**Document structure** (domain-derived, not template-copied):
- §1 Introduction (2 paragraphs: program scope, then compliance/clock/segregation concerns)
- §2 (9 subsections): 2.1 RBAC with per-role identity prose (FacilityOwner→Facility, Importer→ImporterFirm entity-backed; 5 opaque roles); 2.2 verbatim fixed block (byte-identical, `"data": { }` empty); 2.3 Pagination; 2.4 Logical Clock + ops checkpoint (startup default `2026-09-01T00:00:00Z`, forward-only, both strict sweep comparisons, `current_utc`/`expired_facility_ids`/`auto_refused_entry_ids`); 2.5 Common properties (incl. `FFR-NNNNNN` from `FFR-000001`); 2.6 Validation precedence — all 12 priority tiers as a first-failure-wins ordered list with the three "beats" consequences called out; 2.7 OCC (exactly 2 rules); 2.8 Units/currency/rounding (both conservation invariants, round-half-up, rational ratios); 2.9 Left-to-right existence + all ten 404s + `ERR_LAB_NOT_FOUND`
- §3 (9 subsections): facility lifecycle → standing/labs → prior notice → screening → sampling → detention resolution → alerts/petitions → inspections → recalls. All constants embedded (730d, 90/30d window, 8/4/4/2h leads, 720h max, halved amendment minimums, weights 8/12 vs 16/24, terms 35/10/15, threshold 40, cap 100, bond 0.10 + 1500¢/day with the 33-vs-32 rounding-order example, streak ≥ 3 with trailing-run semantics and `created_at` tie-break, CLASS_I 100.0/100.0, 95.0, 90.0, 240h deadline + 24h strict sweep grace). Worked screening contrast 38-vs-46 included.
- §4: 40 endpoints, 4 columns only, including unprefixed `/_clock/set_current_utc`; 201-vs-200 rule paragraph. §5: 41 errors, 2 columns only, no triggers.

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields (+common id/created_at/updated_at/version): 40 required, 40 present, 0 missing
- endpoints[].request_body/input: 41 required, 41 present, 0 missing
- endpoints[].query_params + path_params: 14 required, 14 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 12 tiers checked, 12 expressed in §2.6 ordered prose (+ per-rule triggers scattered in §3), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (renew → expected_facility_version, petition filing → expected_import_alert_version, both ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: all 8 machines' transitions expressed (incl. REGISTERED→REGISTERED renewal self-loop, SUSPENDED absorbing, screen-time RELEASE self-execution note, earliest-created-alert detention rule, no-re-detention), 0 missing
- calculations[]: 10 checked, 10 fully expressed with pinned evaluation orders, 0 missing
- validations[] conditions: all matchable to their error_id in §2/§3 prose; all 41 error IDs appear in §2/§3
- endpoints[].side_effects / applies_to: 40 checked, 40 expressed (cascades: alert create, alert lift, inspection-refusal 3-link, VIOLATIVE for-cause, standing recompute per terminal disposition incl. sweep)
- entities[].fields[] structured content: defaults (GOOD_STANDING, NONE, PENDING, 0-counters, "" reason, null-until-computed fields) and system-copied fields all reconstructible from prose
- sibling-branch symmetry: BASE/HISTORY_WEIGHTED, initial/amendment windows, APPROVE/DENY, RECONDITIONED/REFUSED outcomes, FIRM/COUNTRY_PRODUCT scopes — all rendered at equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 561
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

One repair was made post-draft: renewal's ownership check (`X-User-ID` == facility `id`) was implicit; added an explicit sentence to §3.1. A mechanical-check false alarm (fenced JSON blocks shifting backtick pairing) was diagnosed and the extractor fixed by stripping code fences before tokenization.

## Step 5a: Generate Test Helpers — 2026-10-02T10:32:00.000Z

Stage 5a is complete and verified. All files are under `/home/ubuntu/github/CodingPRD/tasks/task_3459_food_facility_registration_import_alert_detention/test_helpers/`.

## Files written

- **types.py** — 7-role `UserRole` enum, all status enums (Facility/PriorNotice/ImportEntry parallel dims/SampleAnalysis/ImportAlert/AlertPetition/Inspection/Recall, plus risk class, transport mode, scope type), `TERMINAL_DISPOSITIONS`, and 10 entity TypedDicts (all entities carry `id`/`created_at`/`updated_at`/`version`).
- **constants.py** — every constant derived from PRD.md verbatim: clock default `2026-09-01T00:00:00Z`, lead windows 8/4/4/2 + 720 max + amendment ceil-halving (4/2/2/1), screening constants (base 10/30/60, caps 5/3, weights 8/12 vs 16/24, terms 35/10/15, threshold 40, cap 100), bond rate 0.10 + storage 1500/day, standing thresholds (2/4 refusals, exact-rational 1/5 and 1/2 ratios), `REQUIRED_STREAK=3`, recall thresholds (CLASS_I exactly 100.0/100.0, II ≥ 95.0, III ≥ 90.0), registration 730d + window [−90d, +30d], detention 240h + 24h sweep grace, `FFR-000001` sequence, pagination 10/1/100/0. Plus pure PRD-math helpers (`compute_screening_score`, `compute_bond_amount_cents` with pinned per-lot round-half-up, `compute_standing`, `compute_effectiveness_pct`, `compute_consignee_contact_pct`, `amendment_min_lead_hours`, `iso_add_days/hours`) and derived instants (expiry `2028-08-31`, window open `2028-06-02`, grace end `2028-09-30`, detention deadline `2026-09-11`).
- **api_errors.py** — all 41 catalogued error IDs with PRD §5 statuses (1×401, 3×403, 10×404, 1×400, 13×409, 12×422, 1×412), registered with the framework via `set_error_http_status_map`.
- **api_client.py** — `ApiClient(GenericApiClient)` with exactly 40 endpoint methods: 39 under `/registry` plus the **unprefixed** `POST /_clock/set_current_utc`; `api_client` singleton at module level.
- **test_users.py** — `TEST_USERS` (11 entries: two opaque ids each for EntryReviewer/ComplianceOfficer/FieldInspector/RecallCoordinator to support segregation-of-duties and inspector-overlap scenarios; entity-backed entries documented as fallbacks only) + `make_*_headers` builders for all 7 roles, with the entity-backed pair requiring the real entity id.
- **factories.py** — payload factories for all 10 creatable resources and every action payload (renew OCC, amend with inherited-field omission, sample order/result, reconditioning lots/outcome, alert with scope-field omission, petition OCC, evidence, adjudicate, inspection create/complete, recall create/classify/effectiveness, clock), with auto-sequenced unique `ufi`/`account_code`/`lab_code`.
- **assertions.py** — per-entity structural assertions (UUID, ISO-8601, enum membership, nullable system fields) + domain invariants `assert_entry_units_conserved`, `assert_recall_quantities_conserved`, `assert_registration_number`.
- **fixtures.py** — ~45 helpers across all five tiers, all identity-threaded (`make_facility_owner_headers(facility["id"])` / `make_importer_headers(importer["id"])` on every ownership-gated call): clock set returning sweep ids; reads including list-based `find_petition`/`find_inspection` (no single-GET endpoints exist for those); OCC-aware `renew_facility`/`file_petition` (fresh version read by default, explicit stale value passable); facility state builders (EXPIRED via clock sweep, SUSPENDED via inspection refusal, violation_count via inspection completion); screening paths (LOW/STANDARD→RELEASE, HIGH→SAMPLE), for-cause detention via VIOLATIVE sample, alert-cascade detention, bond request, CO-only detained release, refuse/export/reconditioning-outcome; `build_compliant_streak`, `setup_alert_with_compliant_streak`, `setup_lifted_alert` (CO_ONE creates, CO_TWO adjudicates — SoD-correct); `setup_importer_with_history` with the REVOKED-blocks-further-filings caveat documented; full recall lifecycle; batch entry creation for pagination.
- **__init__.py** — barrel export with the shadowing pattern explicit and documented: `test_helpers.api_client` is the singleton (so `import test_helpers.api_client as ac` binds the instance by design), the module stays reachable as `test_helpers.api_client_module`, the class as `test_helpers.ApiClient`.

## Verification output

```
IMPORT CHECK: OK          (the exact required python3 -c import line)
COMPILE: OK               (py_compile over all 9 files)
ac binds: ApiClient | is singleton: True
endpoint methods: 40
ALL SYMBOL + MATH CHECKS OK
```

Math helpers were validated against the design indices' literal expectations: bond 33 for 3×{1,105} at day 0 and 15100 at 10 detained days; screening 46 HISTORY_WEIGHTED/SAMPLE and the inclusive 40-boundary SAMPLE; standing PROBATION(2/5)→REVOKED(3/6); effectiveness 55.0; amendment minima 4/2/2/1; ISO arithmetic 730d → `2028-08-31T00:00:00Z` and +240h → `2026-09-11T00:00:00Z`.

No `test_suite/` files were written — that is Stage 5b's job.

Orchestrator verification: all 9 helper files present on disk; independent `python3 -c` import check of all modules passes. Orchestrator-measured queue sizes from the design YAMLs: 18 active difficulty instances (0 stubs) + 44 active corner instances (5 stubs) = 62 total; instance names verified unique across both files.

## Step 5b: Generate Test Suite — 2026-10-02T11:05:00.000Z

All checks green. Stage 5b complete.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3459_food_facility_registration_import_alert_detention/test_suite/`):
- `conftest.py` — session-scoped `api` fixture + per-role header fixtures
- `test_01_facility_registration_and_renewal.py` (8 tests)
- `test_02_importer_standing_and_laboratories.py` (3)
- `test_03_prior_notices.py` (7)
- `test_04_entry_screening_and_sampling.py` (9)
- `test_05_detention_and_resolution.py` (7)
- `test_06_import_alerts_and_petitions.py` (11)
- `test_07_inspections.py` (5)
- `test_08_recalls.py` (4)
- `test_09_security_errors_and_ops_checkpoint.py` (7)

**Test counts: 61 functions — queue A: 18/18, queue B: 43/44.** test_helpers/ was treated as frozen; no edits.

**AST audit (real `ast` parse, docstring Design tag vs both indices):** 0 malformed tags, 0 extra tags, 0 stub leaks. Exactly one missing instance:
- `Corner/entities/prior_notice_create_with_status_field_returns_invalid_request` — **SKIPPED (PRD-first, unique-derivability failure)**. The instance asserts that smuggling the system field `status` into a create payload is rejected `400 ERR_INVALID_REQUEST`. PRD §2.6 category 12 names only "missing required fields, invalid enum values, range violations, inconsistent alert scope fields" — rejection of unknown/system-writer payload fields is never stated anywhere in PRD.md, so a faithful PRD-only implementer could accept-and-ignore the extra field and fail this test. Not weakened, not emitted.

**Clock/date literals:** every design literal was verified against PRD-pinned math (expiry 2026-09-01+730d = 2028-08-31T00:00:00Z; window open 2028-06-02; grace end 2028-09-30; deadline = detained_at+240h = 2026-09-11T00:00:00Z; sweep at deadline+24h strict; bond 33/15100/1533; scores 30/40/46/93; recall pcts 55.0/89.0/90.0). All clock advances are forward-only from the 2026-09-01T00:00:00Z default. **No clock literal needed re-derivation.**

**One non-clock literal re-derived:** in `Corner/errors/unknown_ids_return_entity_specific_not_found`, the recipe's importer-404 sub-call passes `as_user_id: ${imp_id}` (a real importer) with an unknown body `importer_id`. Per PRD §2.6's fixed order, ownership (category 3) precedes existence (category 4), so that call as written would uniquely return `ERR_OWNERSHIP_VIOLATION`, not the asserted `ERR_IMPORTER_NOT_FOUND`. I set `X-User-ID` equal to the unknown importer id (ownership passes, existence then fails) so the catalogued 404 is the uniquely-derived outcome.

**Citation sweep:** all 98 quoted docstring passages (≥25 chars) verified verbatim against workspace/PRD.md under whitespace normalization (0 failures).

**pytest collection:** `61 tests collected in 0.31s`, 0 errors.

Orchestrator re-verification (independent AST tag audit + pytest collect): expected 62 tags (18 A + 44 B), found 61, 0 dupes, 0 extra, exactly 1 missing — the documented skip. 61 tests collected, 0 errors. Spot-check of the skip: PRD §2.6 category 12 lists only "missing required fields, invalid enum values, range violations, inconsistent alert scope fields" — no unknown/system-field rejection clause exists anywhere in PRD.md, so the skip is legitimate (doc-generator Zero-Silence feedback: unknown-field rejection behavior is PRD-silent).

## Step 6: Generate Implementation — 2026-10-02T12:00:00.000Z

Implementation complete and smoke-tested. All state lives in-memory, store starts empty, no seeding.

## Files written (`workspace/implementation/`)

- `start.sh` — guarded pip install (`import flask` check), `exec python3 app.py`, `PORT` env (default 10000), binds `0.0.0.0`
- `requirements.txt` — flask>=2.0
- `app.py` — Flask wiring, blueprint registration, ApiError/404/405/500 envelope handlers; boots only under `__main__`
- `db.py` — in-memory stores, logical clock (default `2026-09-01T00:00:00Z`, forward-only), ISO parse/format, FFR sequence, `touch()` version/updated_at bumps
- `errors.py` — full 39-id catalog with exact HTTP statuses
- `envelope.py` — `meta`/`response_type`/`data` envelope, error body, pagination meta, JSON body reader
- `auth.py` — tiers 1–2: `X-User-ID`/`X-User-Role` presence + seven roles → 401; per-endpoint role list → 403
- `pagination.py` — limit default 10, min 1, cap 100; offset default 0; invalid → 400
- `serialize.py` — per-entity whitelisted serializers (datetime → canonical logical format, Decimal pcts → float)
- `services.py` — all calculations + detention lifecycle + alert matching + streak + ops checkpoint
- `routes_clock.py` — **`POST /_clock/set_current_utc` (unprefixed)**, runs expiry sweep then detention sweep (both strict `<`)
- `routes_facilities.py` — register/get/renew (ownership-on-path before existence, window, OCC 412)
- `routes_importers.py` — importer + laboratory onboarding with uniqueness
- `routes_notices.py` — file/get/list/amend (supersede + inherit, amendment half-lead variant)
- `routes_entries.py` — entry create/screen/sample/result/release/reconditioning/export/refuse + samples list
- `routes_alerts.py` — alert create (cascade detain), petitions (file/submit-evidence/adjudicate, SoD, lift cascade)
- `routes_inspections.py` — schedule (FOREIGN + half-open overlap), complete, refuse-entry 3-link cascade
- `routes_recalls.py` — initiate/classify/record-effectiveness/terminate with Decimal half-up pcts

## Smoke test (dynamic port 36751, booted via `bash start.sh`, killed exact PID 1276161/1276158)

Verified end-to-end, all matched expectations: 401/403 auth tiers; facility create → `FFR-000001`, expires +730d; duplicate UFI/account_code → 409; PN too-late → 422; ownership → 403; amend VESSEL+6h accepted (amendment min 4h) with old notice SUPERSEDED; entry on superseded → 409; LOW+amendment screen → score 20 RELEASE; HIGH → SAMPLE 60; release-before-compliant → 409; sample past-date → 422 beating capacity; capacity 3+3>5 → 409; bad lab → 404; COMPLIANT → release; FIRM alert cascade detains PENDING entry (deadline now+240h); EntryReviewer release of DETAINED → 403, officer → 200; screen under ACTIVE alert → DETAIN with score 45 stored; petition stale OCC → 412, filing bumps alert version 1→2, creator adjudication → 403 SoD, other officer APPROVE → streak 3 → alert LIFTED with entry cascade-released; sweep grace strict (deadline+24h exactly → not refused; +1s → auto-refused with violation+standing); clock backward → 400; PROBATION recompute observed via HISTORY_WEIGHTED 49 + `probation_adjustment_applied:15`; pagination meta correct; expiry strict at `expires_at` (still REGISTERED, +1s → EXPIRED v+1); renew 403/412/window-closed/EXPIRED→REGISTERED/REGISTERED-extend branches all correct; bond 3×round_half_up(10.5)=**33** (pinned per-lot order); outcome mismatch → 422; failed units → REFUSED + violation; inspection DOMESTIC → 422, overlap → 409, adjacency OK, refusal cascade (SUSPENDED + for-cause detention + COMPROMISED); SUSPENDED renew → `ERR_FACILITY_NOT_RENEWABLE`; CLASS_I gate blocks/unblocks; effectiveness 50.0→terminate 422, 100.0/100.0→TERMINATED; deadline-passed within grace → 422 on export/reconditioning while still DETAINED.

## Coverage checklist

**8 state machines**: Facility (sweep/renew/suspend-cascade) — `services.run_checkpoint`, `routes_facilities.renew_facility`, `routes_inspections.refuse_entry_inspection`; PriorNotice (CONFIRMED→SUPERSEDED/CONSUMED/COMPROMISED) — `routes_notices.amend_prior_notice`, `routes_entries.create_entry`, cascade link 3; ImportEntry (parallel review × disposition) — `routes_entries.*` + `services.detain_entry/release_detained/release_pending/refuse_entry`; SampleAnalysis — `record_result`; ImportAlert (ACTIVE→LIFTED) — `adjudicate_petition`; AlertPetition (EVIDENCE_REVIEW→APPROVED/DENIED) — `submit_evidence`/`adjudicate_petition`; Inspection — `complete_inspection`/`refuse_entry_inspection`; Recall — `classify/record_effectiveness/terminate_recall`.

**10 calculations**: `prior_notice_window_check` → `services.check_notice_window` (minute-granularity floor, inclusive bounds, ceil-halved amendment); `entry_screening_score` → `services.screen_score` (caps, BASE/HISTORY_WEIGHTED, alert-forced DETAIN with score stored); `reconditioning_bond` → `services.compute_bond` (Decimal ROUND_HALF_UP per lot before sum, +1500¢/day floor); `importer_standing_recompute` → `services.apply_terminal_outcome` (exact rational `2*rc>=tec` / `5*rc>=tec`); `petition_compliance_streak` → `services.compliance_streak` (completed_at≥alert.created_at, completed_at/created_at ordering, trailing RELEASED/RECONDITIONED run); `recall_effectiveness` → `routes_recalls._pct/_recompute_recall` (Decimal 1dp half-up, 0.0 on zero total) + thresholds in `terminate_recall`; `facility_registration_expiry` → create/`renew_facility`/`run_checkpoint`; `active_recall_gate` → `services.recall_gate_blocks`; `entry_units_conservation` → preserved in every `services` disposition helper; `recall_quantity_conservation` → `record_effectiveness` accounting gate.

**12 validation tiers**: 1–2 in `auth.require_roles`; 3 ownership per-endpoint (path-id compare for renew before existence; loaded-field compare otherwise); 4 existence left-to-right incl. body `lab_code` (lab-existence checked before entry state per scaffold priority 4<5 — note PRD §3.5's narrative lists state first while claiming §2.6 order; I followed the self-consistent §2.6/scaffold numbering); 5 state guards; 6 registration + recall gates; 7 temporal windows; 8 filer-in-scope / FOREIGN-target; 9 uniqueness/overlap/capacity/SoD/unit-accounting/effectiveness; 10 OCC (`expected_facility_version`, `expected_import_alert_version` → 412, missing → 400); 11 approve-only sufficiency; 12 request shape last (higher tiers win over malformed bodies).

**Boot contract**: 40 routes registered exactly (`python3 -c "import app"` verified package graph; static route disabled), clock endpoint unprefixed, no seeding, fresh-process boot clean.

Orchestrator verification: all 18 files present; independent `import app` shows exactly 40 routes — 39 under `/registry`, clock unprefixed at `/_clock/set_current_utc`. Noted for Step 7/8: subagent flagged a PRD §3.5 narrative that lists state-before-existence while claiming §2.6 order (scaffold tier numbering puts existence 4 before state 5); impl followed §2.6 tier numbering — adjudicate if a test exercises it.

## Step 7: Test-Fix Loop — 2026-10-02T12:20:00.000Z

Two 8-round parallel sweeps (`--isolation per-test-server`, all rounds to completion).

**Iteration 1:** 60/61 in all 8 rounds. Union of failures = 1 deterministic test:
`test_entry_requires_confirmed_prior_notice` — `NameError: name 'get_prior_notice' is not defined`
at test_04 line 414 (asserts PRD §3.3 notice flips to `CONSUMED` on entry creation).

- Diagnosis: STEP 1a/1b pass (PRD §3.3 verbatim-covers the CONSUMED transition; uniquely derived).
  STEP 2: test faithful, but test_04's import list omitted `get_prior_notice`
  (helper exists in test_helpers/fixtures.py:87 and is correctly imported by test_03/07/09).
- Fix (test_suite): added `get_prior_notice` to the `from test_helpers import (...)` list in
  test_suite/test_04_entry_screening_and_sampling.py. No helper/impl edits.
- Pyflakes sweep of test_suite + test_helpers after the fix: zero undefined-name (F821) findings;
  only pre-existing unused-import warnings.

**Iteration 2:** 61/61 passed in all 8 rounds. Clean.

**§2.6-vs-§3.5 precedence adjudication:** never exercised by a failing test. The only failure was
the missing import. Implementation keeps following §2.6's explicit tier numbering (existence tier 4
before state tier 5); no test asserted the §3.5 narrative order, so no adjudication action needed.

**Deletions:** none. **Implementation edits:** none.

All 8 `results.{1..8}.json` files remain on disk in workspace/implementation/ showing passed == total == 61.

Orchestrator verification: all 8 results files independently read — each passed=61, total=61, failed=0. The claimed fix confirmed in source (`get_prior_notice` imported at test_04:21, used at :415); pytest collects 61 tests, 0 errors. Step 7 tally: 2 iterations, 0 deletions, 0 test_helpers fixes, 1 test_suite fix (import omission), 0 implementation fixes.

## Step 8: Finalize PRD — 2026-10-02T12:34:00.000Z

Done. The diff is exactly one line — the §3.5 clause reorder.

## Summary on exit

**Line counts / delta:** PRD.md 343 lines, PRD_FINALIZED.md 343 lines — 0% delta; exactly one line modified (line 193).

**Changes (one edit):**
- §3.5 — revise — reordered the "Three guards apply, in §2.6's order" enumeration so the lab-existence guard (`ERR_LAB_NOT_FOUND`, §2.6 tier 4) is listed before the entry-state guard (`ERR_ENTRY_INVALID_STATE`, tier 5), making the invoked §2.6 ordering literally true — `workspace/implementation/routes_entries.py:172-180`.

**Per-item investigation log (step_7_diff item 1 — no edit):**
- `test_suite/test_04_entry_screening_and_sampling.py` import fix: verified the file now imports `get_prior_notice` (line 21) and the call site (line 415) asserts the notice flips to `CONSUMED` after entry creation; the same test asserts entry creation against a `SUPERSEDED` notice fails with `ERR_PN_NOT_CONFIRMED` (lines 405-409). Both assertions quote PRD §3.3 (line 173: terminal non-CONFIRMED states rejected with `ERR_PN_NOT_CONFIRMED`) and §3.4 (line 177: "Filing flips the notice to `CONSUMED`") verbatim. Implementation matches: `routes_entries.py:50-51` raises `ERR_PN_NOT_CONFIRMED` for any non-CONFIRMED notice, line 96 sets `CONSUMED`; the amend guard (`routes_notices.py:144-145`) is consistent. Failure was a deterministic NameError from a missing import (test_03/07/09 import the same helper and passed). Pure test artifact bug, no PRD implication — no edit.

**Per-edit pre-edit search log (the one edit):**
- (a) Subject: validation-guard ordering for `POST /registry/entries/{id}/record-sample` — the only sample-ordering operation.
- (b) Impl paths enumerated and read/grepped: `routes_entries.py:159-215` (`record_sample`, read in full — actual check sequence: entry path-404 → lab-404 → entry-state → date → capacity → shape); grep of all `ERR_LAB_NOT_FOUND`/`ERR_ENTRY_INVALID_STATE`/`ERR_SAMPLE_DATE_PAST`/`ERR_LAB_CAPACITY_EXCEEDED` sites across `implementation/*.py` (`errors.py` is a status catalogue only; every other `ERR_ENTRY_INVALID_STATE` site — screen, record-result, release, reconditioning, export, refuse — is on an endpoint with no lab-existence check and is untouched by the edit); `services.py` (no sample-ordering logic); related SampleAnalysis paths `list_entry_samples` and `record_result` confirmed unaffected (§3.5¶2 already matches impl order). Test-side: the only `ERR_LAB_NOT_FOUND` test (`test_09:212-217`) uses a freshly screened SAMPLE-state entry, so it does not discriminate orderings — consistent with step_7_diff's "unchallenged" note.
- (c) Wording adjustment: pure clause swap, no content added or removed. The trailing "— a temporal failure that is reported even when capacity is also exhausted" remains attached to the date clause (impl checks date at lines 182-184 before capacity at 186-194, preserving §2.6 line 117's emphasis). Post-edit, "Three guards apply, in §2.6's order" is literally accurate (tier 4 → 5 → 7). §2.6's tier list, §2.9, the §4 routing table, and the §5 catalogue are order-neutral or now accurately summarized — no enumerated path is mis-described.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly line 193 changed — the reported clause reorder (lab-existence before entry-state), nothing else. Zero-edit outcome not taken; the single edit directly resolves the §2.6-vs-§3.5 self-inconsistency flagged at Step 6 hand-off.

## Step 9: PRD Completeness Scan — 2026-10-02T12:47:00.000Z

The diff is exactly as planned — all 13 edit sites applied cleanly, inline, with no new sections. Final verification of the file state is confirmed by the diff output above (343 → 346 lines, 57037 → 61123 chars).

## Summary

**Source vs output:** `/home/ubuntu/github/CodingPRD/tasks/task_3459_food_facility_registration_import_alert_detention/workspace/PRD_FINALIZED.md` (343 lines / 57037 chars) → `.../workspace/PRD_COMPLETED.md` (346 lines / 61123 chars). Char-delta: **+4086**.

**Counts:** ambiguity-pins **14**, mismatch-revisions **4**, impl-bugs-reported **1**.

**Changes (one bullet per change):**
- §2.1 — insert — ambiguity — blank/whitespace-only `X-User-ID` counts as a missing header (401) — auth.py:30-33
- §2.2 — insert — ambiguity — undefined paths / unsupported methods / unexpected failures reject in the error envelope with `ERR_INVALID_REQUEST` at the routing layer's own 404/405/500, exempted from the §5 status mapping — app.py:42-54
- §2.3 — revise — ambiguity — `limit`/`offset` validation pinned: non-integer → `ERR_INVALID_REQUEST`, `limit` < 1 → 400, `limit` > 100 clamped to 100, `offset` < 0 → 400, empty string treated as omitted — pagination.py:15-38
- §2.3 — revise — ambiguity — equal creation timestamps ordered by server creation sequence, never by `id` — db.py:76-78
- §2.3 — revise — ambiguity — `has_more` is true exactly when `offset` + items-returned < `total_count` — envelope.py:22-29
- §2.3 — insert — ambiguity — exact-match conjunctive filter sets enumerated per list endpoint (prior-notices: facility_id/importer_id/status/parent_pn_id; entries: +prior_notice_id/detained_under_alert_id/disposition_status/review_status; alerts: facility_id/status/scope_type; recalls: facility_id/classification/status/product_code) — routes_notices.py:113-130, routes_entries.py:107-125, routes_alerts.py:98-116, routes_recalls.py:97-108
- §2.4 — revise — ambiguity — malformed `current_utc` also → `ERR_INVALID_REQUEST`; the two response id-lists are in resource creation order — routes_clock.py:22-35, services.py:282-296
- §2.5 — revise — ambiguity — `version` starts at 1 at creation — db.py:58-67
- §2.5 — revise — mismatch — business timestamps render `YYYY-MM-DDTHH:MM:SSZ` with no fractional part at whole-second instants (3 digits when millisecond-aligned, 6 otherwise), not always "three fractional digits"; contradicting passage: §2.4's own rendering of the clock start as `2026-09-01T00:00:00Z` — db.py:102-113
- §2.6 — revise — mismatch — the fixed tier order (ownership before existence) is unimplementable where ownership is read from a persisted target; pinned: request-evaluable comparisons (renewal's path id, filing's body `importer_id`) run at tier 3, resource-field comparisons run after the target's 404 — routes_facilities.py:77-84, routes_notices.py:57-59,137-142, routes_entries.py:42-47,288-291,362-364, routes_alerts.py:192-196, routes_inspections.py:92-96,120-124
- §2.6 — revise — mismatch — "the active-recall safety gate beats referential and temporal failures" is unimplementable (the gate's inputs come from the resolved notice; entry creation has no timing checks); pinned: gate evaluated after the notice resolves and after the registration gate, outranking request shape — routes_entries.py:42-63
- §2.6 tier 4 + §2.9 — revise — mismatch — existence-check scope was stated as a closed set (path ids + lab_code) but impl and §3 narratives check more; pinned: body `facility_id`/`importer_id` on filing and `prior_notice_id` on entry creation are checked, alert/recall body `facility_id` are not, and an unresolvable inspection `facility_id` fails with `ERR_INSPECTION_REQUIRES_FOREIGN_FACILITY` (422), not 404 — routes_notices.py:60-66, routes_entries.py:42-44, routes_alerts.py:43-60, routes_recalls.py:56-67, routes_inspections.py:31-37
- §3.3 — insert — ambiguity — no facility-kind restriction at prior-notice filing (a `DOMESTIC` facility may be named; only the registration gate applies) — routes_notices.py:51-99 (no kind check exists)
- §3.3 — revise — ambiguity — amendments do not re-evaluate the registration or importer-standing gates — routes_notices.py:133-162
- §3.5 — insert — ambiguity — a result-recorded analysis still occupies its laboratory-day capacity — routes_entries.py:187-194
- §3.6 — insert — ambiguity — a repeated reconditioning request on a still-detained entry recomputes and overwrites `bond_amount_cents` — routes_entries.py:285-313
- §3.7 — revise — ambiguity — streak candidate double-ties (equal `created_at`) broken by server creation sequence, still never by `id` — services.py:268
- §3.8 — revise — ambiguity — `findings_violation_count` is null until completion — routes_inspections.py:69, serialize.py:171

## IMPL BUGS

- **routes_entries.py:128-156 (`screen_entry`), via services.py:155-165 (`detain_entry`)** — PRD §3.6: "an entry already `DETAINED` is never re-detained by a second matching alert"; §2.8: "`units_held` + `units_released` + `units_refused` + `units_exported` + `units_destroyed` always equals the entry's `declared_units`"; §3.6: "Releasing from `DETAINED` is reserved to a `ComplianceOfficer`: an `EntryReviewer` attempting it is rejected with `ERR_FORBIDDEN` (HTTP 403)" — The screen path applies disposition effects without checking `disposition_status`. Cascades (§3.7 alert placement, §3.8 link 2) legitimately detain entries "whatever its review_status", leaving reachable `PENDING_SCREENING` + `DETAINED` entries that pass the screen guard. Three corrupt outcomes: (a) an ACTIVE-alert match re-runs `detain_entry` on the already-detained entry — resetting `detained_at`/`response_deadline_at` and double-incrementing `open_detention_count` (permanently leaked, since any single resolution decrements once); (b) with no alert match and score < 40, the RELEASE branch sets `units_released = declared_units` while `units_held` already equals `declared_units` (conservation broken at 2× declared), lets an EntryReviewer release a detained entry, and never decrements `open_detention_count`; (c) if the holding alert was lifted first, the lift cascade already released the entry and recomputed standing, and the RELEASE branch at screening then runs `apply_terminal_outcome` a second time for the same entry (double `terminal_entry_count`). — Suggested fix: in `screen_entry`, store score/variant/probation/decision and set `review_status = SCREENED` unconditionally, but apply the disposition effect only when `disposition_status == "PENDING"`: skip `detain_entry` when already `DETAINED`, and self-execute RELEASE only from `PENDING`.

**Dead-code check:** ran it. All 41 catalog errors are reachable; every PRD-stated validation has reachable impl code, and I grepped the writers of every guard's input field (`open_detention_count`, `violation_count`, `standing`, `disposition_status`, `review_status`, `bond_amount_cents`, `response_deadline_at`, recall `classification`/`status`, alert `status`, petition `status`, inspection `status`, sample `status`, notice `status`, `registration_status`). No defined-but-uncalled or shadowed-unsatisfiable checks found. The only guard-writer pathology is the screen re-application reported above.

**Module read confirmations (all end-to-end):**
- implementation/app.py — read end-to-end (blueprint wiring; 404/405/500 handlers).
- implementation/db.py — read end-to-end (clock, stores, seq counters, `new_common`, `fmt_dt`/`parse_dt`/`parse_date`).
- implementation/errors.py — read end-to-end (all 41 ids and statuses verified against §5 — exact match).
- implementation/envelope.py — read end-to-end (success/list/error envelopes, `has_more`).
- implementation/auth.py — read end-to-end (tiers 1-2).
- implementation/pagination.py — read end-to-end.
- implementation/serialize.py — read end-to-end (all 10 serializers cross-checked against §2.5/§3 field narratives).
- implementation/services.py — read end-to-end (all 10 calculations: notice window, screening score, standing recompute, bond, recall gate, streak, checkpoint sweeps — constants and rounding verified against PRD including the 3×105¢=33¢ worked example).
- implementation/routes_clock.py — read end-to-end.
- implementation/routes_facilities.py — read end-to-end (register/get/renew + OCC).
- implementation/routes_importers.py — read end-to-end (importer + laboratory onboarding).
- implementation/routes_notices.py — read end-to-end (file/get/list/amend).
- implementation/routes_entries.py — read end-to-end (all 12 entry/sample endpoints; every guard order cross-checked against §2.6).
- implementation/routes_alerts.py — read end-to-end (alert placement + cascade, petition file/list/evidence/adjudicate, SoD, sufficiency).
- implementation/routes_inspections.py — read end-to-end (schedule/complete/refuse-entry + three-link cascade).
- implementation/routes_recalls.py — read end-to-end (initiate/classify/record-effectiveness/terminate; Decimal half-up percentages and exact 100.0 thresholds verified).

All 40 PRD endpoints exist with matching methods, paths, roles, and 201/200 conventions; the 41-error catalog matches `errors.py` exactly.

Orchestrator verification: PRD_COMPLETED.md present, 346 lines / 61123 chars (+4086 vs FINALIZED), differs from PRD_FINALIZED.md (not a mid-flight no-op).

## Step 9b: Impl-Bug Fix + Re-sweep — 2026-10-02T12:56:00.000Z

Orchestrator adjudicated the single IMPL BUG by reading source directly:
- CONFIRMED at routes_entries.py:128-156 (`screen_entry`): the review guard (line 133) checks only `review_status`; the disposition effects fired with no `disposition_status` check. All other `detain_entry` call sites verified correctly guarded (alert cascade routes_alerts.py:84-88 and inspection cascade routes_inspections.py:141-143 skip non-PENDING; VIOLATIVE sample routes_entries.py:245-249 checks PENDING) — the screen path was the sole defective site, matching Step 9's report exactly.
- PRD warrants: §3.6 "an entry already `DETAINED` is never re-detained" (line 204 of PRD_COMPLETED), §2.8 unit conservation, §3.6 CO-only release from DETAINED, §3.4 "In every case the entry leaves screening with `review_status` `SCREENED`" (review dimension unconditional).
- Fix applied (orchestrator, `implementation/routes_entries.py`): DETAIN branch calls `services.detain_entry` only when `disposition_status == "PENDING"` (else just `db.touch`); RELEASE branch self-executes (disposition flip, units, completed_at, standing recompute) only from PENDING; review-dimension writes (score/variant/probation/decision/`review_status=SCREENED`) remain unconditional per §3.4 parallel-dims rule. No test or helper touched.
- `py_compile` + `import app` clean.
- Full 8-round parallel sweep re-run by the orchestrator (`--isolation per-test-server`, all rounds to completion): **61/61 passed in all 8 rounds, 0 failed**. All 8 `results.{1..8}.json` regenerated on disk showing passed == total == 61.
