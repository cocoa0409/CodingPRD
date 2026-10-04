# Worklog — task_3470_federal_records_accessioning_declassification_review_research_access

## Step 1: Create task directory — 2026-10-02T10:55:00.000Z

Task directory was pre-allocated per command args: `tasks/task_3470_federal_records_accessioning_declassification_review_research_access/` with empty `workspace/` inside. Verified existence; no new index computed, no other task_* directory created.

## Step 2: Generate scaffold — 2026-10-02T11:xx (subagent a7ed98931cec49548)

All three artifacts are complete and verified. Final summary:

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_3470_federal_records_accessioning_declassification_review_research_access/SCAFFOLD.yaml` — 1662 lines (§1.0–§1.7; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_3470_federal_records_accessioning_declassification_review_research_access/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1296 lines (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_3470_federal_records_accessioning_declassification_review_research_access/SCAFFOLD_CORNER_DESIGN.yaml` — 2904 lines (single key `scaffold_corner_design`)

## SCAFFOLD.yaml counts

- **Entities: 11** — Agency, RecordsSchedule, Transfer, Collection, DeclassReview, EquityReferral, ResearcherRegistration, PullRequest, ReproductionRequest, FoiaRequest, PresidentialRestriction (flat topology, FK-linked)
- **State machines: 11** — incl. cyclic FOIA appeal-remand loop, cyclic schedule return-resubmit loop, transfer DEFICIENT self-loop retry, Collection parallel dimensions (processing_status × digitization_status × derived restriction_posture)
- **Calculations: 18** — incl. dual-variant reproduction fee (rounding-order pinned: 25 ACADEMIC rush pages = 2360 vs 2359 alt; verified by code) and dual-variant digitization priority (107 demand-weighted vs 183 age-weighted)
- **Validations: 17** (ordered, incl. OCC at priority 6b and researcher-state at 7b)
- **Endpoints: 58** (57 business under `/records` + `POST /_clock/set_current_utc` with the mandated 2026-09-01T00:00:00Z startup default)
- **Errors: 65** (all cross-referenced from §1.2/§1.4/§1.5)
- **Roles: 12** (segregation-of-duties model; RecordsOfficer/AgencyLiaison entity-backed by Agency, Researcher entity-backed by ResearcherRegistration)
- **Concurrency rules: 1** (OCC `expected_collection_version` on review creation → 412)

## Design index counts

- **Difficulty design: 18 instances** — exactly 2 per rule × 9 rules, all non-stub; every assert literal (fees, priorities, ages, dates) computed and code-verified
- **Corner design: 69 instances — 58 non-stub + 11 `excluded_because:` stubs** (each stub cites a real difficulty instance)

## Verification performed

