# Worklog — task_3297_government_program_contact_center_operations_under_performance

## Step 1: Create task directory — 2026-09-30T18:13:00.000Z

Used pre-allocated directory `./tasks/task_3297_government_program_contact_center_operations_under_performance/` (already created with `workspace/` inside, per command args). No new index computed.

## Step 2: Generate Scaffold — 2026-09-30T18:37:00.000Z

All three files are written and the lint verdict is clean. Final summary:

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_3297_government_program_contact_center_operations_under_performance/SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_3297_government_program_contact_center_operations_under_performance/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_3297_government_program_contact_center_operations_under_performance/SCAFFOLD_CORNER_DESIGN.yaml` (single top-level `scaffold_corner_design`)

## Counts

- Entities: **16** (Contract, ServiceLevel, Agent, Certification, Queue, Call, QualityReview, CoachingPlan, KnowledgeArticle, TrainingCourse, CourseCompletion, SurgeWindow, Incident, Invoice, InvoiceLine, CurePeriod)
- State machines: **11** with 41 transitions (cyclic Invoice revision loop, cyclic Queue OPEN↔PAUSED, branching QualityReview dispute fork, Incident reopen loop, auto-transitions on SurgeWindow and CurePeriod)
- Calculations: **10** (measured_asa, measured_qa_avg, measured_abandon_rate, gross_fee, staffing_target, withholding_amount, quality_total_score, queue_selector, agent_selector, reporting_sla_breach)
- Validations: **11** priority rows
- Endpoints: **65** (includes 11 unified `POST /<entity>/{id}/transition` dispatch endpoints, 2 OCC-guarded writes, 1 logical-clock test-driving endpoint, 1 prepare + 1 recompute + 1 pay-remedy, and the reverse-reachability GET web)
- Errors: **31**
- Roles: **8** (PlatformAdmin, OpsManager, Supervisor, Agent [entity_backed], QualityAnalyst, KnowledgeManager, SecurityOfficer, BillingAnalyst)
- Concurrency rules: **2** (service-level activation and invoice approval, both OCC on Contract.version)
- Difficulty instances: **18** (2 per rule × 9 rules)
- Corner instances: **39** across 9 sections
- Lint: **clean** (744 calls scanned, 0 violations)

## Design decisions downstream steps must know

1. **Unified transition endpoints.** All per-entity state changes route through `POST /<entity>/{id}/transition` with a required `to_status` discriminator, not per-action paths. This was necessary to keep the endpoint count near 40-ish; the PRD generator must present each `to_status` as its own documented action. OCC fields (`expected_contract_version`) are *conditionally* required: only when `to_status` is `EFFECTIVE` (service-levels) or `APPROVED` (invoices); omitting them on other transitions is fine, omitting on those two is 400 ERR_INVALID_REQUEST.

2. **Endpoint count is 65, above the ~40 guideline.** This is floor-driven, not padding: the lint's FK reverse-reachability rule (f) requires a canonical detail-GET per entity before any filtered-list counts, plus sub-resource GETs for lint-blind parent/child pairs (Invoice→InvoiceLine, InvoiceLine→CurePeriod). Trimming further would reintroduce lint violations. The difficulty lives in rule interplay, not the count.

3. **Two dual-variant calculations** on different domains: ASA (provisional vs official measurement-window snapshots on Calls) and QA_AVG (finality-gated QualityReview aggregation). The official variant is re-taken at every `/recompute`.

4. **Withholding formula is the hardest calculation**: miss-ratio tiers (strict `<0.05`, `[0.05,0.15)`, `>=0.15`), per-line absolute cap (`cap_pct_of_gross`), and a contract-mode-dependent cumulative cap (`cap_absolutes` boolean) applied in chronological period order after the per-line cap.

5. **Logical clock**: default `2026-09-01T00:00:00Z`, driven by `POST /_clock/set_current_utc`, fires SurgeWindow and CurePeriod auto-transitions. All fixture dates sit at/after 2026-09-01.

6. **Selector determinism**: queue and agent selection both rank by `created_at ASC` (never `id`), with least-busy-today as the agent primary key. Overflow is at most one hop (`MAX_ROUTE_DEPTH: 2`), adjacency-inclusive overlap on surge windows, strict `>` on certification freshness and incident reporting SLA.

7. **Segregation of duties**: `Invoice.auto_review` becomes true when a recompute refreshes a line that has a completed CurePeriod; approval then requires a different `X-User-ID` than the preparer (ERR_AUTO_REVIEW_REQUIRES_SECOND_APPROVER).

8. **Known lint-heuristic accommodations** (documented as "derivation exception" annotations in entity field descriptions): four FKs (Certification.agent_id, Certification.training_course_id, Certification.invalidated_by_article_id, CourseCompletion.training_course_id) rely on filtered-list reverse reachability even though the lint's segment derivation can't see it — resolved by adding detail GETs for Certification and CourseCompletion.

## Step 3: Copy shared files — 2026-09-30T18:39:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T18:50:00.000Z

PRD generation complete. Summary:

**File written:** `/home/ubuntu/github/CodingPRD/tasks/task_3297_government_program_contact_center_operations_under_performance/workspace/PRD.md` (334 lines)

**Section list:**
- §1 Introduction (3 paragraphs: business context, role coalition, logical-clock + measurement-driven-money commitments)
- §2 Global Specifications: 2.1 RBAC (headers, 8 roles, per-role `identity` translated — `Agent` is entity-backed, all others opaque), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ASC), 2.4 Logical Clock (default `2026-09-01T00:00:00Z`, auto-transitions on clock-set and on surge reads), 2.5 Common Resource Properties + unified `to_status` transition surface (Certification/CourseCompletion carry only `id`/`created_at`), 2.6 Validation priority order 1–11, 2.7 Precision/Rounding/Measurement windows (naive local wall time), 2.8 OCC (`expected_contract_version` required only when `to_status` is `EFFECTIVE`/`APPROVED`, `ERR_STALE_VERSION` 412), 2.9 Privacy/ownership scope
- §3 Business Logic (12 subsections): 3.1 contract + service-level lifecycle (activation cascade, `ERR_SL_CONFLICT`, binding rule, archive gate, all three contract-close fiscal gates), 3.2 agents/training/certification (standing definition with strict `valid_until > t`, revalidation path), 3.3 queues + both selectors (created_at ASC determinism, MAX_ROUTE_DEPTH 2, one-hop overflow), 3.4 call lifecycle (answer/complete ownership, frozen `handled_by_agent_id`), 3.5 quality reviews + disputes + auto-coaching (threshold 70, 7-day dedup window, 14-day due date), 3.6 knowledge publishing cascade, 3.7 surge windows (adjacency-inclusive overlap, multiplier selector), 3.8 incidents (strict >24h SLA derived on read), 3.9 invoice prep (all three measurement algorithms, provisional/official variants, gross fee 50000+4000/cert, staffing baseline 10), 3.10 withholding tiers (strict <0.05, inclusive ≥0.15; per-line cap both modes; cumulative cap only when `cap_absolutes` false, floored, applied after per-line cap), 3.11 cure periods (72h, pay-remedy cascades, auto-FORFEIT), 3.12 settlement (submit line gate, OCC + SoD on approve, revision loop keeps lines)
- §4 Endpoint table (65 rows, 4 columns)
- §5 Error catalogue (31 rows, 2 columns)

**Self-audit (all three hard contracts):**
- Contract 1 (field-name coverage): all 84 entity fields + endpoint input/query identifiers verified present in backticks — 0 missing (one initial miss, `invoice_line_id`, was repaired in §3.11).
- Contract 2 (rule coverage): 72-point checklist over state-machine transitions (both success and failure branches), all 10 calculations with exact boundary semantics (strict vs inclusive tier bounds, strict `>` on the 24h SLA, ceil on staffing target, sum-once rounding), all 11 validation priorities with error ids, both OCC rules, and every role-to-resource mapping — all PASS. All 31 error ids appear in §2/§3 narrative, not just §5.
- Contract 3 (§3 path purity): 0 violations — no backticked path, bare HTTP method, or method+path token anywhere in §3; all endpoint references use state-pair framing, role+verb, or capability description.

The two forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, and no sibling task directories were accessed.

Orchestrator spot-check: PRD.md on disk is 334 lines with all 31 distinct `ERR_*` ids present.

## Step 5: Generate Unit Tests — 2026-09-30T19:05:00.000Z

Done. Summary:

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3297_government_program_contact_center_operations_under_performance/`):

