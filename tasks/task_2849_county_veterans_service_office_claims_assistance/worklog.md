# Worklog — task_2849_county_veterans_service_office_claims_assistance

## Step 1: Create task directory — 2026-09-05T06:32:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2849_county_veterans_service_office_claims_assistance` and `workspace/` (pre-assigned path; no index auto-allocation).

## Step 2: Generate scaffold — 2026-09-05T08:28:00.000Z

Subagent summary (verbatim):

All three scaffold artifacts for task 2849 are complete and lint-clean.

Files (all under `tasks/task_2849_county_veterans_service_office_claims_assistance/`):
| file | lines | top-level key(s) |
|---|---|---|
| `SCAFFOLD.yaml` | 3511 | `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` (no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2876 | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4503 | `scaffold_corner_design` only |

`workspace/` and `worklog.md` untouched; nothing else created or deleted in the task dir (scratch work stayed in `workspace/.scratch/`).

Lint verdict (verbatim, final run):
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
Coverage
  §1.5 endpoints declared:    70
  §1.1 entities declared:     14
  §1.8 instances scanned:     23
  §1.9 instances scanned:     67
  Calls scanned (§1.8+§1.9):  1166

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

SCAFFOLD.yaml counts: 14 entities · 11 state machines · 2 concurrency rules (§1.2.1) · 16 calculations · 62 validations (priorities 1–76) · 70 endpoints · 64 error codes · 5 roles. Domain `county-veterans-service-office`, prefix `/cvso`, logical clock default `2026-08-01T00:00:00Z`.

§1.8 — 9 rule ids, 23 instances: `dual_variant_calc` 2 · `combinatorial_formula` 3 · `non_linear_state_machine` 3 · `transitive_cascade` 2 · `priority_pair_validation_conflict` 3 · `boundary_precision_check` 3 · `cross_entity_state_dependency` 3 · `resource_temporal_overlap` 2 · `compensating_invariant` 2.

§1.9 — all 9 guide sections, 98 instances (67 with full recipes, 31 `excluded_because` stubs): `entities` 12 (0 stubs) · `state_machines` 14 (5) · `calculations` 15 (9) · `validations` 10 (5) · `endpoints` 9 (1) · `errors` 27 (7) · `rbac` 6 (1) · `cross-cutting complexity layers` 4 (3) · `consistency model` 1 (0).

Verification performed beyond the lint:
- All 64 error codes are reachable: 56 triggered by real §1.9 recipes, 8 covered by stubs citing the exact §1.8 instance that triggers them at a tighter boundary.
- All 70 endpoints appear in at least one executable call; all 16 calculations and all 11 state machines are cited in grounds.
- Instance names unique across both design files; every `excluded_because.difficulty_instance` resolves to a real §1.8 instance name (never a corner name); no stub carries a `test_recipe`.
- Every `grounds:` reference resolves to a declared §1.1–§1.7 object (fixed one dangling `calculations.retro_award_cents` → `claim_retro_award_cents`).
- Forbidden concurrency vocabulary now absent from all three files.

Disclosures / edits made to SCAFFOLD.yaml this session:
1. The directive "harder than expert level" is encoded as `complexity_profile.difficulty_level: beyond_expert`; it is not present in `scenario:` or anywhere else.
2. Validation priority 30 (`ERR_NOT_FOUND`) was widened to cover request-body identifier references outside priorities 31–36's `applies_to` (explicitly `reviewer_representative_id` on `POST /cvso/claims/{id}/transitions`).
3. `response_envelope.success` now documents the list shape: rows in `data` as an array with the four pagination fields in a sibling `pagination` object.
4. Earlier-session audit edits still in place: §1.2/§1.5 field-name alignments, `CE_CREDITS_REQUIRED` inlined as literal 12, `PENDING_ACCREDITATION` → `PENDING` in the selector input set, `buffer_minutes` made optional on `POST /cvso/exam-sites`.

Design compromise flagged for the test generator: `corner_designation_acceptance_is_refused_when_the_caseload_ceiling_is_reached` needs 40 accepted designations, so its `setup_api_calls` gives the per-veteran five-call fixture block once with a comment instructing a loop for i = 1..41 (accept only for 1..40) rather than 240 literal calls.

Orchestrator post-step action: deleted line 40 of SCAFFOLD.yaml (`  difficulty_level: beyond_expert`) so the difficulty directive cannot reach the doc generator or PRD.md. All three YAML files re-validated with `yaml.safe_load` after the edit; SCAFFOLD.yaml is now 3510 lines.

## Step 3: Copy shared files — 2026-09-05T08:28:30.000Z

Copied `INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T08:47:00.000Z

Subagent summary (verbatim):

PRD generation complete.

Output: `workspace/PRD.md` — **497 lines**, ~16,500 words, 122 KB. Last line is a complete final row of the §5 error table (a real section boundary; matches the example PRD's ending convention). Nothing else in the task dir was created, modified or deleted; scratch work stayed in `workspace/.scratch/`. Neither withheld design file was opened, and no sibling task dir was read.

Section list:
- `# County Veterans Service Office API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Roles/RBAC · 2.2 API Response Structure (byte-verbatim) · 2.3 Pagination · 2.4 The Logical Clock · 2.5 Identity/Versioning/Audit · 2.6 Accreditation as Precondition · 2.7 Amounts & Rounding Discipline · 2.8 Three Conserved Quantities · 2.9 Cascade Propagation · 2.10 Stale-Version Guards · 2.11 Rejection Precedence · 2.12 Nested Reads & Reverse Lookups
- `## 3. Business Logic & Workflows` — 3.1 Representative Roster (5-hop revocation cascade, caseload weight) · 3.2 Intake & Discharge Document File · 3.3 Screening, Priority Banding, Case Lifecycle · 3.4 Designation & Assignment (selector) · 3.5 Claim Prep, Peer Review, Segregation of Duties · 3.6 Evidence Development & Completeness Score · 3.7 Exam Sites & Booking · 3.8 Recording a Decision (retro award, combined rating, 4-hop cascade) · 3.9 Appeal Counselling, Deadlines, Sweep · 3.10 State Programs & the Two Independent Dimensions · 3.11 Outreach · 3.12 Quarterly Outcome Reporting
- `## 4. Endpoint Definitions` (4-column table) · `## 5. Error Code Catalogue` (2-column table)

Coverage (mechanically verified):
- Endpoints: 70/70 in §4, all with method, path, description, role list exactly as scaffolded.
- Errors: 64/64 in §5 with statuses; all 64 identifiers also appear in §2/§3 prose (verified 0 absent).
- Validations: 62/62 in §2.11, each with its priority number, error id, HTTP status and full `applies_to` scope, in 9 bands (1–5, 10–22, 30–36, 40–49, 50–54, 55–59, 60–64, 65–73, 74–76).
- Calculations: 16/16 rendered as precise prose with every constant embedded (wartime windows · priority bands · six category conjunctions · successive-residual rating · pinned two-stage evidence rounding · retro award schedule · pinned gross-keyed fee waterfall · three ledgers · caseload weight · assignment selector · appeal deadline · dual-basis performance score · half-open exam conflict · symmetric closed travel conflict).
- State machines: 11/11, all 58 transitions described with preconditions, side effects, cascade hops and terminal states. All 32 `action` literals appear verbatim, all 109 enum values appear, all 6 cascade literal strings appear.
- Entities: 14/14 (including the `common_fields: false` EligibilityScreen). Roles: 5/5. Concurrency rules: 2/2.

Three Hard Contracts:
- Contract 1 (Field-Name Coverage): PASS — 140 required backtick tokens (union of 130 entity field names + 90 endpoint input identifiers) all present; verified twice with independent extractions, 0 missing. `id`/`created_at`/`updated_at`/`version` also present.
- Contract 2 (Rule Coverage): PASS — priority ordering complete; both OCC rules stated with write, `expected_veteran_version`/`expected_program_version`, error id and 412; all cross-entity side effects, `applies_to` scopes, defaults/types, sibling-branch symmetry, all transitions, all calculations, all endpoint side effects covered.
- Contract 3 (§3 Path Purity): PASS — 0 backtick tokens in §3 start with `/`, are a bare HTTP method, or combine method+path; §3 contains zero occurrences of the string `/cvso`.

Two scaffold ambiguities resolved by judgement (noted for review):
1. `response_envelope.success` puts pagination fields in a sibling `pagination` object while the mandatory verbatim §2.2 block puts them in `meta`. §2.2 was emitted byte-verbatim and §2.3 additionally states list endpoints mirror the same four fields in a top-level `pagination` object — a superset satisfying both.
2. The Veteran entity says `character_of_service` is null while no document is `VERIFIED`, but the creation endpoint's side effect sets it to `UNCHARACTERIZED`. The PRD follows the endpoint (creation sets the `UNCHARACTERIZED` placeholder) and describes rejection as "establishing no character of service, leaving the field at its pre-verification placeholder", which is consistent under either reading.

Orchestrator truncation check (mandated by the run directive): `tail -25` shows PRD.md ending on a complete `| \`ERR_PROGRAM_POOL_EXHAUSTED\` | 409 |` table row of §5, i.e. a real section boundary, not a mid-sentence cut. All 5 top-level sections and 24 subsections present. No regeneration required.

## Step 6: Generate implementation — 2026-09-05T09:35:00.000Z

Subagent summary (verbatim):

Implementation is complete and verified.

Files written (all in `workspace/implementation/`):

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | reads `$PORT` (fallback 10000), binds `0.0.0.0`, guarded pip install, `exec python3 app.py` in the foreground |
| `requirements.txt` | 1 | `flask>=3.0.0` |
| `app.py` | 63 | Flask factory, 5 blueprint registrations, `ApiError`/`HTTPException`/generic handlers, `threaded=True`, `use_reloader=False` |
| `store.py` | 155 | in-memory `Store` (14 dicts + logical clock + `_seq`), id/instant/date helpers, `new_row`/`bump`/`public`/`ordered` |
| `errors.py` | 78 | all 64 error ids → HTTP status, `ApiError` |
| `envelope.py` | 51 | `meta`/`response_type`/`data` envelope + sibling `pagination` |
| `guard.py` | 554 | `authorize` (rules 1–5), `check_shape` (rules 10–22), 13 `need_*` lookups (rules 30–36), pagination, filters, `run_checks` ordered dispatcher |
| `calc.py` | 595 | all 16 calculations + constants + 3 conserved-quantity recomputes |
| `views.py` | 16 | row → payload projection (re-derives `days_remaining`) |
| `routes_registry.py` | 282 | clock + representatives (8 endpoints), 5-hop revocation cascade |
| `routes_intake.py` | 450 | veterans, screens, discharge documents (13) |
| `routes_claims.py` | 766 | POAs, claims, evidence items (16), 4-hop decision cascade |
| `routes_exams.py` | 375 | exam sites, appointments, decision reviews (13) |
| `routes_state.py` | 603 | state programs, benefit applications, outreach, outcome reports (20) |

Total 3,999 lines. Every `.py` compiles clean; no `__pycache__`, no scratch files, no stray files left in `workspace/`.

Coverage, machine-verified:
- Endpoints: exactly 70. Diffed the live Flask url_map against the 70 rows of PRD §4 — `impl-only: []`, `prd-only: []`.
- Error codes: exactly 64. Diffed `ERROR_HTTP_STATUS` against the §5 catalogue — no gaps either way, zero HTTP-status mismatches, and every one of the 64 is actually raised somewhere in the code.
- Validation priorities: all 62 (1–5, 10–22, 30–36, 40–76). Rules 1–5 live in `authorize`, 10–22 in `check_shape` in PRD order, 30–36 as path-then-body `need_*` lookups, 40–76 as `(priority, fn)` tuples sorted by `run_checks`. Sub-priorities (40.2/40.5/43.5/45.5/49.5) slot undocumented preconditions into the right band without disturbing the declared numbers.
- State machines: 12 implemented (accreditation, intake, discharge verification, POA, claim, evidence, appointment, decision review, determination + disbursement as two independent dimensions, outreach, report).
- Calculations: all 16 from the scaffold, including the three conserved ledgers (`allocated_cents`, `booked_slot_count`, `active_poa_count`) and the two overlap tests (half-open trailing site buffer vs. closed symmetric 30-min travel buffer).

Smoke test: ran a 40-call scripted flow on self-picked port 21889/21897 (representative → activate → veteran → discharge doc → verify → screen → POA → accept → claim → evidence → exam site → appointment → program → application → approve → outreach → hold → report → compute → submit → accept → issue), plus 10 negative probes. Result: SMOKE OK, zero unexpected statuses. Highlights:
- Envelope exactly `{meta, response_type, data}` + sibling `pagination`; `meta` carries `api_request_id`, `api_request_timestamp` and the four pagination fields.
- Derived values correct: `county_case_number` `CVSO-2026-000001`, `priority_group` P3, `income_limit_applied_cents` 2367000, `evidence_completeness_pct` 41.79, site defaults capacity 2 / buffer 15, caseload `{active_poa_count: 1, open_claim_count: 1, caseload_weight: 4, assignment_eligible: true}`.
- Award waterfall verified directly against the PRD bands: rating 50 on a 20,000,000-cent assessment → gross 8,000,000 / fee 160,000 / net 7,840,000; rating 70 → capped at `max_award_cents` 10,000,000 → fee 200,000 / net 9,800,000; tuition 12 credits → 540,000 with a 0.00 fee band; burial → 90,000. Money is emitted as JSON integers.
- Negative probes: 401 no headers, 401 `ERR_INVALID_ROLE`, 403 `ERR_UNAUTHORIZED`, 422 `ERR_INVALID_PAGINATION`, 404 entity-specific not-found, 422 `ERR_VALIDATION`/`ERR_READONLY_FIELD`, 422 `ERR_UNKNOWN_ACTION`, 409 `ERR_INVALID_STATE_TRANSITION`, 404 unknown route. Domain rules fired unprompted and correctly (`ERR_NEXUS_STRENGTH_MISMATCH`, `ERR_REPRESENTATIVE_NOT_ACCREDITED`).
- Restart wipes all state: created a veteran (total_count 1), killed the pid, relaunched on the same port → total_count 0. Boot to first served request measured at 0.61 s, comfortable for `--isolation per-test-server`.

Two operational notes worth recording: my first restart-check used a compound `cd … && bash start.sh &`, so `$!` captured the subshell rather than the exec'd python — the check silently talked to the still-running old server and looked like state was persisting. I re-ran it resolving the pid via `ss -ltnp` per port and it was clean. That same bug had leaked nine smoke servers on ports 21847–21897; I killed each one individually by its port-resolved pid (no pattern kills), and confirmed no listener remains on any 218xx/219xx port.

## Step 5: Generate unit tests — 2026-09-05T10:25:00.000Z

Subagent summary (verbatim):

Step 5 is complete. Final report:

Files written (task root, not `workspace/`):

`test_helpers/` — 3,388 lines total
| file | lines |
|---|---|
| `__init__.py` | 36 |
| `api_client.py` | 574 |
| `api_errors.py` | 183 |
| `assertions.py` | 332 |
| `constants.py` | 288 |
| `factories.py` | 682 |
| `fixtures.py` | 880 |
| `test_users.py` | 141 (all 5 role identities) |
| `types.py` | 272 |

`test_suite/` — 7,467 lines total, 212 tests
`conftest.py` 59 · `test_01` 213/6 · `test_02` 263/8 · `test_03` 189/6 · `test_04` 262/7 · `test_05` 284/10 · `test_06` 289/9 · `test_07` 342/8 · `test_08` 418/10 · `test_09` 232/6 · `test_10` 319/8 · `test_11` 376/16 · `test_12` 473/15 · `test_13` 473/15 · `test_14` 439/11 · `test_15` 614/18 · `test_16` 710/23 · `test_17` 938/21 · `test_18_rbac_and_cross_cutting.py` 574/15 (lines/tests).

Coverage against the two design indices:
- Queue A (Difficulty §1.8): 23 of 23 instances translated, 0 skipped, 78 tests, every instance carrying ≥2 tests (audit: `queue A instances with <2 tests: []`).
- Queue B (Corner §1.9): 66 of 67 non-stub instances translated, 1 skipped, 134 tests, ≥1 test each. `test_18` closed the last seven: `rbac` (5), `cross-cutting complexity layers` (1, both optimistic-concurrency guards), `consistency model` (1, derived-field freshness for `evidence_completeness_pct` 47.05→83.42, `caseload_weight` 4→6, and `combined_rating_pct` 30 / `priority_group` P2).

Skipped instance (1) — `entities/corner_exam_site_buffer_minutes_defaults_to_zero_when_omitted`: not uniquely derivable — PRD §3.7 mandates a 15-minute default buffer, which contradicts the index's asserted 0, so no PRD sentence derives the asserted outcome. Not weakened, not xfailed, no placeholder emitted.

Verification passes (both clean):
- PRD-citation pass over all 19 suite files: `checked=256 missing=0` (every ≥5-word quoted span is a literal substring of `workspace/PRD.md`). Two pre-existing false positives were removed by shortening two payload data literals to under five words (`"Board sanction"` in `test_07`, `"Later date requested"` in `test_08`) — no citation text changed.
- Scaffold-citation pass: 212 `Design:` lines, exactly one per test, `bogus tags: []` — every tag resolves to a real non-stub instance in the correct index; no untagged or dual-tagged tests.
- All 18 modules import cleanly (`imported 18 modules cleanly`), all `py_compile` clean, `__pycache__` removed.
- `ls -la` on the task root confirms `test_helpers/` and `test_suite/` present; `workspace/test_helpers` and `workspace/test_suite` do not exist. `worklog.md`, `PRD.md`, the SCAFFOLD files and `workspace/implementation/` were never touched; no process was killed.

## Step 7: Run tests and iterate — 2026-09-05T10:52:00.000Z

Subagent summary (verbatim):

Whole task dir is untracked, so no diff baseline — but my edits were limited to the two test files below.

**Iterations run:** 2 (initial diagnostic sweep + verification sweep).

**Tests deleted:** none. All 4 failures survived STEP 1 (PRD verbatim-covers the asserted cascade hops and the version-increment rule, and each is uniquely derivable), and were resolved at STEP 2 as test bugs.

**Fixes applied to `test_helpers/`:** none. The upstream fixtures and factories were already PRD-faithful; the bugs lived in the test functions' own request identities and one hardcoded expected value.

**Fixes applied to `implementation/`:** none. No implementation defect was found — the server was correctly enforcing PRD §2.11 band-4 rule (42) and PRD §2.6 in all three cascade cases.

**Fixes applied to `test_suite/`** (all in the direction of greater PRD fidelity):

`test_suite/test_07_representation_cascades.py` — `TestAccreditationRevocationCascade`, three tests (`test_the_assignment_and_the_designation_are_both_torn_down`, `test_the_open_claim_falls_back_to_draft_without_its_designation`, `test_the_examination_is_cancelled_and_the_site_ledger_restored`). Each read back a cascade-touched row (`GET /powers-of-attorney/{id}`, `GET /claims/{id}`, `GET /exam-appointments/{id}`) using `revoked_accreditation["officer_headers"]` — the headers of the representative the fixture had just revoked. PRD §2.6 / §2.11 rule (42) states the accreditation gate applies "on every endpoint whose role list includes `CountyOfficer`", including reads, so the PRD-faithful implementation correctly answered `ERR_REPRESENTATIVE_NOT_ACCREDITED` (403). Switched those three reads to `SYSTEM_ADMIN_HEADERS` (all three endpoints list `SystemAdmin` as authorized in §4). The cascade assertions themselves are unchanged.

`test_suite/test_18_rbac_and_cross_cutting.py` — `TestOnlyTheIntakeClerkMayAssignARepresentative::test_the_front_desk_makes_the_identical_call_succeed`. Asserted an absolute `version == 2` after assignment, but the shared `screened` fixture reaches the veteran through intake → document submit → verify → screen, each of which §3.2/§3.3 requires to bump `version`, so the row is legitimately at 4 before assignment. PRD §3.4 states only that a successful assignment "increments the veteran's `version` by 1", so the assertion now reads the pre-call version and asserts `before + 1` — the exact rule the PRD states, rather than a fixture-chain-dependent literal.

**Final sweep evidence** (all rounds, post-fix):

| results file | passed / total |
| --- | --- |
| results.1.json | 214 / 214 |
| results.2.json | 214 / 214 |
| results.3.json | 214 / 214 |
| results.4.json | 214 / 214 |
| results.5.json | 214 / 214 |
| results.6.json | 214 / 214 |
| results.7.json | 214 / 214 |
| results.8.json | 214 / 214 |

Zero failed, zero errors, zero skipped in every round. No flakiness signal: the pre-fix failure set was identical in all 8 rounds (deterministic, not load-induced), and the post-fix green is likewise unanimous. `worklog.md` was not touched.

Orchestrator independent verification: re-parsed all 8 `results.*.json` directly — every file reports `passed 214 total 214 failed 0 errors 0 skipped 0`, mtime 10:46, both edited test files mtime 10:39 (i.e. the green sweep ran after the fixes). Step 8 is NOT skipped (2 `test_suite/` fixes were applied), though both fixes were test-side only with zero `implementation/` fixes, so a byte-identical `PRD_FINALIZED.md` would be a legitimate Step 8 outcome.

## Step 8: Finalize PRD — 2026-09-05T10:56:00.000Z

Subagent summary (verbatim):

`workspace/PRD_FINALIZED.md` created as a byte-identical copy of `PRD.md`. Zero edits — which the task brief explicitly flags as a legitimate outcome here, and which I confirmed against the implementation before accepting.

- `PRD.md`: 497 lines / 122,249 bytes
- `PRD_FINALIZED.md`: 497 lines / 122,249 bytes
- Delta: 0 lines, 0.00%

Change list: none. Both `<step_7_diff>` items were pure test-function bugs; neither exposed PRD silence or PRD/impl divergence.

Pre-edit verification log (both required checks):

Check 1 — accreditation read-gate scope (rule 42 / §2.6)
(a) Subject: whether the `ERR_REPRESENTATIVE_NOT_ACCREDITED` gate applies to read endpoints when the actor is a `CountyOfficer`, and whether PRD uniquely says so.
(b) Impl paths enumerated and read:
- `guard.py:530-545` — `run_checks()` unconditionally injects `(42, _accreditation_active)` and `(54, _accreditation_unexpired)` whenever `g.role == "CountyOfficer"`, with no method or verb condition; the `request.method == "GET"` branch above it only adds rule 15, confirming GETs flow through the same injector.
- `guard.py:509-514` — `_accreditation_active()` gates on `rep["accreditation_status"] != "ACTIVE"`, i.e. it fires for `REVOKED` exactly as PRD §2.6 line 106 describes.
- Grepped every `run_checks(` callsite across all five route modules (78 calls). Every route function in `routes_intake.py`, `routes_claims.py`, `routes_exams.py`, `routes_registry.py`, `routes_state.py` calls it — including all list and single-row reads.
- The three Step 7 sites specifically: `routes_claims.py:78-82` (`read_designation`), `routes_claims.py:310-315` (`read_claim`), `routes_exams.py:141-146` (`read_appointment`) — each does `authorize(...)` → `need_*()` → `run_checks()`, so a revoked officer gets 403 on the read and existence still wins over the gate.
- Role tuples `READ_POA` (`routes_claims.py:20`), `READ_CLAIMS` (`routes_claims.py:22`), `READ_APPOINTMENTS` (`routes_exams.py:19`) all include both `CountyOfficer` and `SystemAdmin`, matching PRD §4 lines 379-380, 384-385, 399-400 exactly.
(c) Wording adjustment: none needed. PRD line 164 rule (42) already reads "on every endpoint whose role list includes `CountyOfficer`", which uniquely determines the read gate; §2.6 line 106 is consistent. No edit.

Check 2 — version-increment semantics (§3.4 assignment, §3.2/§3.3 chain)
(a) Subject: whether the veteran `version` sequence the `screened` fixture produces (1 → 4 pre-assignment, 5 post) is fully derivable from PRD.
(b) Impl paths enumerated and read: `store.py:137` (creation `version = 1`), `store.py:143-145` (`bump()`), `routes_intake.py:301-331` `create_document`, `routes_intake.py:365-414` `review_document` (all three branches), `routes_intake.py:154-177` `screen_veteran`, `routes_intake.py:179-227` `assign_representative`. Cross-checked against PRD lines 96, 206, 208, 216, 247, 140 — every hop in the fixture chain is verbatim-pinned, so `before + 1` is the PRD rule and the old literal `version == 2` was a fixture-chain artefact, not a PRD gap.
(c) Wording adjustment: none needed. No edit.

Note: one pre-existing, out-of-scope observation (Step 7 never exercised it, so the PRD was deliberately left untouched): on single-row GETs the impl resolves existence (`need_*`) before `run_checks()`, so rule 15 pagination validation (a band-2 rule per PRD line 176) runs after the band-3 404. A request combining a bad `limit` with an unknown id therefore returns the 404, not `ERR_INVALID_PAGINATION`. Flagged only in case a later step wants it; not traceable to any `<step_7_diff>` item.

Orchestrator note: byte-identical `PRD_FINALIZED.md` is the expected and legitimate Step 8 outcome when Step 7 applied zero `implementation/` fixes and zero deletions (both Step 7 items were test-function bugs). Verified with `cmp`. The out-of-scope 404-vs-pagination-ordering observation has been forwarded to Step 9 as an explicit starting lead, since Step 9's scope is the full impl scan and that item is exactly a PRD/impl ordering mismatch.

## Step 9: Complete PRD — 2026-09-05T11:35:00.000Z

Run as three sequential module-partitioned passes over one shared `workspace/PRD_COMPLETED.md` (pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from re-copying, and each confirmed it did not). Partition: pass 1 = `app.py`/`store.py`/`envelope.py`/`errors.py`/`views.py`/`guard.py`/`routes_registry.py`; pass 2 = `routes_intake.py`/`routes_claims.py` + the `calc.py` functions they call; pass 3 = `routes_exams.py`/`routes_state.py` + the remaining `calc.py`. Leads were forwarded forward between passes.

### Pass 1 of 3 — cross-cutting layer + representative registry (subagent summary, verbatim)

Integrity: `cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` done once at the start. `PRD_FINALIZED.md`: 497 lines / 122249 bytes. `PRD_COMPLETED.md`: 497 lines / 128431 bytes (grew only; 14 lines touched, 0 sections added; still ends with the `ERR_PROGRAM_POOL_EXHAUSTED` row).

Counts: ambiguity-pins 15, mismatch-revisions 3 (§2.3 rule-15 scope, §2.11 rule-15 ordering, §2.3 list-ordering key).

Changes:
- §2.1 — revise — ambiguity — `X-User-*` header that is whitespace-only counts as absent (`ERR_MISSING_AUTH_HEADERS`) — guard.py:154
- §2.1 — insert — ambiguity — when the addressed designation/review does not exist the owner comparison is skipped, so the band-3 404 wins over `ERR_ACTOR_NOT_OWNER` — guard.py:177-181, routes_claims.py:88,151, routes_exams.py:307
- §2.2 — revise — ambiguity — `api_request_id` = `req_` + 24 lowercase hex chars — envelope.py:9,13
- §2.3 — revise — mismatch — rule 15 is applied to every GET (single-resource reads validate then ignore `limit`/`offset`); POST/PATCH never reject them — guard.py:542-544
- §2.3 — revise — mismatch — default list order is insertion/creation sequence, not `created_at` (which collides because the clock is static); plus filter semantics: unparseable boolean/`fiscal_year` token matches no rows, other filters are raw-string exact equality, unlisted params ignored — store.py:153-155, guard.py:424-448
- §2.4 — revise — ambiguity — clock setter's `data` carries only `current_utc`, echoed canonically at 3 fractional digits (finer input retained internally), and the clock may move backwards — routes_registry.py:29-35, store.py:63-78
- §2.4 — revise — ambiguity — on input the fractional-second part may be omitted or any width (first six digits significant), `T`/`Z` either case, numeric offsets and non-strings rejected — store.py:21-23,100-116
- §2.5 — insert — ambiguity — a `PATCH` bumps `version`/`updated_at` unconditionally, even on an empty or no-op body — routes_registry.py:125, routes_intake.py:139, routes_exams.py:79, routes_state.py:104
- §2.5 — insert — ambiguity — the server-owned name set is system-wide, exempted only where the addressed endpoint declares that name as its own input; unknown non-server-owned keys are ignored, not rejected — guard.py:108-139,337-340
- §2.11 band 2 preamble — insert — ambiguity — body parsed before rule 10 and regardless of `Content-Type`; absent/empty body = `{}`; non-JSON or non-object body = `ERR_VALIDATION` — guard.py:189-201
- §2.11 (12) — insert — ambiguity — absent/null `action` is `ERR_UNKNOWN_ACTION`; per-action role gates report `ERR_UNAUTHORIZED` here (not band 1); action-conditional required fields also checked here, ahead of rules 13–22 — guard.py:239-254
- §2.11 (14) — insert — ambiguity — adds `ce_credits`/`veterans_contacted`/`veterans_enrolled` ≥ 0, JSON-integer typing, the eight string length bounds (trimmed lower / raw upper), boolean typing, and the non-blank rule for `*_id`/`reason`/`rework_note`/`fiscal_quarter` — guard.py:73-102,264-299
- §2.11 (15) — revise — mismatch (the Step 8 lead, confirmed) — rule 15 runs after band-3 existence on any id-bearing GET, so bad `limit` + unknown id → the entity's 404; it keeps band-2 precedence over bands 4+ including gates 42/54. Verified for all 17 id-bearing GETs — guard.py:535-550, routes_registry.py:99-102,255-258,267-270
- §2.11 (21)/(22) — insert — ambiguity — rule 21 exemption cross-referenced; per-endpoint extra shape rules run at the end of band 2 (after rule 22, before band 3) and all report `ERR_VALIDATION` — guard.py:350-352
- §2.11 closing paragraph — revise — consistency — notes the rule-15 exception to "shape always beats existence"
- §4 preamble — insert — ambiguity — unlisted path or unsupported method → `ERR_NOT_FOUND` (404); trailing slash tolerated — app.py:24,38-46
- §3.1 — revise — ambiguity — `revocation_reason` is present-but-null on a fresh row; `accreditation_number` uniqueness spans every representative including `LAPSED`/`REVOKED` — routes_registry.py:42-63
- §3.1 — insert — ambiguity — the two `RENEW` input rules are `ERR_VALIDATION` evaluated in band 2, i.e. before the representative id resolves and before the from-state check; `ce_credits_earned` is replaced, not accumulated — routes_registry.py:141-151,182

Verified as already pinned (left alone): §5 error catalogue all 64 id→status pairs byte-identical to `errors.py`; `run_checks` numeric sort reproduces PRD's band/rule numbering exactly; §2.11 band 3, §2.6 gates on reads, §2.10 rule 22, §3.1's five-hop cascade with all `version` bumps, the caseload decomposition payload and `assignment_eligible` filters, §2.3 `has_more`/`total_count`, §2.12 nested-read order. Deliberately not documented: `app.py:48-52` catch-all `Exception → ERR_VALIDATION 422` (internal-error fallback, not specifiable). Deliberately left under-determined: `ACTIVATE` also recomputing `active_poa_count`; `limit`/`offset` tolerating a leading sign and whitespace.

### Pass 2 of 3 — intake + claims/evidence spine (subagent summary, verbatim)

No re-copy: never ran `cp`, `Write`, or any wholesale rewrite; every change a targeted `Edit`. Pass 1's 18 edits all still present (spot-checked §2.1–§2.5, §2.11, §3.1, §4 preamble). Size before `497 128431`, after `497 137350`; line count unchanged, bytes only grew, file still ends with the `ERR_PROGRAM_POOL_EXHAUSTED` row.

Counts: 30 Edit calls → 23 ambiguity-pins and 9 mismatch-revisions.

Changes:
- §2.9 — revise — mismatch — dropped `DRAFT` from the "revocation leaves these claims alone" list, since revocation does clear `poa_id` on DRAFT claims — routes_claims.py:186-188
- §3.2 — insert — ambiguity — service-date relationship and logical-clock upper bound on intake dates — routes_intake.py:60-90
- §3.2 — insert — ambiguity — `priority_group` is stored as the literal `P4` at creation, not derived — routes_intake.py:91
- §3.2 — insert — ambiguity — a correction's merged service-date comparison runs after the veteran is resolved, so an unknown id reports `ERR_VETERAN_NOT_FOUND` first — routes_intake.py:128-138
- §3.2 — insert — ambiguity — discharge-mirror tie-break is `created_at` ascending — calc.py `refresh_discharge_mirror`
- §3.2 — revise — mismatch — VERIFY does not force the mirror to `VERIFIED`; it re-mirrors from the newest document and also re-derives `priority_group` — routes_intake.py:397-398
- §3.2 — revise — mismatch — HOLD/REJECT mirror phrasing restated as "re-mirrored from the newest document" — routes_intake.py:397
- §3.2 — insert — ambiguity — resubmit re-mirrors from the newest document and does its merged claimed-date check after existence — routes_intake.py `resubmit_document`
- §3.2 — insert — ambiguity — which document governs `wartime_service_days` when several exist — calc.py `refresh_discharge_mirror`
- §3.3 — insert — ambiguity — `reason` is the empty string when every category is true — calc.py category chains
- §3.3 — insert — ambiguity — exact conjunct spellings emitted in `reason` — calc.py
- §3.3 — revise — mismatch — `priority_group` re-derivation trigger list widened to "every correction, whatever fields it touches" plus document verification — routes_intake.py:128-138, 398
- §3.3 — insert — ambiguity — RECORD_DEATH: each collected preparer's `caseload_weight` recomputed, `version` moves only when a term changed, and §3.5 appointment/evidence cleanup is not run — routes_intake.py:278-293
- §3.4 — insert — ambiguity — offer: `executed_on` unbounded, no accreditation/type/ceiling test, an existing ACTIVE designation is irrelevant, veteran resolved before representative — routes_claims.py `offer_designation`
- §3.4 — revise — mismatch — acceptance requires the designated representative to be `ACTIVE` (`ERR_REPRESENTATIVE_NOT_ACCREDITED`, 403), after the stale-version guard and before the ceiling — routes_claims.py `accept_designation` (45.5)
- §3.4 — revise — mismatch — revocation's request shape is keyed on the designation's `status`, not the acting role; the OFFERED path reads nothing else — routes_claims.py `revoke_designation`
- §3.4 — revise — mismatch — revocation cascade: DRAFT claims get only `poa_id` cleared; appointments cancelled only for reverted claims; the veteran row is untouched so `assigned_representative_id` survives; revocation works even for a DECEASED veteran — routes_claims.py:186-205
- §3.4 — insert — ambiguity — assigning against a DECEASED veteran reports `ERR_VETERAN_DECEASED` from inside check 40, ahead of the SCREENED from-state test — routes_intake.py:188-195
- §3.4 — insert — ambiguity — a nominated representative is subject only to the ceiling, bypassing the selector's status/type/count filters — routes_intake.py:184-214
- §3.5 — insert — ambiguity — claim creation defaults and `veteran_id` resolved before `poa_id` — routes_claims.py `open_claim`
- §3.5 — insert — ambiguity — the per-action actor-identity gate reports `ERR_INVALID_STATE_TRANSITION` (409) at priority 40.5, ahead of rules 41/42 — routes_claims.py `CLAIM_ACTOR`/`actor_identity`
- §3.5 — revise — mismatch — OPEN_EVIDENCE_DEVELOPMENT against an `INTAKE_STARTED`/`INACTIVE` veteran is an invalid transition decided between rules 43 and 44; version wording de-universalised — routes_claims.py `drive_claim`
- §3.5 — insert — ambiguity — SUBMIT_FOR_REVIEW: unknown reviewer → `ERR_NOT_FOUND`; non-ACTIVE reviewer → `ERR_REPRESENTATIVE_NOT_ACCREDITED`, both ahead of the two segregation checks — routes_claims.py `drive_claim` (43.5)
- §3.5 — insert — ambiguity — MARK_READY effects enumerated — routes_claims.py `drive_claim`
- §3.5 — revise — mismatch — WITHDRAW waives `REQUESTED` items at half credit, which raises the completeness score; `INSUFFICIENT` items are untouched — routes_claims.py WITHDRAW + calc.py `refresh_item_points`
- §3.5 — insert — ambiguity — reopen is not driven from this endpoint — routes_claims.py `drive_claim` action set
- §3.6 — insert — ambiguity — `provider_name` is 1–160 characters — guard.py `STRING_RULES`
- §3.6 — insert — ambiguity — row defaults: `nexus_opinion_strength` stored as `NONE` when omitted, `received_on`/`status_reason` null, creation not gated on claim status, nested file listing filters only `status` and `evidence_type` — routes_claims.py `request_evidence`, `read_evidence_file`
- §3.6 — insert — ambiguity — the open-for-development gate's codes and ordering, plus RECEIVE's clock check as a third `ERR_INVALID_STATE_TRANSITION` — routes_claims.py `drive_evidence` (40 / 40.2 / 40.4)
- §3.6 — insert — ambiguity — `status_reason` is not cleared by RE_REQUEST or RECEIVE — routes_claims.py `drive_evidence`
- §3.8 — insert — ambiguity — recording a decision is open to any accredited `CountyOfficer`, unlike §3.5's preparer/reviewer-bound transitions — routes_claims.py `record_decision`
- §3.8 — insert — ambiguity — the ITF window is a signed gap, so an `intent_to_file_date` later than `filed_on` still anchors on the ITF — calc.py retro-award
- §3.8 — insert — ambiguity — `dependent_count` is read as it stands when the decision is recorded, not as at filing — calc.py retro-award

Deliberately left alone: `PATCH /cvso/claims/{id}` with an explicit `null` for `claimed_conditions` 500s (`len(None)` in `calc.required_points`) — documenting a crash or inventing a "null clears the field" rule would violate "never invent behavior"; §2.9's cross-reference to "(§3.7)" for the decision cascade should read §3.8 (PRD-internal typo, not an impl mismatch, and §2.x is pass 1's); local §3 mentions of the other rule-14 string bounds (owned by passes 1/3).

