# Worklog — task_2884_ballot_measure_petition_signature_verification

## Step 1: Create task directory — 2026-09-05T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2884_ballot_measure_petition_signature_verification` and its `workspace/` subdirectory. Index 2884 was pre-assigned by the orchestrating command; no scan of `./tasks/` was performed.

## Step 2: Generate scaffold — 2026-09-05T13:39:00.000Z

All three scaffold artifacts for task 2884 are complete and lint-clean.

## Files (all in `/home/ubuntu/github/CodingPRD/tasks/task_2884_ballot_measure_petition_signature_verification/`)
- `SCAFFOLD.yaml` — 2,987 lines, §1.0–§1.7 only (top-level keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles — neither design key present)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 3,593 lines, single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 5,190 lines, single key `scaffold_corner_design`

## Surface
12 entities (VerificationStandard, County, VoterRecord, Petition, Circulator, CirculationAssignment, SignatureBatch, SignatureRecord, VerificationRound, CurePeriod, Challenge, FraudReferral), 65 endpoints (api_prefix ""), 11 calculations, 15 ordered validation priorities, 67 error codes, 7 roles (CountyClerk `entity_backed:County`, CirculatorAgent `entity_backed:Circulator`), 2 OCC rules, profile: compliance_audit + ledger_reconciliation, cyclic state machines, immediate consistency, expert_plus.

## §1.8 — 23 instances over all 9 rule_ids
dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2.

## §1.9 — all nine guide sections, 34 real instances + 35 already-covered stubs
entities 4/0, state_machines 7/9, calculations 3/8, validations 9/9, endpoints 2/3, errors 3/0, rbac 4/0, complexity_layers 1/6, consistency_model 1/0. Every stub cites an existing §1.8 instance by name; 69 instance names are unique and none collide with §1.8. A closing comment maps all 67 error codes to their triggering instance — verified programmatically: 0 codes unreferenced.

