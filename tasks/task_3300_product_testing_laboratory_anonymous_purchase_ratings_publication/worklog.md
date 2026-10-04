# Worklog — task_3300_product_testing_laboratory_anonymous_purchase_ratings_publication

## Step 1: Create Task Directory — 2026-09-30T18:27:00.000Z

Task directory was pre-allocated by the caller: verified `./tasks/task_3300_product_testing_laboratory_anonymous_purchase_ratings_publication/workspace/` exists and is empty. No new index computed; no other task directory created.

## Step 2: Generate Scaffold — 2026-09-30T18:46:00.000Z

Note: first subagent attempt exceeded the output cap mid-generation and wrote no files; relaunched with strict output discipline (one tool call per message, no printed design rationale, ≤1500-line scaffold, ≤36 endpoints hard cap). Second attempt succeeded. Subagent summary (verbatim):

  All three artifacts generated, validated, and lint-clean in `/home/ubuntu/github/CodingPRD/tasks/task_3300_product_testing_laboratory_anonymous_purchase_ratings_publication/`.

  **Verification results**
  - `SCAFFOLD.yaml` — 941 lines; `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 937 lines; `SCAFFOLD_CORNER_DESIGN.yaml` — 1191 lines. All parse as valid YAML; SCAFFOLD.yaml contains no `scaffold_difficulty_design`/`scaffold_corner_design` keys.
  - `scaffold_lint.py` verdict: **clean lint** — 36 endpoints, 10 entities, 434 recipe calls scanned, zero violations (endpoint existence, role, payload shape, capture resolution, OCC placeholder discipline, FK reverse-reachability all pass).

  **Structure**
  - Entities (10): ProductCategory, TestProgram, LabProtocol, TestSample, PurchaseOrder (embedded lines), Measurement, SurveyWave (embedded responses), RatingPublication (embedded rated_models + manufacturer_responses), SafetyFinding, Member (embedded subscriptions). Testability drove the consolidation: parent-embedded arrays let tests create and read child state without dedicated read endpoints, keeping the surface at exactly 36 endpoints (merged per-entity `/transitions` endpoints with an `action` discriminator).
  - State machines (8): cyclic loops on LabProtocol (DRAFT↔IN_REVIEW) and RatingPublication (UNDER_REVIEW↔REVISION_REQUESTED), program pipeline with bubble-up publish and revert-on-withdraw, wave open→closed→qualified/disqualified, finding lifecycle, member lapse/revive/cancel, sample cascade machine.
  - Difficulty design: 9 rule_ids × 2 instances = 18; corner design: 28 instances across 8 sections.
  - 3 OCC concurrency rules (protocol activate on category version, publication approve on program version, wave qualify on wave version), 18-error catalog, 18-priority validation chain, SoD RBAC (proposer≠approver, placer≠verifier, Member entity-backed).

  **Harder-than-expert hook**: a tier-3 safety escalation fires a depth-3 cascade (escalate → designation flip → publication withdrawal → category rescore with program revert), while designation itself depends on a safety-first threshold ladder fed by a two-stage mean whose dual variants are clock- and rounding-order-sensitive — all pinned to pre-computed literals in every recipe.

Orchestrator verification: files exist on disk (941/937/1191 lines), all parse as YAML, correct top-level keys, 10 entities / 36 endpoints / 8 state machines / 18 difficulty instances / 28 corner instances, no design keys leaked into SCAFFOLD.yaml.

## Step 3: Copy Shared Files — 2026-09-30T19:19:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T19:24:00.000Z

Subagent summary (verbatim):

  All checks pass. Final verification of the three hard contracts.

  **PRD written:** `workspace/PRD.md` — **294 lines**.

  **Sections:** §1 Introduction; §2.1 RBAC (all 10 roles + identity prose), §2.2 Response Structure (verbatim block), §2.3 Pagination, §2.4 Common properties + logical clock (incl. startup default `2026-09-01T00:00:00Z`, Measurement's missing `updated_at`/`version`), §2.5 Validation priority order (all 18), §2.6 OCC (3 rules), §2.7 Money/precision, §2.8 Marketing refusal; §3.1–3.10 (categories/selection score, programs, purchasing/budget ledger, protocols, samples/measurements, publications/designations/embargo, safety cascades, survey waves, membership/cycle-run, manufacturer responses); §4 endpoint table (35 endpoints, 4 columns); §5 error catalogue (18 errors, 2 columns).

  **Contract 1 (Field-Name Coverage):** PASS — entities[].fields, request_body, query_params, path_params: all ~90 identifiers checked mechanically via backtick grep, 0 missing after adding §3.10 for `manufacturer_responses`/`manufacturer_response_text`/`manufacturer_name`/`body_text`.

  **Contract 2 (Rule Coverage):** PASS — 18/18 validations with priority prose (§2.5 explicit ordering); 3/3 OCC rules with endpoint + `expected_*_version` + `ERR_STALE_VERSION`/412; all 38 state-machine transitions expressed (incl. TestProgram PUBLISHED↔READY_FOR_PUBLICATION revert cascade, tier-3 depth-3 safety cascade, cycle-run depth-2 member lapse); 7/7 calculations in precise prose (selection_score with 60-month cap and dual clock variants, po_tax pinned per-line-then-sum, two-stage measurement mean, renormalized overall rating, pinned safety-first designation ladder with 20000-cent cap and 75/80/50 thresholds, cumulative escalation ladder with tier-3 requiring CRITICAL+hazard, closed-interval 14-day grace); all endpoint side_effects and applies_to scopes covered; sibling branches (dual cancel/withdraw/retire/close transitions) given equal density.

  **Contract 3 (§3 Path Purity):** PASS — 510 backtick tokens scanned in §3, 0 path/method violations.

  Constraint honored: the DIFFICULTY_DESIGN and CORNER_DESIGN files were never opened.

Orchestrator verification: workspace/PRD.md exists on disk, 294 lines, begins with "# Product Testing Lab Ratings API — Product Requirements Document", ends with error catalogue table containing ERR_STALE_VERSION/ERR_MARKETING_USE_FORBIDDEN etc.

## Step 5: Generate Unit Tests — 2026-09-30T19:36:00.000Z

Note: Step 5 and Step 6 launched SEQUENTIALLY (not concurrently) because this model endpoint duplicates parallel tool calls; the read-ban on test_suite/ for Step 6 is enforced via the explicit ISOLATION RULE in its prompt instead of physical directory absence. Subagent summary (verbatim):

  All checks pass. Final report:

  ## Test generation complete — task_3300

  **Files created (15 total, 2776 lines):**

  test_helpers/ (1169 lines):
  - `types.py` (295) — 12 status enums, role enum, 11 entity TypedDicts (Measurement correctly omits `version`/`updated_at`)
  - `api_client.py` (126) — one method per PRD endpoint (25 methods)
  - `api_errors.py` (50) — 18 error IDs + HTTP map registered with framework
  - `assertions.py` (130) — per-entity assertions + budget invariant
  - `factories.py` (160), `constants.py` (22), `test_users.py` (43) — opaque role constants + `make_member_headers` entity-backed builder
  - `fixtures.py` (316) — composite pipeline fixtures: category→program→protocol→sample→sourcing→testing→scoring→ready→published, member+subscription, wave setup
  - `__init__.py` (27) barrel export

  test_suite/ (1607 lines): `conftest.py` (60) + 5 test files: `test_01_categories_scoring.py` (270), `test_02_programs_protocols_pos.py` (553), `test_03_survey_waves.py` (138), `test_04_publications.py` (242), `test_05_safety_membership_rbac.py` (344).

  **Coverage audit (scripted):** 66 tests, zero tag errors.
  - Queue A (Difficulty): all 18 non-stub instances ≥2 tests each.
  - Queue B (Corner): all 23 non-stub instances ≥1 test each; no `excluded_because` stubs existed.

  **PRD-citation pass (scripted):** every quoted docstring citation greps verbatim against PRD.md (0 non-verbatim after fixing 6 re-flowed §4 table-row citations).

  **Skipped instances:** none — every instance passed the PRD-first filter.

  **Clock check:** PRD §2.4 startup default 2026-09-01T00:00:00Z confirmed; grace-window literals re-derived from term_end 2026-09-02 + 14 days = grace_until 2026-09-16T00:00:00Z (consistent with design recipes); renewal recompute check derives 2027-09-16 + 14d → 2027-09-30. No contradicting literals found; no re-derivation overrides needed.

  **py_compile:** all 15 files compile clean. No tests executed (no server, per instructions).

Orchestrator verification: test_helpers/ has 9 files + test_suite/ has conftest.py and 5 test files on disk; AST count confirms 66 test functions.

## Step 6: Generate Implementation — 2026-09-30T19:49:00.000Z

Subagent summary (verbatim):

  All checks pass. Note that I observed a system warning that app.py "changed on disk" — that's the expected result of my own Bash appends; no other writer was involved.

  ## Final report

  **Files created** (in `workspace/implementation/`):
  - `app.py` — 1363 lines, Flask entry point, all routes
  - `helpers.py` — 220 lines, calculations & domain helpers
  - `resp.py` — 81 lines, response envelope + error envelope + pagination
  - `auth.py` — 24 lines, X-User-ID / X-User-Role middleware
  - `store.py` — 72 lines, in-memory dict store + logical clock (starts 2026-09-01T00:00:00Z, never falls back to wall clock)
  - `start.sh` — 8 lines, executable, guarded `pip install` + `exec python3 app.py`
  - `requirements.txt` — flask

  **Endpoints implemented (33)**: `/_clock/set_current_utc`, `/_cycle/run`, CRUD + transitions for product-categories, test-programs, lab-protocols, test-samples, purchase-orders, measurements, survey-waves, rating-publications, safety-findings, members — matching the SCAFFOLD endpoint table exactly.

  **Key behaviors**: pinned threshold ladder (safety-first designation), two-stage mean lab score, per-line-then-sum PO tax, renormalized overall when survey_score null, cumulative escalation ladder, OCC on protocol activate / publication approve / wave qualify, embargo gate, marketing-use refusal header, member-only visibility rules, SoD on program approve and PO verify, depth-3 safety cascade (escalate → designation flip → withdrawal → program revert → category recompute), grace-window closed-interval subscription aging on `/_cycle/run`.

  **Verification**: `python3 -m py_compile` clean on all five .py files. Smoke tests: (1) boot + unauthenticated 401 + category create with correct selection_score 66.0; (2) full happy-path end-to-end through publication, all transitions returning expected statuses and correct computed values (PO totals 10000/1000/11500, lab_score 85.0, BEST_BUY designation). Both smoke-test PIDs killed explicitly after use.

Orchestrator verification: files exist on disk (app.py 1363 lines etc., start.sh executable). Route check: 36 @app.route registrations in app.py vs 36 PRD §4 endpoint-table rows — manual comparison confirms exact path/method coverage (the subagent's "33" count was loose; actual is 36 matching PRD exactly, incl. GET /test-samples/{id}/measurements and POST /measurements).

## Step 7: Run Tests and Iterate — 2026-09-30T20:00:00.000Z

Subagent summary (verbatim):

  All 8 rounds pass 66/66. Summary:

  ## Summary

  **Iterations run:** 2 (initial sweep → fixes → clean 8-round sweep).

  **Tests deleted:** none.

  **Failing tests diagnosed (union across rounds 1-8, all rounds failed the same 3 tests):**
  - `test_start_sourcing_requires_active_protocol` — expected `ERR_INVALID_STATE`, got `ERR_REFERENTIAL_INTEGRITY`
  - `test_start_sourcing_requires_at_least_one_sample` — same
  - `test_member_cannot_read_under_review_publication` — expected `ERR_MEMBERSHIP_INACTIVE`, got `ERR_NOT_FOUND`

  **Fixes applied to `workspace/implementation/app.py`** (in the `start_sourcing` transition handler):
  - Changed the "program needs >= 1 TestSample" precondition failure from `ERR_REFERENTIAL_INTEGRITY` (422) to `ERR_INVALID_STATE` (409). PRD §2.5 states "the target resource is in a valid from-state for the requested action ... failure yields `ERR_INVALID_STATE`" and "the state check (priority 4) precedes every business check, an action attempted from the wrong state always surfaces `ERR_INVALID_STATE` even when a business rule would also reject it". The start_sourcing gate preconditions (§3.2) are state-transition gating preconditions; a faithful PRD-only implementation maps them to the state-check error, not referential integrity. This is the PRD-derivable reading (STEP 3 implementation fix, no PRD-required check removed).

  **Fixes applied to `test_suite/test_04_publications.py`** (`test_member_cannot_read_under_review_publication` — STEP 2 test bug):
  - The test used `create_member_with_subscription`, which per PRD §3.9 leaves the member `ACTIVE` (new subscriptions start `ACTIVE`; members only become `LAPSED` when the ops-run checkpoint ages an `EXPIRED` subscription). Asserting `ERR_MEMBERSHIP_INACTIVE` on an ACTIVE member was unreachable. Fixed by setting the clock to `2027-09-16T00:00:01Z` (past the fixture's `term_end` 2027-09-01 + 14-day `grace_until`) and running the ops-run checkpoint (`api.run_cycle`, PRD §3.8 endpoint `POST /_cycle/run`) so the member cascades to `LAPSED` before the member read. The `ERR_MEMBERSHIP_INACTIVE` assertion itself is preserved verbatim per PRD §3.6 ("member-only operations additionally require the acting member's own `status` to be `ACTIVE`, else `ERR_MEMBERSHIP_INACTIVE` (403)").

  **Final state:** all 8 parallel rounds pass 66/66.

Orchestrator verification: all 8 results.{1..8}.json on disk show total=66, passed=66, failed=0, errors=0, skipped=0 (sweep ran 19:59 UTC). mtimes confirm app.py (19:55) and test_04_publications.py (19:56) edits preceded the clean sweep.

## Step 8: Finalize PRD — 2026-09-30T20:04:00.000Z

Step 8 ran (not skipped — Step 7 had 1 implementation/ fix + 1 test_suite/ fix). Subagent summary (verbatim):

  Done. One edit made; the test_04 fixture-bug item required no PRD change.

  ## Summary

  - **Line counts:** PRD.md 294 lines, PRD_FINALIZED.md 294 lines (0% delta by lines; one sentence inserted into §3.2's existing paragraph — no new sections).

  **Changes (1 edit):**
  - §3.2 — revise (inline insert into the program-pipeline paragraph) — pinned that the gating preconditions of the pipeline transitions (≥1 sample and ACTIVE protocol for start-sourcing; sourcing-complete and no DRAFT/PLACED orders for start-testing; testing-complete for start-scoring) are evaluated under the §2.5 priority-4 state check and surface `ERR_INVALID_STATE` (409), with the readiness safety gate remaining `ERR_SAFETY_GATE` — `implementation/app.py:250-301` (start_sourcing gates at lines 254-257 after Step 7's fix; parallel gates at 268-272, 283-284).

  **Pre-edit search log:**
  - (a) Subject: which error the non-from-state gate preconditions on program pipeline transitions raise.
  - (b) Impl paths enumerated and read: `app.py` program transitions handler lines 220-302 (all six actions: approve, cancel, start_sourcing, start_testing, start_scoring, ready — confirming uniform `ERR_INVALID_STATE` for gate failures except ready's `ERR_SAFETY_GATE`); publication submit gate at lines 1028-1031 (same `ERR_INVALID_STATE` pattern, consistent); purchase-order create gate at 533-534 (uses `ERR_REFERENTIAL_INTEGRITY` at *create*, not a transition — unaffected since the edit is scoped to pipeline transitions); measurement gate at 640-641.
  - (c) Wording adjustment: scoped the sentence explicitly to "the program pipeline transitions" and named each gate individually, carving out the readiness safety gate, so the PO-create and measurement-create `ERR_REFERENTIAL_INTEGRITY` paths and §3.6's submit gate remain un-contradicted.

  **No edit for the test_04 item:** pure fixture bug. PRD §3.9 (subscriptions start `ACTIVE`; aging only via the ops-run checkpoint) plus §3.6 (member-only ops require member `status` `ACTIVE`, else `ERR_MEMBERSHIP_INACTIVE`) already uniquely determine the behavior; impl `_member_visible` (app.py:925-933) checks membership before visibility-404, consistent with §3.6's "additionally require" wording.

Orchestrator verification: diff PRD.md↔PRD_FINALIZED.md shows exactly one inserted sentence in §3.2 (line 139), 294→294 lines. mtimes confirm no implementation/ or test_suite/ edits after the Step 7 clean sweep (app.py 19:55, test_04 19:56, sweep 19:59).

## Step 9: Complete PRD — 2026-09-30T20:06:00.000Z

Subagent summary (verbatim):

  Done. Report below.

  ## Summary

  **File produced:** `workspace/PRD_COMPLETED.md`

  - Source: `PRD_FINALIZED.md` (294 lines, 44,799 chars) → `PRD_COMPLETED.md` (294 lines, 45,286 chars); char-delta +487, 3 hunks.
  - Counts: 2 ambiguity-pins, 1 mismatch-revision.

  **Changes:**

  - §3.3 (Anonymous Purchasing) — insert — ambiguity — defined "manufacturer name" for the sourcing-integrity checks as exactly the `model_label` of any known `TestSample` (the system's only brand-manufacturer record); PRD previously never said how a retailer/buyer string is recognized as a manufacturer name — `implementation/helpers.py:93-106` (`is_manufacturer_direct`, `is_manufacturer_name` compare against the set of all sample `model_label`s).
  - §3.6 (publication approval, wave snapshot) — revise — mismatch — changed tie-break for `survey_wave_id_snapshot` selection from "earliest `created_at`" to "latest `created_at`" to match impl sort key `(field_end, -created_at_epoch)` with `reverse=True`, which yields latest `created_at` on ties — `implementation/app.py:848-849`.
  - §3.6 (Member visibility) — insert — ambiguity — pinned that a member read of a publication not in `PUBLISHED` status (e.g. DRAFT or WITHDRAWN) is rejected with `ERR_NOT_FOUND` (404), as though nonexistent, while only `PUBLISHED`-but-embargoed reads yield `ERR_EMBARGOED`; PRD previously left the error for non-PUBLISHED member reads unspecified — `implementation/app.py:925-933` (`_member_visible` raises `ERR_NOT_FOUND` 404 when `status != 'PUBLISHED'`).

  Everything else in the implementation (validation orderings, OCC guards, tax/scoring/survey formulas, designation ladder, escalation cascades, subscription aging boundaries, pagination, endpoint roles) was already uniquely pinned by PRD_FINALIZED.md prose and required no edit.

Orchestrator verification: diff PRD_FINALIZED.md↔PRD_COMPLETED.md shows exactly the 3 reported hunks (§3.3 manufacturer-name definition, §3.6 latest-created_at tie-break, §3.6 member 404 visibility), 294→294 lines. No implementation/, test_suite/, or test_helpers/ files modified after the Step 7 sweep.

## Final verification sweep (orchestrator-run) — 2026-09-30T20:08:00.000Z

Because Step 8/9 subagents can in principle edit implementation/ after a clean sweep (invalidating it), the orchestrator re-ran the full 8-round stability sweep directly after Step 9 completed. mtime check first confirmed no post-sweep edits to implementation/, test_suite/, or test_helpers/ (only PRD markdown was added). Re-run result: all 8 rounds total=66, passed=66, failed=0, errors=0, skipped=0. Results at workspace/implementation/results.{1..8}.json (2026-09-30 20:07 UTC).

PIPELINE COMPLETE: 66/66 tests passing × 8 parallel rounds, zero deletions, zero skips, PRD chain PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md produced.