### Pass 3 of 3 — exams/decision reviews + state programs/outreach/reporting (subagent summary, verbatim)

Did not re-copy the file — every change a targeted `Edit`. Integrity: before `497 lines / 137350 bytes` → after `497 lines / 143981 bytes` (grew 6631 bytes, no line-count change). Ends with the `ERR_PROGRAM_POOL_EXHAUSTED` row.

Counts (slice): 23 ambiguity-pins, 7 mismatch-revisions, across 26 edit sites.

§3.7 — Examination sites and appointments:
- §3.7 — insert — ambiguity — `name` bounded 1–120 characters — guard.py:94
- §3.7 — insert — ambiguity — a site retune writes every carried key including an explicit `null`; omitted keys untouched — routes_exams.py:75-78
- §3.7 — revise — mismatch — booking instants are §2.4-shaped (fractional part optional) and are stored/echoed exactly as supplied, not "with three fractional digits" — routes_exams.py:115-116, store.py:104-107
- §3.7 — insert — ambiguity — booking imposes no claim-state precondition and no preparer/representative tie — routes_exams.py:87-97
- §3.7 — insert — ambiguity — a second `COMPLETE_PREP` is `ERR_INVALID_STATE_TRANSITION` 409 via the band-4 check — routes_exams.py:176-177
- §3.7 — insert — ambiguity — synthesized DBQ item also carries `requested_on` = logical-clock date, null `provider_name`/`status_reason`, and always earns the full on-time 17.5 points — routes_exams.py:209-221, calc.py:242-263
- §3.7 — insert — ambiguity — `NO_SHOW` before `ends_at` is `ERR_INVALID_STATE_TRANSITION` 409, not a temporal code — routes_exams.py:178-179