- `scaffold_lint.py`: **VERDICT: clean lint** (1019 calls scanned; two initial violations found and fixed — a `$.data.status` capture on Collection and Transfer's `collection_id` FK reverse-reachability)
- Custom audits all clean: instance-name uniqueness across both files, grounds resolution against §1.1–§1.7 (this caught and fixed two genuinely missing error codes: `ERR_SYSTEMATIC_REVIEW_PREMATURE`, `ERR_COOLING_PERIOD_ACTIVE`), `${var}` placeholder closure, forbidden-vocabulary scan, error-catalog cross-refs, endpoint-role refs
- Replay caught and fixed a real determinism hole: the queue tie-break instance now separates the two accessions by one logical second so `created_at ASC` is decidable

One caution for downstream steps: 58 endpoints exceeds the ~40 threshold flagged in memory as breaking impl-gen unless Step 6's prompt pre-constrains it (one file per message, per-domain modules, no-truncation, self-smoke-test) — recommend applying that constraint when this task goes through the pipeline.

Orchestrator verification: all three files exist (1662/1296/2904 lines), all parse as valid YAML, SCAFFOLD.yaml top-level keys contain no design keys, api_prefix `/records`, entity list matches this task's federal-records domain.

## Step 3: Copy shared files — 2026-10-02T12:29:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes). No subagent.

## Step 4: Generate PRD — 2026-10-02T12:xx (subagent ac12889a804206251)

All contracts pass. The PRD is complete and shipped.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3470_federal_records_accessioning_declassification_review_research_access/workspace/PRD.md` — 393 lines.

**Section list:**
- §1 Introduction (3 paragraphs: statutory pipeline, three structural commitments, mount/consistency)
- §2 Global Specifications: 2.1 RBAC (12 roles, all `identity:` fields translated), 2.2 Response Structure (byte-identical verbatim block — verified), 2.3 Pagination, 2.4 Logical Clock (startup default `2026-09-01T00:00:00Z`, no wall-clock fallback, lazy expiry), 2.5 Common Resource Properties, 2.6 Request Adjudication Order (full 17-rung priority ladder), 2.7 OCC, 2.8 Restriction Posture & Posture-Flip Cascade, 2.9 Anniversary Arithmetic, 2.10 Precision & Rounding
- §3 Business Logic (9 subsections, lifecycle-ordered): 3.1 schedules, 3.2 transfers, 3.3 accession, 3.4 processing/digitization, 3.5 declassification/referrals, 3.6 presidential restrictions, 3.7 registration/pulls, 3.8 reproduction/fees, 3.9 FOIA
- §4 Endpoint Definitions (58 rows, 4 columns) — §5 Error Code Catalogue (65 rows, 2 columns)

**Scaffold coverage confirmed:** 11/11 entities, 11/11 state machines (43 transitions, all 44 state strings in prose), 18/18 calculations (formulas in precise prose with worked examples 2360¢ and 107 pts, boundary inclusivity/exclusivity stated per gate), 15/15 validation priorities (rendered as the ordered §2.6 ladder plus endpoint-specific sub-orders), 58/58 endpoints, 65/65 errors, 12/12 roles.

**Hard Contract Reports:**
```
Field coverage check:
- entities[].fields: 86 required, 86 present, 0 missing
- endpoints[].request_body: 51 required, 51 present, 0 missing
- endpoints[].query_params: 12 required, 12 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 17 ladder rungs checked, 17 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (open-review write + expected_collection_version + ERR_STALE_COLLECTION_VERSION/412 all named), 0 missing
- state_machines[].transitions: 43 checked, 43 fully expressed, 0 missing
- calculations[]: 18 checked, 18 fully expressed, 0 missing
- validations[] conditions: 15 priorities checked, all matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 58 checked, 58 expressed, 0 missing
- entities[].fields[] structured content: 86 checked, 86 reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (FOIA adjudicate/appeal branches, metadata submit branches, restriction categories, affiliations, formats, standards, classification levels, review types), 8 with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 613
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Note: the audit's naive backtick pairing initially false-positived because the §2.2 fenced JSON blocks unbalance naive pairing; stripping fenced blocks before extraction fixed the measurement (document itself was correct).

Orchestrator spot-check: PRD.md is 392 lines by wc -l, 26 `##` headings, 65 unique ERR_ tokens, and contains the `/records` mount sentence, the `2026-09-01T00:00:00Z` startup default, and the OCC `expected_collection_version` clause.

## Step 5a: Generate test helpers — 2026-10-02T13:xx (subagent a359ca1eb4c367052)

Stage 5a is complete and verified. All nine helper files are written, compile clean, and import clean.

## Files written (all under `tasks/task_3470_.../test_helpers/`)

| File | Lines |
|---|---|
| `__init__.py` | 243 |
| `types.py` | 337 |
| `api_client.py` | 217 |
| `api_errors.py` | 161 |
| `assertions.py` | 292 |
| `factories.py` | 372 |
| `constants.py` | 163 |
| `test_users.py` | 93 |
| `fixtures.py` | 677 |

No `test_suite/` was created. No wall-clock calls anywhere (the only `datetime.now` hit is a docstring saying it's never consulted).

## Verification results

- **Import smoke test** (`PYTHONPATH=. python3 -c "import test_helpers.api_client, ..."`): OK, zero ImportError/NameError. `py_compile` on all 9 files: OK.
- **Clock endpoint unprefixed**: `constants.py:14` — `CLOCK_PATH = "/_clock/set_current_utc"`; `api_client.py:33` — `set_clock` posts to `CLOCK_PATH` directly (`return self.post(CLOCK_PATH, json={"to_iso8601": to_iso8601}, headers=headers)`), while all 57 business methods build paths from `API_PREFIX = "/records"`.
- **Error catalog**: all 65 PRD §5 errors extracted programmatically from PRD.md and diffed against `HTTP_STATUS_CODES` — exact match including the three unusual statuses (ERR_REPRO_NOT_PAID=402, ERR_STALE_COLLECTION_VERSION=412, ERR_UNIT_RANGE_INVALID=400). Registered with `set_error_http_status_map`.
- **Semantic spot-checks against PRD worked examples all pass**: fee 25pg ACADEMIC rush = 2360 (not the 2359 variant), 45pg = 3635, tier boundaries 1600/1650/5600/5625, 25/40/120/200pg JOURNALIST = 1850/2600/6100/8100; backlog SECRET/25y = 265; digitization priority 60/50/125/72 and the PRD's 107-point worked example; age gate 24 vs 25 at the anniversary; date arithmetic (card +2y → 2028-09-01, referral +21d → 2026-09-22, cooling +30d → 2026-10-01, Feb 29 → Feb 28 non-leap).

## Role-header builders (test_users.py)

- `make_records_officer_headers(agency_id)` / `make_agency_liaison_headers(agency_id)` / `make_researcher_headers(researcher_id)` — entity-backed per-instance builders (mandatory for ownership-gated calls)
- `make_headers(user_id, role)` — arbitrary pairing for cross-wiring probes
- `TEST_USERS` dict: admin, anonymous, appraiser, appraiser_2, processing_archivist, declass_reviewer, chief_archivist, research_room_staff, foia_officer, foia_officer_2, foia_appeals_officer + fallback constants for the three entity-backed roles. Segregation-of-duties identities are distinct: `arch-ap-1` vs `arch-chief-1` (appraise/decide), `foia-1` vs `foia-ap-1` (adjudicate/decide-appeal), with `arch-ap-2`/`foia-2` for re-appraisal and re-adjudication flows.

## Factory functions (factories.py)

Payload builders: `agency_payload`, `schedule_payload`, `appraise_payload`, `decide_schedule_payload`, `transfer_payload` (auto-pairs PHYSICAL/EAD_2002+linear_feet vs ELECTRONIC/PREMIS_3_0+checksum_manifest), `submit_metadata_payload`, `accession_payload`, `description_payload`, `declass_review_payload(collection_id, review_type, expected_collection_version, ...)` (OCC-carrying), `referrals_payload`, `complete_review_payload`, `respond_referral_payload`, `researcher_payload`, `pull_request_payload`, `reproduction_payload` (rush omitted when None), `pay_payload`, `foia_request_payload`, `adjudicate_payload`, `appeal_payload`, `decide_appeal_payload`, `restriction_payload`, `designate_payload`, `clock_payload`. Date helpers (all clock-anchored, never wall-clock): `parse_instant`, `format_instant`, `add_days`, `add_hours`, `add_seconds`, `add_years_anniversary` (Feb 29 → Feb 28). Defaults derive from the startup clock: cutoff `2001-03-15` (age exactly 25, lag 20 elapsed), visit `2026-09-10`, presidential cutoff `2009-01-20`/lag 12. `metadata_elements_for(standard)` holds the design-canonical complete element sets needed to land VALIDATED.

## Key fixtures (fixtures.py, 9 tiers)

Clock: `set_clock(to_iso8601=STARTUP)` (explicitly re-pins the startup default). Chain: `create_agency` → `create_approved_schedule` / `create_returned_schedule` → `create_validated_transfer` → `accession_transfer` → `create_collection_bundle`. Postured bundles: `setup_public_described_collection`, `setup_classified_collection(classification_default, described)`, `setup_presidential_collection`, `setup_queued_collection`, `setup_published_collection`. OCC pair: `current_collection_version(collection_id)` + `build_review_create_payload(...)` (fresh version read at call time). Reviews/referrals: `create_open_systematic_review`, `create_open_mdr`, `create_in_progress_mdr`, `create_referrals`, `respond_referral` (liaison headers from `referral["agency_id"]`), `complete_review`, `setup_in_progress_mdr_with_referral`. FOIA: `create_foia`, `adjudicate_foia`, `create_denied_foia`, `create_appealed_foia`, `decide_appeal`. Restrictions: `impose_restriction`, `designate_representative`, `notify_restriction`, `create_notified_restriction`, `release_restriction`. Pulls/repros: `create_pull`, `fulfill_pull`, `return_pull`, `create_reproduction`, `pay_reproduction`, `fulfill_reproduction`, `cancel_reproduction`, plus paid/fulfilled composites. Researchers: `register_researcher`, `activate_researcher`, `create_active_researcher` — all downstream ownership-gated calls thread `make_researcher_headers(registration["id"])`.

One judgment call to flag for Stage 5b: `validate_success` from the framework defaults to 200 — tests for create endpoints must pass `201` explicitly (the framework accepts the argument; nothing in helpers overrides it). The metadata required-element lists are not enumerated in PRD prose (§3.2 only says the system "holds ... a defined set"); they live in factories, not constants, and tests asserting specific `last_missing_elements` contents will need Stage-5b PRD-first adjudication.

Orchestrator spot-check: `CLOCK_PATH = "/_clock/set_current_utc"` confirmed at constants.py:14; no wall-clock calls outside docstrings; test_suite/ absent (Step 6 isolation preserved); helpers total 2555 lines.

## Step 5b: Generate test suite — 2026-10-02T14:xx (subagent aa03ea7f02cae80d0)

Stage 5b is complete. Final summary:

## Files written (21 files, 4101 lines)

All under `/home/ubuntu/github/CodingPRD/tasks/task_3470_federal_records_accessioning_declassification_review_research_access/test_suite/`:

| File | Lines | Tests |
|---|---|---|
| `conftest.py` | 70 | — (api fixture + 11 role-header fixtures) |
| `test_01_corner_entities.py` | 332 | 10 |
| `test_02_corner_schedule_transfer_lifecycle.py` | 215 | 5 (incl. consistency_model) |
| `test_03_corner_workflow_states.py` | 292 | 6 |
| `test_04_corner_calculations.py` | 143 | 3 |
| `test_05_corner_temporal_boundaries.py` | 242 | 6 |
| `test_06_corner_shape_and_ownership.py` | 211 | 5 |
| `test_07_corner_duties_and_uniqueness.py` | 251 | 6 |
| `test_08_corner_exemptions_and_guards.py` | 204 | 5 |
| `test_09_corner_envelope_and_not_found.py` | 156 | 5 |
| `test_10_corner_rbac.py` | 97 | 3 |
| `test_11_corner_cross_cutting.py` | 162 | 3 |
| `test_12_difficulty_fees.py` … `test_20_difficulty_invariants.py` | 116–249 each | 4 each (36 total) |

## AST tag audit (real `ast` parse vs `yaml.safe_load` of both indices)

- Queue expected: **76** (18 difficulty + 58 corner)
- Emitted test functions: **93**; distinct tags: **75**; untagged: **0**; dual-tagged: **0**
- **Matched: 75 · Unexpected: 0 · Missing: 1** (the deliberate skip below)
- All 18 difficulty instances carry exactly **2 tests** each; all 57 emitted corner instances ≥1 test.

## Skip list (1 instance, PRD-first filter)

- `Corner/state_machines/transfer_metadata_deficient_retry_loop` — SKIP. PRD §3.2 says only "The system holds, for each metadata standard, a defined set of required element names" and never enumerates them; the instance asserts specific `last_missing_elements` contents (`["provenance"]`, `["format","provenance"]`) and DEFICIENT/VALIDATED polarities of partial element lists, which a PRD-only implementer cannot uniquely derive (hand-off note #4's exact case). No weakening, no placeholder.

## Verification results

- `python3 -m py_compile test_suite/*.py` — OK.
- `pytest --collect-only` (PYTHONPATH=TASK_DIR) — **93 tests collected, 0 import errors**; package graph resolves.
- Citation verbatim check: **184 quoted spans (≥25 chars) across all docstrings, 0 failures** against PRD.md (whitespace-normalized). Three drafting errors were caught and fixed during this pass: PRD says "`schedule_id` before `agency_id`" (I had written "first, then"), one path-segment quote had an ellipsis, one cascade quote had joined two sentences with " ... ".

## Hand-off notes honored / adjudications

1. `validate_success(resp, 201)` passed explicitly on every create; 200 on actions/reads.
2. Clock only via `th.set_clock()` (unprefixed `/_clock/set_current_utc` handled by the frozen client).
3. All recipe date literals verified reachable from the 2026-09-01T00:00:00Z startup clock; two tests move the clock *backward* (systematic-age probes at 2026-03-14 and 2025-02-27/28) — PRD states no monotonicity constraint on the clock endpoint, so no literal needed re-derivation.
4. The metadata-element skip above is the only content skip.
5. No helper edits. One helper API note (not a bug): `fixtures.fulfill_and_return_pull(pull)` expects an already-PULLED pull despite its name; tests call `th.return_pull(th.fulfill_pull(pull))` explicitly instead.
6. Two borderline adjudications emitted rather than skipped, flagged for the record: `version == 1` at creation (PRD §2.5 says "starts at its initial value" without pinning the numeral — the conventional counter reading, matching all design literals) and `created_at == logical clock` (derived from §2.4 "No rule in this system reads wall-clock time" + §2.5). Both use `same_instant`/direct equality as the instances prescribe.

Orchestrator independent AST audit (re-run, not trusting subagent): expected 76 live; 93 test fns; 93 tags; 75 distinct; 0 untagged; matched 75; missing exactly `Corner/state_machines/transfer_metadata_deficient_retry_loop` (the declared skip); unexpected none; 18 tags carry 2 tests (difficulty pairs). Confirms subagent report exactly.

## Step 6: Generate implementation — 2026-10-02T15:xx (subagent a2eea9da309da3b7e)

Complete. Exactly 58 routes registered, static route removed, `start.sh` executable, both smoke-test PIDs confirmed dead (no stray servers).

## Summary

**Implementation location:** `/home/ubuntu/github/CodingPRD/tasks/task_3470_federal_records_accessioning_declassification_review_research_access/workspace/implementation/`

### Module list (line counts, endpoint counts)

| Module | Lines | Endpoints |
|---|---|---|
| `start.sh` | 10 | launcher (guarded `pip install`, `exec python3 app.py`, `$PORT`/0.0.0.0) |
| `requirements.txt` | 1 | flask>=3.0 |
| `app.py` | 70 | bootstrap, blueprint registration, ApiError/404/405/500 envelope handlers |
| `store.py` | 79 | in-memory store (11 dicts) + logical clock (default exactly `2026-09-01T00:00:00Z`), `ts3`/`tsc` timestamp formatters |
| `errors.py` | 93 | `ApiError` + full 65-error catalog with HTTP statuses (incl. `ERR_REPRO_NOT_PAID`=402, `ERR_STALE_COLLECTION_VERSION`=412, `ERR_UNIT_RANGE_INVALID`=400) |
| `constants.py` | 87 | every §1.3 constant + enum lists + `METADATA_REQUIRED` |
| `envelope.py` | 46 | `meta`/`response_type`/`data` envelope; pagination fields inside `meta` |
| `validation.py` | 189 | **the 17-rung adjudication ladder helpers** — rung 1 `get_auth`, rung 2 `require_role`, rung 5 `require_ownership`, shape validators, pagination; remaining rungs are invoked in explicit ladder order inside each route (annotated per call site) |
| `calcs.py` | 115 | §2.9 anniversary arithmetic (Feb 29→Feb 28), `records_age_years`, `reproduction_fee_cents` (Decimal, round-half-up per tier then rush), `digitization_priority`, `backlog_score`, `restriction_posture`, `declass_review_outcome` |
| `helpers.py` | 142 | entity 404 loaders, `bump` (version/updated_at), lazy EXPIRED, §2.8 `recompute_posture` + posture-flip FOIA cascade, §3.7 suspension cascade, QUEUED priority recompute |
| `routes_agencies.py` | 49 | 2 |
| `routes_schedules.py` | 182 | 6 |
| `routes_transfers.py` | 234 | 6 |
| `routes_collections.py` | 190 | 7 + `GET /records/digitization-queue` |
| `routes_reviews.py` | 343 | 6 declass-review + 3 equity-referral |
| `routes_researchers.py` | 77 | 3 |
| `routes_pulls.py` | 214 | 5 (full 5-step reservation sub-order: range→span→overlap→capacity→active-limit) |
| `routes_repros.py` | 169 | 6 |
| `routes_foia.py` | 204 | 6 |
| `routes_restrictions.py` | 150 | 6 |
| `routes_clock.py` | 38 | 1 — **`POST /_clock/set_current_utc`, unprefixed** |

Total: **58 endpoints** (verified via Flask url_map dump, exactly matching the scaffold table).

### Self-smoke-test (all executed against live booted servers)

Required probes: (a) `POST /_clock/set_current_utc` → 200 `{"current_utc":"2026-09-01T00:00:00Z"}`; (b) `POST /records/agencies` → 201 with envelope; (c) `GET /records/schedules` → 200 `response_type:"array"` with `limit/offset/total_count/has_more` in meta; (d) `GET /records/schedules/does-not-exist` → 404 `ERR_SCHEDULE_NOT_FOUND` envelope.

Extended probes all verified: SoD rejection (403 `ERR_SEGREGATION_OF_DUTIES`); OCC stale 412 then success (collection version 1→2 on review open); review complete → DECLASSIFIED, classification→NONE, posture→PUBLIC; fee math — 25pg ACADEMIC rush = **2360** (PRD's worked example), ACADEMIC non-rush = 1573, 150pg ACADEMIC = 5823; daily quota 200 OK / 201st → 409; card_expires_at = clock+2y anniversary; FOIA remand loop (DENIED→APPEALED→REMAND→IN_REVIEW→GRANTED, remand_count=1, foia_release_count=1); late return → SUSPENDED/LATE_RETURN with sibling REQUESTED pull + QUOTED repro CANCELLED; fresh reboot yields empty store + default clock; auth rungs 400/403/400.

### Confirmations

- **In-memory only**: plain dicts in `store.py`; no SQLite/files//tmp; fresh state per boot (verified by relaunch).
- **Clock unprefixed** at `/_clock/set_current_utc`; all other 57 endpoints under `/records`; never reads wall-clock (entity stamps use the logical clock; `created_at`/`updated_at`/`api_request_timestamp` use 3-fractional-digit logical-clock format).

### Flag for Step 7 reconciliation (unpinned constant)

PRD §3.2 references "a defined set of required element names" per metadata standard but neither PRD.md nor SCAFFOLD.yaml enumerates them. I defined them once in `constants.py` (`METADATA_REQUIRED`): EAD_2002 `[title, creator, date, extent, scope_content]`, MODS_3_7 `[title, creator, date, identifier, type_of_resource]`, PREMIS_3_0 `[object_identifier, object_category, preservation_level, original_name, format_name]`. Discovery-pattern tests (submit → read `last_missing_elements` → resubmit) pass with any set; if the design files pin different literals, this is the single place to align.

Orchestrator spot-check: 19 modules + start.sh + requirements.txt present; `routes_clock.py:19` registers `@bp.post("/_clock/set_current_utc")` unprefixed; store.py header confirms dicts-only; `METADATA_REQUIRED` at impl constants.py:82.

## Step 7: Run tests and iterate — 2026-10-02T14:55 (subagent a3c2c7537c07892d9)

All 8 rounds pass 93/93. Clean sweep achieved; the final `results.*.json` files remain on disk per the output contract.

## Summary

- **Iterations run:** 2 (each a full 8-round parallel sweep; union-of-failures diagnosis per round set).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:**
  1. `test_helpers/fixtures.py` — `submit_metadata()`: replaced the hardcoded element-set submission with the **discovery pattern** (submit factory's guess → if response is DEFICIENT, read `last_missing_elements` from the 200 response → resubmit with those names merged in). PRD §3.2 says only "the system holds, for each metadata standard, a defined set of required element names" without enumerating them, so the implementation's `METADATA_REQUIRED` (constants.py:82) is the alignment target; the old `METADATA_ELEMENTS_BY_STANDARD` sets in `factories.py:75-79` were the pre-diagnosed fixture bug masquerading as dozens of independent failures. Explicit `metadata_elements` arguments are still submitted verbatim so DEFICIENT probes behave as before.
  2. `test_helpers/fixtures.py` — `create_appealed_foia()`: added the `description_of_records` passthrough parameter (matching sibling `create_denied_foia`); `test_10_corner_rbac.py::test_foia_officer_cannot_decide_appeal` passed the kwarg and died with `TypeError` before exercising its RBAC assertion.

- **Fixes applied to `test_suite/`:** none — the failing test was faithful to PRD (§3.9 appeal-decision authority, §2.1 `ERR_FORBIDDEN_ROLE`); only its fixture's signature was broken.

- **Fixes applied to `implementation/`:** none — the implementation was PRD-faithful throughout; both bugs were in the test helper layer.

Final state: 8/8 rounds at 93 passed / 93 total / 0 failed / 0 errors.

Orchestrator verification: all 8 `results.{1..8}.json` present on disk, each independently parsed showing passed=93/total=93/failed=0; `find -newer results.1.json` over all source trees (implementation, test_suite, test_helpers, excluding __pycache__) returns empty — final sweep postdates the last edit (fixtures.py 1790952756 < results 1790952924).

## Step 8: Finalize PRD — 2026-10-02T15:xx (subagent acc3efb765920d6fc)

Done. The diff is exactly one in-place line revision; everything else is verbatim.

## Summary

**Line counts / delta:** PRD.md 392 lines, PRD_FINALIZED.md 392 lines — 0% line-count delta; one line (167) revised in place.

**Changes:**
- **§3.2 (Transfers: Initiation, Metadata Validation, Withdrawal) — revise** — pinned the previously unnamed per-standard required element sets inline after "a defined set of required element names": `EAD_2002` → title, creator, date, extent, scope_content; `MODS_3_7` → title, creator, date, identifier, type_of_resource; `PREMIS_3_0` → object_identifier, object_category, preservation_level, original_name, format_name — `implementation/constants.py:82-87` (`METADATA_REQUIRED`), consumed at `implementation/routes_transfers.py:153`. Without this, a fresh implementer could not reproduce `last_missing_elements` contents or the DEFICIENT/VALIDATED polarity.

**Adjudication of step_7_diff items:**
- Item 1 (fixtures.py `submit_metadata` discovery pattern): traced to PRD §3.2 silence on required element names → PRD edit applied (the only edit).
- Item 2 (`create_appealed_foia` signature): pure test-helper defect; PRD §3.9/§2.1 already determine the behavior and the impl was faithful → no PRD edit.

**Pre-edit search log (Edit 1, the only edit):**
- (a) Subject: per-standard required metadata element name sets referenced but unnamed by PRD §3.2.
- (b) Impl paths enumerated: `constants.py:82-87` (definition, Read); `routes_transfers.py:141-159` submit-metadata — `missing = sorted(e for e in required if e not in elements)`, stores submission verbatim, VALIDATED iff none missing (Read); `routes_transfers.py:53-62` create-time `metadata_standard` enum + method compatibility (grep — never reads element names); `routes_transfers.py:103,109-110` transfer init `submitted_metadata_elements: []`, `last_missing_elements: []` (grep); `routes_transfers.py:162-179` accession gate reads only `status == "VALIDATED"`, never element fields (Read); full-tree grep over `implementation/` for `metadata_elements|submitted_metadata|last_missing|METADATA_REQUIRED|metadata_standard` confirmed no other source path touches the sets (remaining hits are `results.*.json` test artifacts).
- (c) Wording adjustment: kept the sentence a pure enumeration of *required* names only — deliberately not claiming submissions are restricted to those names (the impl accepts and stores extra/unknown elements verbatim at `routes_transfers.py:155`) and not touching the already-pinned "sorted" semantics of `last_missing_elements` or the VALIDATED/DEFICIENT polarity. No further adjustment needed; wording is consistent with every enumerated path.

Output file: `workspace/PRD_FINALIZED.md`

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly one revised line (167), insert matches impl constants.py:82-87 verbatim; both files 392 lines.

## Step 9: Complete PRD — 2026-10-02T16:xx (subagent a3704f5bb211b7dd0)

The patch is verified and complete. Final report:

## Summary

**Produced:** `workspace/PRD_COMPLETED.md` (only file edited).

**Size delta:** PRD_FINALIZED.md 392 lines / 65,377 bytes → PRD_COMPLETED.md 394 lines / 68,409 bytes (+2 lines, +3,032 bytes; 41 changed diff lines).

**Counts:** 24 ambiguity-pins, 2 mismatch-revisions, 0 impl-bugs-reported.

I walked every implementation file (app.py, store.py, errors.py — all 65 codes match PRD §5 statuses, constants.py, envelope.py, validation.py, calcs.py, helpers.py, and all 11 route modules covering all 58 endpoints) against the PRD. Every formula (fee tiers with the 2360-cent worked example, backlog 315 example, priority 107 example, anniversary/Feb-29 arithmetic, all temporal boundary inclusivities), every state machine, gate order, cascade, role binding, and error code already matched; only genuine PRD silence needed pinning.

**Change log** (`{section} — {insert|revise} — {class} — {what} — {impl ref}`):

- §2.2 — revise — ambiguity — `api_request_timestamp` pinned as rendered from the logical clock, never wall-clock — envelope.py:14-18
- §2.2 — insert — ambiguity — unrouted route / wrong method / unexpected error keep the error envelope with `ERR_INVALID_REQUEST` at 404/405/500 — app.py:50-66
- §2.3 — insert — ambiguity — pagination clamps (`limit`→[1,100], `offset`→≥0); non-numeric rejected `ERR_INVALID_REQUEST` — validation.py:158-178
- §2.3 — insert — ambiguity — equal `created_at` ties retain insertion order — validation.py:186
- §2.5 — revise — ambiguity — `updated_at` always 3 fractional digits; clock-stamped fields (incl. `current_utc`, `records_cutoff_date`, `sent_at`, `decided_at`, `visit_date`, `due_back_at`, …) render the exact instant (no fractional part when zero, else 3 digits) — store.py:65-75
- §2.5 — revise — ambiguity — `version` starts at 1 — e.g. routes_agencies.py:39
- §2.6 rung 8 — revise — ambiguity — added `ERR_DIGITIZATION_NOT_READY` and `ERR_REFERRALS_OUTSTANDING` to the endpoint-specific 409 enumeration (the "several" list was non-exhaustive; both fire at the from-state rung) — routes_collections.py:156-160, routes_reviews.py:246-255
- §3.2 — insert — ambiguity — submit-metadata admitted only from `INITIATED`/`DEFICIENT`; else `ERR_INVALID_STATE` — routes_transfers.py:147-151
- §3.2 — insert — ambiguity — the other method's payload field is stored null — routes_transfers.py:105-106
- §3.2 — revise — ambiguity — withdraw from any other status → `ERR_INVALID_STATE` — routes_transfers.py:227-231
- §3.3 — insert — ambiguity — `receipt_note` required non-empty, validated but not stored; accession answers with the updated transfer — routes_transfers.py:178-179, 218
- §3.4 — insert — ambiguity — complete-description from non-`PROCESSING` → `ERR_INVALID_STATE` — routes_collections.py:82-86
- §3.4 — insert — ambiguity — publish-digital from non-`DESCRIBED` → `ERR_INVALID_STATE` — routes_collections.py:151-155
- §3.5 — insert — ambiguity — wrong role for the review flavor → `ERR_FORBIDDEN_ROLE` — routes_reviews.py:52-61
- §3.5 — revise — ambiguity — systematic age gate evaluated at the temporal rung, ahead of the posture check — routes_reviews.py:100-116
- §3.5 — insert — ambiguity — `agency_ids` must be a non-empty list — routes_reviews.py:189
- §3.5 — insert — ambiguity — bulk referral creation answers 201 `array`, in supplied id order, no pagination fields — routes_reviews.py:214-231
- §3.5 — revise — ambiguity — `exemption_code` recorded only for `EXEMPT`; `DECLASSIFY` stores null — routes_reviews.py:340
- §3.5 — insert — ambiguity — referrals-outstanding check sits immediately after the from-state gate, before shape rules — routes_reviews.py:246-258
- §3.6 — revise — ambiguity — release from any non-`NOTIFIED` status (incl. already `RELEASED`) → `ERR_RESTRICTION_NOT_NOTIFIED` — routes_restrictions.py:133-137
- §2.4 — revise — **mismatch** — lazy expiry pinned to `ACTIVE` registrations — helpers.py:66-73. *Why PRD was defective:* the blanket "on any load of a registration" contradicts §3.7's own "Suspension… is terminal and… has no way back" (a `SUSPENDED` registration holding a lapsed `card_expires_at` must not transition); the impl's ACTIVE-only reading is the internally consistent one.
- §3.7 — revise — **mismatch** — same ACTIVE-only pin in the workflow narrative — helpers.py:66-73 (same justification)
- §3.7 — insert — ambiguity — activation admits exactly `PENDING`/`EXPIRED`; else `ERR_INVALID_STATE` — routes_researchers.py:67-71
- §3.8 — revise — ambiguity — `payment_reference` required, non-empty — routes_repros.py:134
- §3.9 — insert — ambiguity — adjudicating from `APPEALED`/`APPEAL_GRANTED`/`APPEAL_UPHELD`/`CLOSED` → `ERR_INVALID_STATE` — routes_foia.py:120-124
- §4 — insert — ambiguity — list filters are exact-match equality — validation.py:182-189

**IMPL BUGs:** none. No case where the implementation violated a clearly and uniquely pinned PRD rule; every PRD↔impl divergence found was PRD silence or the one internally inconsistent lazy-expiry wording noted above.

Orchestrator verification: `diff -q` confirms PRD_COMPLETED.md differs from PRD_FINALIZED.md (not a silent no-op); byte/line delta matches report exactly (392/65377 → 394/68409); no source file in implementation/, test_suite/, or test_helpers/ is newer than the final sweep's results.1.json (Step 9 touched only the PRD); all 8 results.*.json intact; ACTIVE-only lazy-expiry pin confirmed at PRD_COMPLETED.md:96. Pipeline complete — final state: 8/8 sweep rounds at 93/93.