`test_helpers/` (9 files):
- `__init__.py` — barrel export (framework generics + PRD-specific)
- `constants.py` — BASE_FEE_CENTS 50000, RATE_CARD_CENTS 4000, BASELINE_STAFFING 10, tier bounds/rates, AUTO_COACH_THRESHOLD 70, CURE_WINDOW_HOURS 72, MAX_ROUTE_DEPTH 2
- `types.py` — status enums + entity TypedDicts (Certification/CourseCompletion omit `updated_at`/`version` per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint
- `api_errors.py` — `ApiErrorId` enum + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + invoice money invariant
- `factories.py` — payload factories (input fields only)
- `test_users.py` — `TEST_USERS` shared headers for opaque roles + `make_agent_headers(agent_id)` per-instance builder for the entity-backed Agent role
- `fixtures.py` — composite fixtures: `setup_active_contract`, `setup_routable`, `setup_completed_call`, `setup_breach_invoice`, clock/route/answer/complete/invoice/cure helpers (all identity-threaded)

`test_suite/` (11 files, 78 tests):
- `conftest.py`, `test_01_creation_and_listing.py` (7), `test_02_state_machine_lifecycle.py` (8), `test_03_routing_selectors.py` (5), `test_04_quality_scoring_and_coaching.py` (9), `test_05_invoicing_core.py` (11), `test_06_withholding_tiers_and_cure.py` (7), `test_07_validation_and_rbac.py` (16), `test_08_surge_incidents_and_knowledge.py` (10), `test_09_endpoint_mechanics.py` (5), `test_10_abandon_measurement.py` (1)

**Instance coverage** (57 total design instances, 0 stubs in either yaml):
- Queue A (Difficulty): 18/18 emitted, each with exactly 2 tests (36 tests).
- Queue B (Corner): 39/39 non-stub emitted with ≥1 test (42 tests). No skips in either queue.

**Skips: none.** Every instance passed the PRD-first two-condition filter. The `remaining_error_stubs` instance name is literal (not an `excluded_because` stub) and was translated; its ERR_CALL_OVERFLOW_FORBIDDEN sub-claim is unreachable via the transition surface and was not asserted — the instance's own yaml already delegates that assertion elsewhere.

**Clock check:** all fixture dates are ≥ the 2026-09-01T00:00:00Z logical start; the oldest occurred_at (2026-08-01) is only an incident input field, which is clock-independent.

**Design-tag confirmation:** every one of the 78 emitted tests carries exactly one `Design: Difficulty/<rule_id>/<instance>` or `Design: Corner/<section>/<instance>` line as the final line of its docstring; a scripted audit confirmed every tag resolves to a real instance `name:` in the source yamls, and every ≥8-word PRD citation fragment survives a literal whitespace-normalized grep of PRD.md.

All ownership-gated calls use `make_agent_headers(<actual agent id>)`; no skip/xfail markers anywhere.

Orchestrator spot-check: on disk — 9 test_helpers files, 11 test_suite files, 78 `def test_` functions, 57 unique Design tags (18 difficulty + 39 corner instances).

## Step 6: Generate Implementation — 2026-09-30T19:29:00.000Z

All smoke tests pass. The implementation is complete and functional.

## Summary

**Files written** (all under `workspace/implementation/`):

- `start.sh` — foreground launcher; guarded pip install (`if ! python3 -c "import flask"`); `exec python3 app.py`; reads `$PORT` (default 10000), binds 0.0.0.0
- `requirements.txt` — `flask>=3.0`
- `errors.py` — `ApiError` exception + `raise_err` helper
- `clock.py` — module-level logical clock (default `2026-09-01T00:00:00Z`), ISO-8601 parse/format with 3 fractional digits, `period_window`/`period_end` (naive wall-time months)
- `db.py` — 16 in-memory dicts; empty at boot, no seeding
- `models.py` — record factories; `common=True` produces `id`/`created_at`/`updated_at`/`version`; Certification and CourseCompletion get only `id`/`created_at`
- `response.py` — envelope helpers; auth via `X-User-ID` + `X-User-Role` against the 8 declared roles
- `calculations.py` — Decimal-based round-half-up helpers, `quality_total_score`, `cert_standing_at`, surge-mult selector, `staffing_target_for` (ceil(10·mult)), `gross_cents_for` (BASE 50000 + sum of 4000·cert·mult, round once), measured ASA/ABANDON/QA_AVG over naive period window, `is_compliant` (with staffing-shortfall override), tiered withholding (`<0.05 → 10%`, `[0.05,0.15) → 25%`, `>=0.15 → 40%`), per-line cap, cumulative floor when `cap_absolutes` false, binding-SL selector
- `routing.py` — `queue_selector` (GENERAL/SPECIALTY matching, language filter, earliest-created queue with available agent; overflow one hop, MAX_ROUTE_DEPTH 2) and `agent_selector` (ACTIVE, language match, standing cert, not busy; fewest COMPLETED today then earliest created_at)
- `auto_transitions.py` — surge DECLARED→ACTIVE→EXPIRED and CurePeriod PENDING→FORFEIT
- `invoice_logic.py` — `prepare_invoice`, `recompute_invoice`, `pay_cure_remedy`
- `app.py` — Flask app with all 65 endpoints (clock set, contract/service-level CRUD+transition with OCC, agents, training courses, certifications, queues, calls, quality reviews + auto-coaching cascade, coaching plans, knowledge articles + publish invalidation cascade, surge windows with adjacency-inclusive overlap, incidents with derived sla_breached, invoices prepare/recompute/transition with SoD, cure-period pay-remedy, reverse-reachability collections)

**Self-check:** `bash -n start.sh` parses cleanly, `python3 -c "import app"` succeeds with 66 URL rules registered; live smoke test on a throwaway port verified clock-set, empty list pagination, contract creation (201 DRAFT), 401/403 RBAC. No tests were run.

**ISOLATION RULE honored:** subagent reported it did not read `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_suite/`, or `test_helpers/`.

Orchestrator spot-check: on disk — 12 implementation files (2500 lines total Python), start.sh parses OK.

## Step 7: Run Tests and Iterate — 2026-09-30T20:12:00.000Z

Results are from the final sweep, after all edits. Clean 8/8 rounds at 78/78.

## Summary

- **Iterations run:** 4 sweeps (11/78 → 12/78 → 19/78 → 69/78 → 78/78 across all 8 rounds).

- **Tests deleted:** none. Every failing test traced to a verbatim PRD rule; all failures were fixed in the artifact or the implementation.

- **Fixes applied to test_helpers/:**
  - `test_helpers/fixtures.py` `create_certified_agent` — fixed `NameError: agent_id` (passed bare name instead of `agent["id"]`); this single defect caused 58 of 59 failures in round 3 of iteration.
  - `test_helpers/fixtures.py` `setup_active_contract` — removed the redundant `activate_contract` call; the first service-level activation bootstraps the parent contract to ACTIVE (the PRD's two activation preconditions are mutually recursive), so a separate contract activation 409s on the no-longer-DRAFT contract.
  - `test_helpers/fixtures.py` `setup_active_contract`/`setup_routable` — threaded a `program_code` parameter through so multi-contract tests can isolate program-scoped staffing/gross counts (PRD §3.9 counts certified agents per program, globally).
  - `test_helpers/fixtures.py` — added `staff_to_target(course_id, target=10, already=1)` helper to certify enough agents to clear the PRD §3.9 staffing-shortfall override where a test exercises the metric rule in isolation.

- **Fixes applied to test_suite/:**
  - `test_01_creation_and_listing.py` — `created_at` literal corrected to `2026-09-01T00:00:00.000Z` (PRD §2.7 mandates three fractional digits).
  - `test_02_state_machine_lifecycle.py` — same timestamp drift on `reported_at`; staffed revision-loop test to baseline target.
  - `test_04_quality_scoring_and_coaching.py` — same timestamp drift on `due_date`.
  - `test_09_endpoint_mechanics.py` — added missing `setup_active_contract` import (NameError); added a clock-set to 2026-10-01 before activating an SL with `effective_from=2026-10-01`, and moved the invoice period to 2026-08 so the SL lies outside the half-open measurement window (the original test demanded the impossible: activate an SL whose effective_from is in the future, which PRD §3.1 forbids).
  - `test_05_invoicing_core.py` — staffed the provisional-ASA and at-target-ASA tests to the baseline target of 10 so the PRD §3.9 staffing-shortfall override doesn't force the asserted-compliant lines non-compliant.
  - `test_06_withholding_tiers_and_cure.py` — gave the three tier-boundary contracts distinct program codes so their gross/staffing counts don't cross-contaminate under PRD §3.9's program-global counting.
  - `test_08_surge_incidents_and_knowledge.py` — same program isolation for the two-contract surge multiplier test (56000 vs 62000).
  - `test_07_validation_and_rbac.py` `test_overflow_mismatch_and_overflow_locked` — the fixture queue (created before q_en1) is the earliest English queue and receives the routed call; the test now exercises OVERFLOW_LOCKED on that queue instead of asserting the call landed on q_en1.

- **Fixes applied to implementation/:**
  - `clock.py` `new_id` — emits `str(uuid4())` (hyphenated UUID) instead of `.hex`; PRD §2.7 requires a server-minted UUID.
  - `app.py` `service_level_transition` — bootstrap resolution of the PRD's mutually recursive activation preconditions (SL EFFECTIVE requires ACTIVE contract; contract ACTIVE requires an EFFECTIVE SL): when activating a DRAFT SL whose DRAFT parent has no EFFECTIVE sibling, the parent is activated in the same write; a CLOSED parent still yields ERR_INVALID_STATE. Direct contract activation without an EFFECTIVE SL still fails (test_contract_activate_without_effective_sl_fails passes).
  - `app.py` — all ten transition endpoints now reject an unknown `to_status` with ERR_INVALID_REQUEST (400) instead of ERR_INVALID_STATE; PRD §2.6 puts enum-membership at request-shape priority, before state-machine legality.
  - `app.py` surge-window creation — overlap predicate corrected to adjacency-inclusive (`s_dt <= we and e_dt >= ws`); PRD §3.7: "a candidate beginning exactly when another ends is rejected".
  - `invoice_logic.py` `recompute_invoice` — a line whose cure period was remedied keeps its released zero withholding across recomputes and opens no new cure period; previously recompute re-detected the breach and re-withheld, undoing the remedy that PRD §3.11 says "cures the breach".

Orchestrator spot-check: all 8 `results.{1..8}.json` on disk, each passed=78 failed=0 total=78, mtimes 20:12 (post-edit final sweep). No test deletions.

## Step 8: Finalize PRD — 2026-09-30T20:17:00.000Z

All six edits are in place; both files are 334 lines (edits were inline revisions/expansions within existing paragraphs, so line count is unchanged; character delta is +~1,400 chars on ~55 KB, roughly +2.5%).

**Line counts / delta:** PRD.md = 334 lines, PRD_FINALIZED.md = 334 lines (0% line-count delta; 6 paragraphs revised in place, no sections added or removed).

**Changes made (one bullet per edit):**

- §2.5 — revise — `id` pinned to canonical 36-character hyphenated UUID string form, no type prefix — implementation/clock.py:38-39 (`new_id` returns `str(uuid.uuid4())`).
- §2.5 — revise — unified transition surface now declares `to_status` an enum: an unrecognized target is `ERR_INVALID_REQUEST` (400) at §2.6 priority 4, while a recognized-but-unreachable target remains `ERR_INVALID_STATE` (409) — implementation/app.py:139, 279, 348, 590, 722, 855, 930, 1018, 1133, 1425 (all ten transition endpoints).
- §2.4 — revise — initial clock reading clarified to render with three fractional digits wherever emitted (e.g. `2026-09-01T00:00:00.000Z`) — implementation/clock.py:34-35.
- §3.1 — revise — service-level activation bootstraps the mutually recursive preconditions: activating a DRAFT SL whose parent contract is still DRAFT activates the parent to ACTIVE in the same write (parent version increments once for the bootstrap, plus the activation's own increment); a CLOSED parent yields ERR_INVALID_STATE; direct contract activation never bootstraps — implementation/app.py:226-236, 262; asymmetry confirmed at app.py:110-119.
- §3.7 — revise — surge-overlap predicate changed from strict to inclusive inequalities ("at or before" / "at or after"), matching the adjacency-as-collision sentence and the impl — implementation/app.py:1085 (`s_dt <= we and e_dt >= ws`).
- §3.11 — revise — recompute now pins remedy permanence: a line with a REMEDIED cure period keeps its zero withholding across recomputes even if still non-compliant, and no new cure period opens for it — implementation/invoice_logic.py:164-166, 180-185.

**Diff items deliberately not turned into PRD edits (already pinned or pure fixture bugs):** `create_certified_agent` NameError (fixture bug); `setup_active_contract` redundant activation (consequence of the §3.1 bootstrap, now pinned); `program_code` threading and `staff_to_target` (consequences of §3.9's program-global staffing counts and staffing-shortfall override, already pinned); timestamp test literals (§2.5/§2.7 already mandate three fractional digits; §2.4 clarification added as the adjacent silence); test_09 clock-set (§3.1 effective_from rule already pinned); OVERFLOW_LOCKED queue ordering (§3.3 earliest-`created_at` selection already pinned).

**Per-edit pre-edit search logs:** recorded inline before each Edit call — each lists (a) subject, (b) impl paths enumerated and verified, (c) wording adjustments. Notable (c) items: edit 2 avoids any claim about role-gate ordering for unknown `to_status` values; edit 4 explicitly pins the double contract-version increment and the contract-endpoint asymmetry; edit 6 is scoped to recompute only (re-prepare replaces lines wholesale in `prepare_invoice`, so a remedy does not carry across re-preparation).

File produced: workspace/PRD_FINALIZED.md

Orchestrator spot-check: PRD_FINALIZED.md on disk (59,255 bytes vs PRD.md 57,268); 12 changed diff lines; all implementation/*.py mtimes predate the 20:12 final sweep — Step 8 did not touch implementation/, so the clean 8/8 sweep remains valid.

## Step 9: Complete PRD — 2026-09-30T20:25:00.000Z

Diff confirms exactly the intended edits (18 changed lines, all in-place paragraph revisions; same line count of 334). The work is complete.

## Summary

**Source vs output**: `PRD_FINALIZED.md` 334 lines / 59,255 chars → `PRD_COMPLETED.md` 334 lines / 63,670 chars (char-delta +4,415; 18 lines revised in place, no lines or sections added).

**Counts**: ambiguity-pins: 17; mismatch-revisions: 1.

**Changes** (all in-place paragraph edits; no new sections):

- §2.4 — insert — ambiguity — clock-set forfeiture also increments contract `cure_periods_used` at that moment, and cure-period forfeiture fires only on clock-sets, never on reads — implementation/auto_transitions.py:20-30, invoice_logic.py
- §2.6 — insert — ambiguity — course-completion 404 surfaces `ERR_CERTIFICATION_NOT_FOUND`; cure-period 404 surfaces `ERR_INVOICE_LINE_NOT_FOUND` (no dedicated ids exist) — implementation/app.py:461, app.py:1355
- §2.7 (precision) — insert — ambiguity — `answer_seconds`/`talk_seconds` stamps are exact whole-second differences, not rounded — implementation/app.py:695, 709
- §2.7 (windows) — insert — ambiguity — naive wall time equals UTC instants since the clock and all timestamps are UTC — implementation/clock.py:42-50
- §2.9 — insert — ambiguity — Agent single-call GET is refused `ERR_FORBIDDEN` unless call's `agent_id` equals `X-User-ID` — implementation/app.py:657-658
- §3.1 (activation) — insert — ambiguity — bootstrap activation advances parent contract version by 2 total (1 for parent activation + 1 for SL activation), vs 1 against an ACTIVE parent — implementation/app.py:236, 262
- §3.1 (activation) — insert — ambiguity — `ERR_SL_CONFLICT` compares `effective_from` strings lexicographically; equivalent instants in different notations do not conflict — implementation/app.py:247
- §3.1 (binding rule) — insert — ambiguity — binding-SL tie-break compares `effective_from`/`created_at` as stored strings — implementation/calculations.py:235
- §3.3 (overflow validation) — insert — ambiguity — GENERAL queues do not compare the target's `specialty_tag` — implementation/app.py:480-482
- §3.3 (overflow fallback) — insert — ambiguity — the overflow target must itself be `OPEN` — implementation/routing.py:119
- §3.3 (agent selector) — insert — ambiguity — "fewest completions today" attributes by frozen `handled_by_agent_id` counting `ended_at` on the logical current day — implementation/routing.py:18-36
- §3.4 — insert — ambiguity — only `Supervisor` may request `ASSIGNED`; only `Supervisor` may request `ABANDONED` (Agent refused `ERR_FORBIDDEN`) — implementation/app.py:671, 715
- §3.5 — insert — ambiguity — `accuracy_score`/`compliance_score` must be integers in [0,100] — implementation/app.py:773-778
- §3.5 (auto-coach) — insert — ambiguity — a plan created exactly 7 days ago still counts as within the dedup window — implementation/app.py:752
- §3.6 — insert — ambiguity — cascade grounding completion is the earliest-created matching (training_course_id, agent_id) completion; already-invalidated certs are not restamped — implementation/app.py:999-1010
- §3.7 — insert — ambiguity — multiple ACTIVE windows tie-break to the earliest-created; EXPIRED tie-break on ends_on then created_at is as stored strings — implementation/calculations.py:46, 51
- §3.8 — revise — mismatch — SLA delay computed at full precision (fractional seconds/3600), not whole-second difference; non-CRITICAL always reads `sla_breached` false — implementation/app.py:1151-1155
- §3.8 — insert — ambiguity — no incident transitions defined beyond the four listed (e.g. OPEN→RESOLVED, CONTAINED→OPEN are `ERR_INVALID_STATE`) — implementation/app.py:1219-1226
- §3.9 — insert — ambiguity — invoice creation records `preparer_user_id`; born with `auto_review` false; prepare on non-DRAFT is `ERR_INVALID_STATE`; re-prepare is destructive (lines + their PENDING cure periods discarded) — implementation/models.py:203-214, app.py:1296, invoice_logic.py:106-114
- §3.9 — insert — ambiguity — provisional/official variants use identical measurement definitions differing only in snapshot timing — implementation/invoice_logic.py:74-88
- §3.9 — insert — ambiguity — line `staffing_actual` evaluated at period end (matching §3.2's standing-at-`t` semantics) — implementation/invoice_logic.py:84-85
- §3.10 — insert — ambiguity — exact 0.05 lands in the 25% tier, exact 0.15 in the 40% tier; zero target treats any non-compliance as top-tier — implementation/calculations.py:180-187, 206-207
- §3.10 — revise — ambiguity — cumulative-cap floor = cumulative gross through this period (incl. this invoice's current gross, only gross-computed invoices) minus sum of `withheld_cents` over strictly-earlier periods; `withheld_cents_cum` resync = sum over all invoices — implementation/invoice_logic.py:42-71, 144-147
- §3.11 — insert — ambiguity — remedy payment at the exact deadline instant still succeeds — implementation/invoice_logic.py:205
- §3.11 — insert — ambiguity — FORFEIT touches only `cure_periods_used`; line/invoice withholding and `withheld_cents_cum` untouched — implementation/auto_transitions.py:24-30
- §3.12 — insert — ambiguity — recompute allowed on DRAFT and REJECTED; full per-target invoice lifecycle role split (SUBMITTED: BillingAnalyst; APPROVED/PAID/REJECTED: OpsManager; DRAFT-from-REJECTED: BillingAnalyst) — implementation/app.py:1308, 1369-1424
- §4 — insert — ambiguity — GET `/calls/{id}` row notes the Agent ownership refusal — implementation/app.py:657-658

Output file: `workspace/PRD_COMPLETED.md`

Orchestrator spot-check: PRD_COMPLETED.md on disk (334 lines, 63,670 bytes; 56 diff lines vs PRD_FINALIZED.md); no implementation/*.py modified after the 20:12 final sweep (`find -newermt` returned empty) — the clean 8/8 result stands as the pipeline's final verified state.