§3.9 — Decision reviews:
- §3.9 — insert — ambiguity — counselling a non-`DECIDED` claim is `ERR_INVALID_STATE_TRANSITION` 409; any accredited officer may counsel; a claim may carry several review rows — routes_exams.py:238-242
- §3.9 — insert — ambiguity — `days_remaining` re-derived on list reads too, keeps sliding on terminal rows, never clamped — views.py:9-11, calc.py:429
- §3.9 — insert — ambiguity — per-action role table (`ELECT`/`FILE` = CountyOfficer, `WITHDRAW` = VeteranClient), `ERR_UNAUTHORIZED` 403 at band-2 rule (12) ahead of required-field and 404; explicitly distinguished from §3.5's actor-identity/`ERR_INVALID_STATE_TRANSITION` mechanism; band-1 ownership evaluated earlier and action-blind — routes_exams.py:307-332, guard.py:245-250
- §3.9 — insert — ambiguity — a null `review_lane` on `ELECT` does not overwrite — routes_exams.py:358-359
- §3.9 — revise — mismatch — `FILE` reopens the claim only while it is still `DECIDED` — routes_exams.py:365-370
- §3.9 — insert — ambiguity — sibling-review case: review reaches `FILED` but claim/`reopen_count`/caseload untouched — routes_exams.py:366
- §3.9 — insert — ambiguity — `expired_review_ids` in ascending creation order — routes_exams.py:278