## Verification
`scaffold_lint.py` final run: `§1.5 endpoints declared: 65 / §1.1 entities: 12 / §1.8 instances: 23 / §1.9 instances: 34 / Calls scanned: 1373` → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` All three files `yaml.safe_load` cleanly.

## Design adjudications made this session
- **Cure walk**: ERR_CURE_LIMIT_REACHED is probed with C2 still OPEN and the clock exactly at its exclusive `deadline_at`, so the priority-14 overlap rule and the priority-10 state gate both pass and only the priority-15 count gate can fire. Both arms of ERR_SUPPLEMENTAL_WITHOUT_CURE_PERIOD are probed on the same endpoint; recorded reasoning: since supplemental and ordinary batches share `POST /signature-batches`, the priority-10 petition gate must admit creation in CURE_PERIOD, which makes the priority-13 coherence clause the only possible refusal for either shape. Targets differ by design (shortfall 2 @ 5000 bps → 4 raw; shortfall 1 @ 10000 bps → 1 raw).
- **ERR_CURE_NOT_ELIGIBLE** needs a FULL_CHECK latest closed round (a RANDOM_SAMPLE projection is frozen on the round and cannot drop): the petition enters CURE_PERIOD legitimately at the inclusive floor (4 == 5×8000/10000), a batch invalidation voids two lines to drop below it, and reinstatement makes the identical call succeed.
- **Priority ordering pinned where two rules compete**: revoked-circulator bar (12) outranks the fraud-named-batch bar (13); ownership (7) outranks state (10) on `submit`; role (3) outranks existence (5) — every RBAC exclusivity probe uses an unresolvable path id to prove it; existence (6) outranks linkage (13) for `cure_period_id`; body-FK order is walked one key at a time to show petition_id → circulator_id → county_id.
- **SosAdmin is not a superuser** — nine of the 23 exclusivity denials are administrator denials (format review, tally, title-summary, proponent ops, affidavit, escalate).
- **Lint-driven field corrections**: `paid_disclosure_document_id` → `disclosure_document_id`/`paid_disclosure_on_file`; `valid_count` → `sampled_valid_count`; dropped a non-existent `circulator_version_at_assignment` capture; replaced a literal `expected_petition_version: "1"` with a server-issued `${pet_v}` (rule (e)), adding a minimal setup and adjusting the "nothing was created" assert accordingly.
- **Directive-leak strip**: `SCAFFOLD.yaml`'s `scenario` key had the generator directive line "Generate task harder than expert level!" as its first line, which reaches PRD.md downstream. I removed that one line (and its blank line); the domain description itself is byte-identical to the supplied text, and neither design file ever contained the directive.

Orchestrator verification: `grep -rn "harder than expert"` over the task dir returns nothing — no directive leak.

## Step 3: Copy shared files — 2026-09-05T13:40:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T13:56:00.000Z

PRD complete and verified.

**Deliverable:** `workspace/PRD.md` — **506 lines / 15,235 words**, written incrementally (one `Write` + heredoc `cat >>` appends), ending cleanly at the last row of the §5 error table. No audit footer, no report files written.

**Sections emitted**
- §1 Introduction (3 paragraphs: statutory promise, seven misaligned constituencies + segregation of duties, three technical constraints)
- §2.1 Actors/RBAC (all 7 roles, identity translation, ownership codes) · §2.2 verbatim response-structure block · §2.3 Pagination · §2.4 Logical Election Clock · §2.5 Jurisdiction Standard (16 `VerificationStandard` fields + every fixed constant) · §2.6 bps/cents/millicents rounding discipline · §2.7 Common Resource Properties (9 full vs 3 config-only types) · §2.8 Left-to-right identifier resolution (12 not-found codes, 12 path params, body FK order) · §2.9 Optimistic concurrency (both rules) · §2.10 Cascades/compensation/two conserved ledgers · §2.11 Order of evaluation (all 15 priorities with error IDs, statuses, applies_to scopes) · §2.12 Segregation of duties
- §3.1 jurisdiction config · §3.2 draft→cleared · §3.3 circulator registration & assignments · §3.4 batches/lines/affidavit · §3.5 pool, sample draw, line validation · §3.6 tally: projection, sufficiency bands, county distribution, batch cost, tiered invoice · §3.7 cure periods & supplemental signatures · §3.8 determination, challenges, court review · §3.9 fraud referrals, circulator discipline, compensating corrections
- §4 Endpoint Definitions (65-row Method/Path/Description/Roles table) · §5 Error Code Catalogue (67 rows)

**Hard Contract results**
- **Contract 1 (Field-Name Coverage) — PASS**, two independent passes. Pass 1: 145-name pre-enumerated set (117 entity fields + endpoint inputs + path params + computed-read output keys) → 0 missing. Pass 2: 134-name set re-derived fresh from the scaffold with literal backticked-name substring search → 0 missing. Fix applied mid-verification: the six path-only identifiers (`assignment_id`, `challenge_id`, `referral_id`, `round_id`, `signature_record_id`, `voter_record_id`) appeared only inside full path strings, so §2.8 now names all twelve path identifiers as standalone backticked tokens.
- **Contract 2 (Rule Coverage) — PASS**. All 78 transitions across 10 state-machine dimensions covered (every from/to state name appears as backticked prose; petition-status machine walked transition-by-transition, including both documented cycles `FULL_CHECK → FULL_CHECK` and `CURE_PERIOD → CURE_PERIOD`, and the `PENDING_CERTIFICATION` ↔ `PENDING_FAILURE` court flip). All 11 calculations documented with their formulas, rounding directions, variants (pooled/stratified draw, pooled/stratified projection, provisional/adjudicated credibility) and worked examples; every named constant value appears in prose. All 15 validation priorities with error IDs, HTTP statuses and applies_to scopes. Both concurrency rules. All 67 error IDs appear in prose or catalogue, and the PRD contains no `ERR_` token absent from the scaffold. No forbidden fuzzy words remain (the one earlier "roughly" was removed).
- **Contract 3 (§3 Path Purity) — PASS**. Zero backticked tokens in §3 begin with `/`, are a bare HTTP method, or combine method+path (checked mechanically over the whole §3 range).

**Coverage confirmation:** 65/65 endpoints, 67/67 error codes, 11/11 calculations, 15/15 validation priorities, 12/12 entities, 7/7 roles, 78/78 transitions.

**Adjudications (2 scaffold inconsistencies resolved)**
1. `GET /petitions/{petition_id}/verification-invoice`'s description carried the sentence about `counties[]` elements (`county_code`, `distribution_minimum`, `credited_count`, `qualifies`), which contradicts its declared invoice output and belongs to `GET /petitions/{petition_id}/distribution-report`. Adopted: distribution report returns `petition_id`, `required_qualifying_counties`, `qualifying_county_count`, `counties[]`; invoice returns `petition_id`, `gross_cents`, `tier`, `discount_bps`, `discount_cents`, `subtotal_cents`, `surcharge_cents`, `total_cents`.
2. The `PENDING_FAILURE → FAILED` transition lists only the challenge and segregation preconditions, while validation priority 15 places both the fraud-referral gate and the county-distribution gate at determination time. Adopted: `ERR_FRAUD_REFERRAL_OPEN` applies to any determination; `ERR_COUNTY_DISTRIBUTION_UNMET` applies only to the `CERTIFY` path (stated explicitly in §2.11 and §3.8).

Neither design yaml was opened, grepped or referenced; no sibling task directory was read.

Orchestrator truncation check (per the known doc-generator failure mode): `wc -l` = 506, `tail` ends at the final row of the §5 error-code table — a real section boundary, not mid-sentence. Section headings §1 through §5 all present and in order. Not truncated; no regeneration needed. Re-verified integrity a second time after Steps 5/6 launched (md5 18605c9e78244e31826d020d851be317, still 506 lines).

## Step 6: Generate implementation — 2026-09-05T14:33:00.000Z

The implementation is complete and verified.

## Files written

`workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `services/calculations.py` | 450 | all 11 PRD calculations |
| `routes/petitions.py` | 409 | petition lifecycle, rounds/cure/challenge openers, reports |
| `db.py` | 312 | in-memory store, logical clock, instant formatting, lookups |
| `routes/batches.py` | 305 | batches, lines, affidavit verify, invalidate/reinstate, line validation |
| `routes/circulators.py` | 276 | registration ladder, suspend/reinstate/revoke, assignments |
| `routes/config.py` | 211 | clock, standards, counties, voter records |
| `routes/challenges.py` | 201 | challenges, court review, fraud referrals |
| `services/verification.py` | 184 | 5-step line cascade, tally, round void |
| `response.py` | 141 | envelope, pagination, filtering, deterministic sort |
| `services/cascades.py` | 139 | 4 cascade levels + compensating operations |
| `validation.py` | 124 | body/type/enum/instant coercion |
| `errors.py` | 106 | 67 PRD error ids → HTTP status catalogue |
| `middleware.py` | 73 | auth priority 1–3, ownership/identity binding |
| `app.py` | 64 | app factory, 6 blueprints, error handlers, `PORT` bind |
| `start.sh` | 10 | guarded pip, `exec python3 app.py` (foreground, `0.0.0.0:$PORT`) |
| `requirements.txt` | 1 | `flask>=3.0.0` |

3109 lines total. No `__pycache__` left behind; grep audit confirms zero filesystem/SQLite/JSON persistence and zero seeded entities — every list endpoint returns `total_count=0` on a fresh boot (verified explicitly across all 12 collections).

## Endpoints: 65/65

The Flask URL map yields exactly 65 application `(method, path)` pairs, matching the PRD's 65 (a 66th pair is Flask's built-in `/static/<path:filename>`). 12 creators return 201, the rest 200, per SCAFFOLD.yaml.

## Calculations: 11/11 implemented and numerically verified

Three scripted end-to-end passes (`/tmp/task_2884_impl/smoke{,2,3}.py`, ~150 assertions, all green) reproducing every worked example in the PRD:

- **PRD flagship divergence reproduced exactly**: identical data (2 accepted lines in each of 2 counties, one invalid in the first) → POOLED projects **4**, STRATIFIED projects **3**, with the round-level `validity_rate_bps` legitimately disagreeing with the stratified projection (7500 vs 3).
- Sample sizing: POOLED draws 2, STRATIFIED draws 4 from the same pool; `FULL_CHECK` size == pool size; systematic interval walk selects the documented positions.
- Batch cost: 1 line @4750 millicents → 5c; 2 lines → 10c (half-up on 9.5).
- Invoice: gross 10 → `TIER_NONE`/0/10/1/**11**; gross 20 → `TIER_A`/1000bps/2/18/1/**19**.
- Credibility: fresh 10000; 0 valid + 1 invalid → 5000; 1 valid + 1 invalid → **7500**; substantiated referral → 8000.
- Threshold, cure target, distribution minimum/credited, determination gates, all 5 line-validation outcomes including `manual_match_override`.
- **Conservation invariants hold byte-identically**: invalidate → reinstate restores all 7 petition ledger fields; round void restores line statuses, batch statuses, batch costs, petition cost/projection, and returns the petition to `SIGNATURES_FILED`.

## Validation priority chain

Implemented as PRD §2.11's 15 tiers in this exact order (§2.11 treated as normative over §3 narration): missing headers (401) → unknown role (401) → role not authorised (403) → body shape (400) → path ids (404) → body FKs (404) → ownership (403) → segregation of duties (403) → optimistic concurrency (412) → state (409) → uniqueness (409) → statutory (422) → linkage (409) → windows (409) → counting (409). Verified live for each tier.

## Adjudications where the PRD was ambiguous

1. **`ERR_AFFIDAVIT_NOT_SWORN` is scoped to the circulator affidavit endpoint only** — the PRD phrases it as "the affidavit request carries `sworn == false`", so a batch filed with `affidavit_signed: false` is accepted and merely recorded.
2. **`verified_valid_count` after a sample round** — set to 0 (not face value) when the latest closed round is a `RANDOM_SAMPLE`, since only `FULL_CHECK`/`CURE_RECHECK` produce a verified count. Face-value recompute broke the invalidate→reinstate conservation invariant.
3. **Duplicate-keeper order independence** — a `PENDING` line's *claimed* voter number counts as its staked voter, making keeper selection independent of validation order.
4. **Batch invalidate/reinstate is credibility-neutral** — voiding uses `status_before_void`, so the circulator is deliberately *not* recomputed or `touch()`ed there; doing so would bump `version` on an undeclared mutation and corrupt `expected_circulator_version` OCC.
5. **`format_review_round` increments on both outcomes** of the format decision (APPROVE and REJECT).
6. **Config entities carry no `updated_at`/`version`** (only the 9 full resource types do, per §2.4); `version` bumps at most once per resource per request via a request-scoped touch set.
7. Round resources expose no per-county stats field — the PRD never declares one, so stratum rates are computed on demand for projection and distribution credit.

## One operational note for the harness

`start.sh` uses `exec`, but when launched under this sandbox's shell wrapper the Python process ended up as a *child* that survived a kill of the recorded `$!` and kept holding the port. The child does inherit the launcher's process group, so `prd-bench-local-run`'s group kill will reap it correctly. Anyone smoke-testing by hand should kill the PID reported by `ss -lptn | grep <port>`, not `$!`.

## Step 5: Generate unit tests — 2026-09-05T16:29:00.000Z

All 18 test files are complete and the full-suite audit is clean. Final state:

## Files written (all at the TASK ROOT, nothing under `workspace/`)

`test_helpers/` — 2710 lines, 9 modules (`__init__.py` 53, `api_client.py` 315, `api_errors.py` 147, `assertions.py` 407, `constants.py` 64, `factories.py` 265, `fixtures.py` 972, `test_users.py` 79, `types.py` 408).

`test_suite/` — `conftest.py` 88 plus 18 test modules, 120 tests total:

| file | lines | tests |
|---|---|---|
| test_01_projection_variants_and_credibility | 303 | 5 |
| test_02_cost_and_sample_formulas | 287 | 7 |
| test_03_petition_and_batch_state_machines | 301 | 7 |
| test_04_discipline_cascades | 205 | 4 |
| test_05_rejection_priority_order | 262 | 6 |
| test_06_gate_boundaries | 303 | 7 |
| test_07_cross_entity_state_gates | 290 | 6 |
| test_08_temporal_intervals | 271 | 5 |
| test_09_compensating_ledgers | 222 | 4 |
| test_10_configuration_resources_and_petition_intake | 428 | 8 |
| test_11_lifecycle_initial_states_and_transition_gates | 845 | 13 |
| test_12_derived_arithmetic_and_immediate_consistency | 518 | 8 |
| test_13_uniqueness_linkage_and_window_rejections | 653 | 9 |
| test_14_challenge_discipline_and_cure_rejections | 764 | 8 |
| test_15_clock_stamping_list_filters_and_version_echoes | 676 | 6 |
| test_16_auth_shape_and_not_found_rejections | 543 | 7 |
| test_17_role_exclusivity_and_shared_operations | 428 | 5 |
| test_18_ownership_and_segregation_of_duties | 484 | 5 |

## Design-index coverage (machine-audited against both yamls)

- Every test carries exactly one `Design:` tag: 120 tests / 120 tags, no untagged, no dual-tagged, no tag pointing at a non-existent instance, no tag pointing at an `excluded_because:` stub.
- Queue A (difficulty): **23 / 23** instances, 51 tests, every instance with >=2 tests (test_01–test_09).
- Queue B (corner): **34 / 34** non-stub instances, 69 tests (test_10–test_18) — entities 4, state_machines 7, calculations 3, validations 9, endpoints 2, errors 3, rbac 4, complexity_layers 1, consistency_model 1.
- **Skips: none.** No instance failed the PRD-first two-condition filter outright.

## Adjudications made (recorded in the affected module docstrings)

1. `SOS-POOLED-A`/`SOS-STRAT-A` → `SOS-POOL`/`SOS-STRA` (8-char `jurisdiction_code` cap).
2. List-order assertions replaced by count/membership/partitioning: §2.3 pins creation-ascending order but the frozen clock leaves same-test ties unresolved, so `$.data[0]` positions are not uniquely derivable.
3. Initial `version` asserted as a type/increment relation rather than the literal `1` (PRD does not pin the seed value).
4. Pre-tally `checked_signature_count` left unasserted (not uniquely derivable from the PRD).
5. `measure_subject_codes: ["ENV"]` in three recipes corrected to `ENVIRONMENT` (the declared code) — `endpoints`, `cure_eligibility_floor_blocks_reopen_after_ledger_drop`, `entity_backed_and_owner_scoped_writes_denied_to_non_owners`.
6. The `endpoints` recipe's `updated_at`/`version` assertions on `County`/`VoterRecord` dropped: §2.7/§3.1 state those fields are absent from configuration resources.
7. The `county_distribution_gate_blocks_certification` recipe's non-participating-county row dropped per §3.6.
8. `entity_backed_and_owner_scoped_writes_denied_to_non_owners` asserts `ok_line_status == VALID` but its own setup never closes circulation or opens a round, so the line would not be in a sample; test_18 adds the `file-signatures` + census `RANDOM_SAMPLE` round before the owning clerk validates.

## Verification run

`python3 -m compileall -q test_helpers test_suite` → OK; per-file `py_compile` on every file; `pyflakes` clean across the suite (the only remaining warnings are the deliberate re-exports in `test_helpers/__init__.py`); `__pycache__` removed. `workspace/` contains only `INSTRUCTION.md`, `PRD.md` and `implementation/` — no `test_helpers`/`test_suite` stray copies, `workspace/implementation/` was never read or written, and `worklog.md` was not touched.

Orchestrator verification: `test_helpers/` and `test_suite/` both confirmed present at the task root; no stray copies found anywhere under `workspace/`.

Orchestrator note: Steps 5 and 6 ran concurrently as required. The impl generator was additionally given an explicit prohibition on reading `test_suite/`/`test_helpers/`, and reported it never read `workspace/implementation/`'s counterpart directories; the test generator confirmed it never read `workspace/implementation/`. Isolation held in both directions.

## Step 7: Run tests and iterate — 2026-09-05T17:22:00.000Z

All 8 rounds pass 120/120. Done.

## Summary

**Iterations run:** 2 sweeps (baseline + verification). Baseline was fully deterministic — 113/120 in all 8 rounds with the identical 7 failures, so no flakiness or load-induced noise to disentangle.

**Root cause:** all 7 failures were test-artifact bugs. **Zero changes were made to `implementation/`** — the Flask service was already PRD-faithful on every one of these rules (I verified its pool ordering, draw sizing, systematic walk, pooled projection, and sufficiency banding line-by-line against §3.5/§3.6 before concluding this).

**Tests deleted:** none. One assertion was removed under STEP 1c partial-coverage handling:
- `test_18…::test_the_examiner_who_tallied_the_deciding_round_cannot_certify` — dropped `assert held["certified_at"] is None`. **COMPUTED-FIELD / FIELD SILENCE:** `certified_at` appears nowhere in PRD.md; §2.4's enumeration of every system-assigned instant and §3.2's list of a fresh petition's null fields both omit it. The test's core segregation-of-duties assertions (§2.12, verbatim) were kept intact. Notably the field was *not* added to the implementation — that would have violated the "no response field without a verbatim PRD sentence" rule.

**Fixes applied to `test_helpers/`:** none — the fixtures, factories and role-header builders were all PRD-consistent.

**Fixes applied to `test_suite/`:**
- `test_05_rejection_priority_order.py` — setup bug: the four-line world had all voters `ACTIVE`, so the sample came back 100% valid and projected 4 against upper gate 3 → `SUFFICIENT`, never reaching the `FULL_CHECK` state the §2.11 priority test needs. Set VA3 (drawn at pool position 2) to `INACTIVE` so rate is 5000 and projection lands 2, strictly between gates 1 and 3. Added the intermediate arithmetic assertions.
- `test_06_gate_boundaries.py`, `test_08_temporal_intervals.py` — three raw string `==` comparisons demanded a client-supplied instant (`signed_on`, `effective_from`) be echoed back widened to `.000Z`. **PRD is silent on canonicalising client-supplied instant width:** "three fractional digits" appears only for `api_request_timestamp` (§2.2) and `created_at`/`updated_at` (§2.7); §2.7's closing sentence says client-supplied datetimes merely "are ISO 8601 UTC instants", which `2026-08-01T00:00:00Z` already is. Switched to `assert_instants_equal` / `parse_instant` — exact value equality preserved, only the uncovered width claim dropped. This also makes these three the last holdouts consistent with the other 117 tests, which already use `assert_instants_equal` throughout.
- `test_13_…py` (two fixes) — (a) `determination is None` on an OPEN round contradicted PRD §3.6 verbatim ("a round's `determination` sits at `PENDING` until it is tallied") *and* the suite's own `assert_verification_round` enum; corrected to `== "PENDING"`. (b) `raw_signature_count == 0` after a refused `file-signatures`; petition_b already held one verified line, and §3.4 says adding a line recomputes the counter, so the correct unchanged value is 1.
- `test_14_…py` — `restored["status"] == "AFFIDAVIT_VERIFIED"` ignored that a RANDOM_SAMPLE then a FULL_CHECK round had advanced the batch to `FULLY_CHECKED` before invalidation; §3.9 requires verbatim restore from `status_before_invalidation`, so `FULLY_CHECKED` is correct.

**Final sweep evidence** (`results.$i.json`): round 1 — 120/120, round 2 — 120/120, round 3 — 120/120, round 4 — 120/120, round 5 — 120/120, round 6 — 120/120, round 7 — 120/120, round 8 — 120/120. Union of failures across all rounds: empty.

`worklog.md` untouched by the subagent; its scratch was confined to `/tmp/task_2884_fix/`.

Orchestrator verification: independently parsed all 8 `workspace/implementation/results.*.json` and confirmed `passed == total == 120` in every round. The sweep ran under `setsid nohup bash workspace/sweep.sh` (a pre-written script file rather than an inline one-liner, to avoid the known `--start-command` quote-injection failure), and the orchestrator polled for `results.*.json` rather than trusting the launcher's early return.

Orchestrator Step 8 decision: the pipeline overview's shorthand ("skipped if Step 7 had 0 implementation/ fixes") and Step 8's own detailed skip condition (all four of deletions / test_suite fixes / test_helpers fixes / implementation fixes must be 0) disagree here — implementation fixes were 0, but there were 5 `test_suite/` fixes plus one assertion removal. I am treating the detailed condition as authoritative and RUNNING Step 8, because two of those test_suite corrections are explicit PRD-silence findings that Step 8 exists to pin: the client-supplied-instant width silence (§2.7) and the absent `certified_at` field. Skipping would discard exactly the signal Step 8 consumes.

## Step 8: Finalize PRD — 2026-09-05T17:27:00.000Z

`PRD_FINALIZED.md` is written. Two edits, both traced to `<step_7_diff>` items.

## Line counts
- `PRD.md`: 506 lines; `PRD_FINALIZED.md`: 506 lines — 0% line delta (both edits are in-line revisions of existing paragraphs; file ends at the same real boundary, the `ERR_FRAUD_REFERRAL_OPEN` row of the §5 error table).

## Changes
- **§2.7 (Common Resource Properties, closing datetime sentence) — revise** — pinned instant *rendering*: server-stamped/derived instants carry exactly three fractional digits, while a client-supplied instant (`signed_on`, `effective_from`, `effective_to`, `registration_date`) is stored and echoed back byte-for-byte as supplied and never widened to `.000Z` — `implementation/validation.py:77-84` (`as_instant` returns the raw string), `routes/batches.py:162`, `routes/circulators.py:233-234`, `routes/config.py:179`; contrast `db.py:79-88` (`fmt_instant`).
- **§3.8 (Determination, first paragraph) — insert** — pinned that issuing a determination writes only the petition's `status` (plus the §2.7 `updated_at`/`version` refresh): no `certified_at`-style instant and no stored `determination` field on the petition — `implementation/routes/petitions.py:380-387`.

## Per-edit pre-edit search log

**Edit 1 — §2.7 instant width**
- (a) Subject: how every datetime field is formatted on the way out, both client-supplied and server-assigned.
- (b) Enumerated/read: `validation.py:77-84` (`as_instant` — echoes the raw string, parses only for comparisons); `db.py:79-121` (`fmt_instant` 3-digit renderer, `parse_instant` permissive reader); every `fmt_instant`/`now_str` callsite via grep — `db.py:142,159,183` (`created_at`/`updated_at` on both resource kinds), `routes/petitions.py:161,163,301,302,343,344` (`cleared_at`, `circulation_deadline`, `opened_at`, `deadline_at`, `filed_at`, `review_deadline_at`), `routes/batches.py:87` (batch `filed_at`), `routes/circulators.py:93,131` (`training_completed_at`, `affidavit_filed_at`); every client-instant store site — `routes/batches.py:133,162`, `routes/circulators.py:192-195,233-234`, `routes/config.py:164-165,179`, plus `routes/config.py:27` (`current_utc`, parsed only, never echoed).
- (c) Adjustment: worded the server side as "every instant the server stamps **or derives** for itself", explicitly naming the derived deadlines (`circulation_deadline`, `deadline_at`, `review_deadline_at`) because those are not in §2.4's system-assigned-instant list yet also go through `fmt_instant`. Deliberately did **not** touch what input formats are *accepted* (impl's `parse_instant` also tolerates offsets, missing seconds and a space separator), so the new sentence makes no claim §2.11's shape check would contradict; "stored and echoed back exactly as the caller wrote it" stays true even for those permissive forms.

**Edit 2 — §3.8 determination writes**
- (a) Subject: what the determination endpoint mutates on the petition (and whether any certification timestamp/determination field exists).
- (b) Enumerated/read: `routes/petitions.py:360-387` (`issue_determination` — sets `status`, then `touch`); `routes/petitions.py:46-70` (the full petition field set at creation — no `certified_at`, no `determination`); grep for `certif`/`CERTIF`/`certified_at` across all of `implementation/` (only status-string literals; the field does not exist anywhere); `db.py:167-184` (`touch` → `updated_at` + `version`); the other writers of terminal-ish petition state for consistency — `routes/challenges.py:79-82` (court ruling flips `PENDING_*`, stores `ruling` on the *challenge*), `services/verification.py:116-144` (tally sets petition `status`), `services/verification.py:182-183` (void restores `SIGNATURES_FILED` but never touches `CERTIFIED`/`FAILED`).
- (c) Adjustment: scoped the claim to the petition only ("writes nothing **onto the petition**") so it cannot be read as denying the `ruling`/`voided_reason`/round writes that other operations legitimately make, and carved out the `updated_at`/`version` refresh explicitly, since `touch(petition)` does fire on this path.

No PRD change was made for the four remaining `<step_7_diff>` items — the OPEN-round `determination == "PENDING"` fix, the `raw_signature_count` fix after a refused `file-signatures`, the `FULLY_CHECKED` restore-verbatim fix, and the test_05 setup/arithmetic fix — because PRD.md already determines each verbatim (§3.6 closing sentence; §3.4 recompute rule; §3.9 / §2.10 verbatim restoration; §3.5 interval walk and §3.6 banding), and Step 7 made zero changes to `implementation/`.

Orchestrator verification: `cmp` confirms `PRD_FINALIZED.md` is NOT byte-identical to `PRD.md` (112666 vs 111550 bytes, same 506 lines — two in-paragraph revisions), and it ends at the same real section boundary (final `ERR_FRAUD_REFERRAL_OPEN` row of the §5 table), so it is not truncated.

Orchestrator plan for Step 9: to avoid the known failure where a single Step 9 subagent's scan silently never runs (leaving `PRD_COMPLETED.md` byte-identical to its source), Step 9 will be executed as THREE SEQUENTIAL passes over one shared `PRD_COMPLETED.md`, partitioned by implementation module. Pass 1 performs the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 must not re-copy, only edit in place. Partition: pass 1 = infrastructure + config/circulator routes (`app.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `validation.py`, `routes/config.py`, `routes/circulators.py`); pass 2 = `routes/petitions.py`, `routes/batches.py`, `routes/rounds.py`; pass 3 = `services/calculations.py`, `services/verification.py`, `services/cascades.py`, `routes/challenges.py`.

## Step 9: Complete PRD — 2026-09-05T18:05:00.000Z

Executed as THREE SEQUENTIAL module-partitioned passes over one shared `workspace/PRD_COMPLETED.md`. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden to re-copy and each verified the prior passes' sentinel phrases survived. Final artifact: 506 lines / 130,687 chars, **+18,021 chars over `PRD_FINALIZED.md`**. 51 edits total — 36 ambiguity-pins, 13 mismatch-revisions (plus 2 structural restorations).

### Pass 1 — infrastructure + config/circulator routes (app.py, db.py, errors.py, middleware.py, response.py, validation.py, start.sh, routes/config.py, routes/circulators.py)

`cp PRD_FINALIZED.md PRD_COMPLETED.md` performed. 19 edits: 16 ambiguity-pins, 3 mismatch-revisions. 112,666 → 117,547 chars.

- §2.1 — revise — mismatch — a header holding only whitespace now explicitly counts as absent (`ERR_MISSING_AUTH_HEADERS`) — middleware.py:27
- §2.2 — insert — ambiguity — `api_request_id` is `req_` plus exactly 20 upper-case-alphanumeric characters — response.py:20
- §2.2 — insert — mismatch — `api_request_timestamp` is taken from real wall-clock UTC and is deliberately independent of the §2.4 logical clock — response.py:23-28
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` are 400; an empty-string value falls back to the default — response.py:74-96
- §2.3 — insert — ambiguity — because the logical clock stands still, `created_at` ties are common and are broken by creation sequence (insertion order) — response.py:135
- §2.3 — insert — ambiguity — `total_count` is the pre-window filtered size; `has_more` is `offset + len(page) < total_count` — response.py:56
- §2.3 — insert — ambiguity — undeclared query parameters are ignored; an uninterpretable bool/int filter value yields an empty page, not a 400 — response.py:108-127
- §2.4 — insert — ambiguity — the clock-setting call answers HTTP 200 with an empty `data` object — routes/config.py:29
- §2.5 — revise — ambiguity — `cure_eligibility_floor_bps` is any whole number >= 0 with no upper bound (the only unbounded bps parameter) — routes/config.py:68-70
- §2.7 — insert — ambiguity — `version` starts at 1 and advances exactly once per request per resource even when one request mutates it several times, while `updated_at` is restamped by each mutation — db.py:148, db.py:167-184
- §2.7 — insert — ambiguity — accepted client instant spellings (`T` or space, lower-case `t`/`z`, optional seconds, optional zone read as UTC, 1-9 fractional digits, numeric offsets converted to UTC but echoed verbatim) — db.py:91-121
- §2.11 item 4 — insert — ambiguity — four global shape conventions: booleans never accepted for integers, "uppercase" means no lower-case letter, an absent body reads as `{}` while a non-object body is a 400, unrecognised body fields ignored — validation.py:15-73
- §3.1 — revise — ambiguity — `county_code` is 2-12 characters carrying no lower-case letter (digits admissible) — validation.py:50, routes/config.py:122
- §3.3 — insert — mismatch — registering a paid circulator with a null `employer_name` succeeds; the defect surfaces only via `paid_disclosure_on_file` and the affidavit gate — routes/circulators.py:42-60
- §3.3 — insert — ambiguity — the paid-disclosure write has no state precondition (accepted in every status, `REVOKED` included) and omitting `employer_name` leaves the stored value intact — routes/circulators.py:99-115
- §3.3 — insert — ambiguity — `sworn` is required, so omission is a 400 and `ERR_AFFIDAVIT_NOT_SWORN` is reserved for an explicit `false` — routes/circulators.py:122-130
- §3.3 — insert — ambiguity — assignment creation refuses a non-`REGISTERED` (incl. `REVOKED`) circulator with `ERR_INVALID_CIRCULATOR_STATE`, not a 422 signal — routes/circulators.py:217-218
- §3.3 — insert — ambiguity — assignment creation places no precondition on the petition's own `status` — routes/circulators.py:206
- §3.3 — insert — ambiguity — terminating an already-`TERMINATED` assignment is `ERR_INVALID_PETITION_STATE` (no assignment-state signal exists) and a `Proponent` may terminate only an assignment whose petition it owns — routes/circulators.py:271-273
- §3.9 — revise — ambiguity — credibility is also recomputed once at circulator revocation (call site only; the formula belongs to pass 3) — routes/circulators.py:178

### Pass 2 — petition/batch/round routes (routes/petitions.py, routes/batches.py, routes/rounds.py)

Confirmed no re-copy; pass 1's sentinels all survived. 18 edits: 10 ambiguity-pins, 6 mismatch-revisions (plus one restored blank paragraph separator — a sentence-deletion edit had silently dropped the file to 505 lines and it was caught and repaired). 117,547 → 123,344 chars.

- §2.8 — revise — mismatch — "Path resolution always precedes body validation" reversed: body shape validation precedes path resolution (§2.11 order 4 before 5), so a bad path + missing required field yields `ERR_INVALID_REQUEST`. Verified uniform across all five route modules — routes/petitions.py:132-138, routes/batches.py:128-136, routes/rounds.py:58-60
- §3.2 — insert — ambiguity — `reviewer_note` is shape-checked as a string when non-null but never stored or echoed — routes/petitions.py:115
- §3.2 — revise — mismatch — clearance requires title/summary non-null **and non-empty**; the gate is truthiness, and `title-summary` imposes no minimum length — routes/petitions.py:156
- §3.4 — insert — ambiguity — `affidavit_signed` is a required boolean whose value gates nothing (a `false` batch is created); no petition-status precondition on batch filing — routes/batches.py:35,42
- §3.4 — insert — ambiguity — only the assignment's `status` is consulted, not its `effective_from`/`effective_to`; where several `ACTIVE` assignments exist the earliest created governs the county check alone — routes/batches.py:60-70
- §3.4 — insert — ambiguity — a batch on a never-cleared petition has no window, so every line is refused `ERR_SIGNED_OUTSIDE_WINDOW` — routes/batches.py:147-149
- §3.5 — insert — ambiguity — `CURE_RECHECK` without `cure_period_id` is `ERR_INVALID_REQUEST`/400; on other round types a supplied `cure_period_id` is still resolved (404-able) then discarded, stored null — routes/petitions.py:214-223,239
- §3.5 — insert — ambiguity — round initial values pinned (`round_index` counts voided rounds; `sampled_valid_count`/`validity_rate_bps`/`projected_valid_count`/`accrued_cost_cents` at 0; `tallied_by_examiner_id`/`voided_reason` null) — routes/petitions.py:237-254
- §3.5 — insert — ambiguity — `ERR_ROUND_ALREADY_OPEN` is evaluated before the petition-status gate (both are §2.11 group 10) — routes/petitions.py:225-228
- §3.5 — insert — ambiguity — the `FULL_CHECK` and `CURE_RECHECK` self-transitions do not restamp the petition at all (no `version`, no `updated_at`); wrong-source-status openings are `ERR_INVALID_PETITION_STATE`, evaluated before the cure period's `OPEN` check — routes/petitions.py:227-230,261-268
- §3.6 — revise — mismatch — the petition projection is **not** refreshed "whenever `accepted_raw_total` changes"; only the §2.10 reconciliations refresh it. Affidavit verification and line addition move the counters and leave the stored projection alone — routes/batches.py:218,177 vs routes/batches.py:236,257
- §3.6 — revise — mismatch — the distribution report's `qualifying_county_count` is counted afresh from its own `counties` array, not copied from the petition's stored counter (they diverge after validations without a tally); `counties` is ordered by `county_code` ascending — routes/petitions.py:399
- §3.7 — insert — ambiguity — `supplemental_raw_count` is derived at read time, so a supplemental filing moves it without advancing the `CurePeriod`'s `updated_at` or `version` — routes/petitions.py:26-29, routes/rounds.py:76,85
- §3.7 — insert — ambiguity — expiring a non-`OPEN` period is `ERR_CURE_PERIOD_NOT_OPEN`; expiry skips the `PENDING_FAILURE` advance when the petition is already `CERTIFIED`/`FAILED` (reachable via two staggered cure periods) — routes/rounds.py:93,100-102
- §3.8 — revise — mismatch — segregation of duties is the **first** gate, not the fourth (§2.11 position 8, ahead of the status gate); challenge/fraud/distribution renumbered second/third/fourth to match — routes/petitions.py:367-382
- §3.8 — insert — ambiguity — a new `Challenge` starts with `court_docket_number` and `ruling` null — routes/petitions.py:345-346
- §3.9 — insert — ambiguity — reinstating a non-`INVALIDATED` batch is `ERR_INVALID_BATCH_STATE`; `invalidation_reason` is replaced when supplied, retained when omitted, never cleared — routes/batches.py:248, services/cascades.py:71-72
- §4 — revise — mismatch — the `verification-invoice` row carried the distribution-report's `counties[]` field list; replaced with the invoice's actual fields — routes/petitions.py:409

Pass 2 also resolved pass 1's `require_batch_owner` hand-off as unreachable: petitions are never deleted from `db.petitions` and routes/batches.py:144,217,290 index it directly, so no batch can outlive its petition. No PRD silence needed.

### Pass 3 — services + challenges (services/calculations.py, services/verification.py, services/cascades.py, routes/challenges.py)

Confirmed no re-copy; passes 1 and 2's sentinels all survived (§2.2 `api_request_id`, §2.7 version-starts-at-1, §2.8 body-before-path, §3.8 segregation-first, §3.7 cure-expiry terminal guard). 14 edits: 10 ambiguity-pins, 4 mismatch-revisions. 123,344 → 130,687 chars.

- §2.10 — insert — ambiguity — pins the one shared petition reconciliation and the exact seven figures it refreshes (incl. `raw_signature_count` and `cure_period_count`, which §3.9's three per-operation lists all omit), states that `verification_cost_accrued_cents` is never recomputed but moves only by explicit deltas, and carves out the round-void variant — services/cascades.py:9-18
- §2.10 — revise — mismatch — the "restoration is verbatim" claim for round voiding now says only the *status* is rolled back, the stored batch cost being zeroed, so cost conservation holds for invalidate/reinstate but not across a round void — services/verification.py:165-166
- §3.5 — insert — ambiguity — duplicate candidate set now includes a still-`PENDING` line whose `claimed_voter_id_number` resolves to the same voter, which is what actually makes the keeper order-independent — services/calculations.py:254-261
- §3.6 — insert — ambiguity — the §2.10 projection refresh pinned per round type: a `RANDOM_SAMPLE` latest-closed round recomputes `projected_valid_count` and sets `verified_valid_count` to 0; `FULL_CHECK`/`CURE_RECHECK` sets both to face value; none remaining sets both to 0 — services/calculations.py:209-223
- §3.6 — revise — mismatch — `SAMPLED` → `FULLY_CHECKED` is driven by a later `FULL_CHECK` **or `CURE_RECHECK`** round; also pins that the promotion test is "no line of the batch is `PENDING`" batch-wide, and that already-`SAMPLED`/`FULLY_CHECKED` batches touched by a random sample keep their status — services/verification.py:71-80
- §3.6 — insert — ambiguity — under a `STRATIFIED` standard a participating county in which the latest closed round selected no line has a stratum rate of 0 and is credited 0 (so cannot qualify), whereas `POOLED` applies the round-level rate to every participating county — services/calculations.py:170-173, 308-314
- §3.8 — insert — ambiguity — challenge dismissal's `reason` is shape-checked only (explicit null accepted), never stored or echoed; `ruling` stays null on an administrative dismissal — routes/challenges.py:92-93
- §3.8 — insert — ambiguity — the submitted `ruling` is stored on both the `AFFIRM` and `REVERSE` paths — routes/challenges.py:68
- §3.8 — insert — ambiguity — the `REVERSE` flip reaches only `PENDING_CERTIFICATION`/`PENDING_FAILURE`; a petition that has drifted out of them gets `challenge_status` `COURT_REVERSED` with `status` untouched — routes/challenges.py:79-82
- §3.9 — insert — ambiguity — referral opening: a `CountyClerk` naming a `batch_id` outside its own county gets `ERR_NOT_RESOURCE_OWNER`, but a referral naming no batch carries no ownership restriction at all — routes/challenges.py:126-127
- §3.9 — revise — mismatch — referral opening rescores through the *same* two-variant rule, not unconditionally the provisional one: a circulator already carrying a strike is rescored under the adjudicated variant, where the new open referral moves the score not at all — routes/challenges.py:143, services/calculations.py:441-449
- §3.9 — insert — ambiguity — adjudication evaluates the segregation bar before the `REFERRED_TO_AG` state gate, per §2.11 — routes/challenges.py:186-189
- §3.9 — insert — ambiguity — substantiated cascade: no-batch referral records `voided_signature_count` 0; cascade invalidation leaves `invalidation_reason` null; `misconduct_strike_count` is *recounted* from `SUBSTANTIATED` referrals; suspension fires only when `registration_status` is `REGISTERED`, leaving `PENDING_TRAINING`/`TRAINED`/`SUSPENDED`/`REVOKED` circulators and their assignments untouched — services/cascades.py:118-132
- §3.9 — insert — ambiguity — revoke cascade reaches a batch by (revoked circulator, petition released by a just-terminated assignment) since batches name no assignment, so sheets for a petition whose only assignment was already `TERMINATED` are spared; `invalidation_reason` left null — services/cascades.py:90-108
- §3.9 — revise — mismatch — round voiding rewritten: unconditional return of selected lines to `PENDING` including already-`VOIDED` ones with residual `status_before_void`/`void_reason` (and no longer reinstatable); `checked_signature_count` recomputed; round's `accrued_cost_cents` reset to 0; the cost drift across a two-round batch spelled out; and the recompute set plus the `SIGNATURES_FILED` reset (with the `CERTIFIED`/`FAILED` guard) extended to `OPEN`-round voids — services/verification.py:151-184

### Pass 3's verdicts on pass 2's four hand-off leads

1. **verification.py:166 cost-ledger drift — CONFIRMED and pinned.** Traced concretely: batch of 4 lines, round 1 samples 2 (cost 10, petition 10), round 2 full-checks the rest (cost 19, delta 9, petition 19). Voiding round 2 zeroes the batch to 0 and subtracts only 9, leaving the petition at 10 with no batch backing; a later re-examination computes its delta against a stored 0 and re-accrues 10 on top (petition 20). §3.9's "exact because the round accrued only deltas" was true of the petition-side subtraction but false as a conservation claim, so the delta sentence was kept and the drift added explicitly, plus a cross-reference caveat in §2.10.
2. **verification.py:155-159 residual void metadata — CONFIRMED and pinned.** Reachable by: close round → invalidate a batch the round sampled (lines → `VOIDED`) → void the round. Every selected record is forced to `PENDING` with `status_before_void`/`void_reason` left standing, and `reinstate_batch` (cascades.py:56-60) only compensates lines still at `VOIDED`, so the line is permanently unrestorable. Both consequences now in §3.9.
3. **calculations.py:254-285 duplicate candidate set — CONFIRMED and pinned.** A `PENDING` line has `matched_voter_record_id` null, so the PRD's literal candidate predicate would never admit it and the stated order-independence would be false. Pinned inline in §3.5. The analogous "participating counties" wording in §3.6's *stratified-projection* sentence was deliberately NOT pinned — a county with accepted lines but no selected line contributes a zero-rate term either way, so both readings give the identical integer sum; it is a real silence only in §3.6's county-distribution rule, where a zero credit un-qualifies the county, and that is where it was pinned.
4. **cascades.py:55 `or "RECEIVED"` fallback — NOT a real silence; deliberately left unpinned.** `INVALIDATED` is assigned at exactly one site (cascades.py:44, the only match in the tree) and that branch always writes `status_before_invalidation` first; `reinstate_batch` is the only clearer of that field and it also moves the batch off `INVALIDATED`, and the reinstate route gates on `status == "INVALIDATED"`. `void_round`'s `_batch_status_before` restore writes a pre-round status, not `INVALIDATED`, and would make the batch fail the reinstate gate anyway. The fallback is unreachable defensive code; pinning `RECEIVED` would have documented behavior the implementation cannot exhibit.

Pass 1's remaining hand-off (the credibility formula itself) checked out clean against calculations.py:426-450 — weights 5000/10000, 500 per open referral, 2000 per strike, floor 1000, and §3.9's recompute-site list ("every line validation, every referral opening, every adjudication, once more at revocation") exactly matches the five call sites. The only defect in that area was the variant selection at referral opening, pinned above.

### Orchestrator final verification

- `PRD_COMPLETED.md` is 506 lines / 130,687 chars and is **NOT** byte-identical to either `PRD_FINALIZED.md` (112,666) or `PRD.md` (111,550) — the scan demonstrably ran.
- It ends at the final `ERR_FRAUD_REFERRAL_OPEN` row of the §5 error table; all five top-level sections (§1–§5) present and in order. Not truncated.
- All 8 `workspace/implementation/results.*.json` re-parsed: 120/120 in every round.
- Mtime audit confirms nothing executable changed after the green sweep: implementation last written 14:22 (Step 6), test fixes 16:03 (Step 7), results 16:08 (final sweep). Steps 8 and 9 touched only `PRD_FINALIZED.md` / `PRD_COMPLETED.md`.
- Exactly one `worklog.md`, at the task root — no cwd-drift strays under `workspace/`. `__pycache__` directories removed.

Pipeline complete.