§3.10 — State programs and applications:
- §3.10 — insert — ambiguity — `program_code` 1–40, `program_name` 1–160 — guard.py:97-98
- §3.10 — revise — mismatch — `min_rating_pct` is not checked at filing, only at approval — routes_state.py:177 vs 243-249
- §3.10 — insert — ambiguity — `requires_wartime` defaults to false — routes_state.py:70
- §3.10 — revise — mismatch — `program_code` (and `program_type`, `fiscal_year`) are not retunable; the duplicate-code check can never fire on a retune — routes_state.py:28-29, 95-104
- §3.10 — insert — ambiguity — retune writes explicit nulls; omitted keys untouched — routes_state.py:101-103
- §3.10 — insert — ambiguity — `DENY` leaves gross/fee/net and `rating_at_approval_pct` at 0 — routes_state.py:285-288
- §3.10 — insert — ambiguity — the `CLAW_BACK` `reason` is validated but never stored; `issued_on` retained — routes_state.py:330-336

§3.11 — Outreach:
- §3.11 — revise+insert — mismatch/ambiguity — `location_name` 1–160; instants §2.4-shaped and echoed verbatim — guard.py:96, routes_state.py:368-369
- §3.11 — insert — ambiguity — the assigned representative's accreditation is never examined and the §3.1 revocation cascade leaves their planned events standing — routes_state.py:353, routes_registry.py:188-247
- §3.11 — insert — ambiguity — the hold-time conflict re-test excludes the event itself — routes_state.py:427-429
- §3.11 — insert — ambiguity — `HOLD`/`CANCEL` are CountyOfficer-only (a SystemAdmin can plan but not drive); `HOLD` before `starts_at` is `ERR_INVALID_STATE_TRANSITION` 409 — routes_state.py:404, 421-422

§3.12 — Quarterly reporting:
- §3.12 — insert — ambiguity — computing a `RETURNED` report leaves `status`/`return_reason` intact — routes_state.py:518-532
- §3.12 — insert — ambiguity — reopen retains `weighting_basis`, so `ERR_REPORT_NOT_COMPUTED` can never fire twice on a row — routes_state.py:599-601

Pass-1 sections pass 3 touched (flagged as required):
- §2.4 — revise — mismatch — "every datetime the server itself emits carries three fractional digits" was a false universal: caller-supplied `starts_at`/`ends_at` are echoed byte-for-byte. Narrowed to datetimes the server mints and named the two caller-supplied fields — routes_exams.py:115, routes_state.py:368
- §2.7 — insert — ambiguity — §2.7's "carried to N decimal places" is about rounding, not the wire form, so it was silent rather than wrong. Added one sentence: rounded percentages/scores travel as JSON numbers in shortest exact form, so `weight_points` 20.00 → `20.0`, `performance_score` 100.0 → `100.0` — calc.py:105-107, 478
- §2.11 rule (71) — revise — mismatch — removed `PATCH /cvso/state-programs/{id}` from the duplicate-`program_code` rule; it can never fire there. Rule 70's PATCH claim is correct (routes_registry.py:112-118), so the asymmetry is real and now stated.

Forwarded-lead disposition: (1) per-action role gate — acted on in §3.9 including the band-2 rule (12) position and the explicit "not the same rule as §3.5"; (2) `days_remaining` negative/terminal — partially pinned already, list reads and terminal rows acted on; (3) `reopen_count` / reopen driven from `FILE` — verified already pinned in §3.9/§3.8, added the `still DECIDED` guard and the sibling-review case; (4) float emission vs §2.7 — acted on with one §2.7 sentence; (5) string bounds in owning §3 subsections — acted on for `name` (§3.7), `program_code`/`program_name` (§3.10), `location_name` (§3.11).

Sanity check: `## 1.`–`## 5.` all present (lines 3, 11, 184, 351, 428); §4 table = 70 data rows; §5 table = 64 data rows.

Deliberately left alone: §3.10's "Six checks apply" list order (§2.11 already pins global order by rule number, and the §3.10 prose does not claim to be a precedence list); §3.12's submit prose listing `ERR_REPORT_NOT_COMPUTED` before the accreditation gate (actual precedence 40 < 42 < 48 < 54 already determined by §2.11's bands); §2.3's boolean filter tokens being case-insensitive in impl (pass 1's section, wording defensible).

### Orchestrator verification of Step 9

- `wc -l -c`: `PRD.md` 497 / 122249 · `PRD_FINALIZED.md` 497 / 122249 · `PRD_COMPLETED.md` 497 / 143981 → +21,732 bytes, +17.8% over the source. Never smaller than the source at any pass boundary (122249 → 128431 → 137350 → 143981), so no pass truncated a predecessor's work.
- `cmp PRD_FINALIZED.md PRD_COMPLETED.md` → files differ, i.e. the scan genuinely ran (a byte-identical `PRD_COMPLETED.md` would mean the pass never happened).
- All five top-level sections present at lines 3, 11, 184, 351, 428. §4 endpoint table 70 data rows; §5 error table 64 data rows. Final line is the complete `| ERR_PROGRAM_POOL_EXHAUSTED | 409 |` row — no truncation.
- Step 9 edited only `PRD_COMPLETED.md`; `implementation/`, `test_suite/` and `test_helpers/` were untouched, so the Step 7 green sweep (8/8 rounds, 214/214) remains the valid evidence of a passing implementation.

## Pipeline complete — 2026-09-05T11:36:00.000Z

All nine steps finished. Final state: 3 scaffold YAMLs · `workspace/PRD.md` (497 lines) · `workspace/PRD_FINALIZED.md` (byte-identical, legitimate — Step 7 made zero implementation fixes) · `workspace/PRD_COMPLETED.md` (497 lines / 143981 bytes, 53 ambiguity-pins + 19 mismatch-revisions across three module-partitioned passes) · `test_helpers/` (9 files, 3388 lines) · `test_suite/` (19 files, 214 tests) · `workspace/implementation/` (14 modules, ~4000 lines, 70 endpoints) · `results.1..8.json` all 214/214.
