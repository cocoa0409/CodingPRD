# Worklog — task_3447_crayon_manufacturing_color_retirement_experience_attraction

## Step 1: Create Task Directory — 2026-10-02T04:48:56.000Z

Task directory was pre-allocated by the caller: `./tasks/task_3447_crayon_manufacturing_color_retirement_experience_attraction` with `workspace/` inside. Verified it exists and is empty; no new index computed, no other task_* directory created. Difficulty instruction for scaffold-generator: "Generate task much harder than expert level!"

## Step 2: Generate Scaffold — 2026-10-02T06:10:00.000Z

All three artifacts are complete and verified. Final summary:

## Deliverables

All three files in `/home/ubuntu/github/CodingPRD/tasks/task_3447_crayon_manufacturing_color_retirement_experience_attraction/`:
- `SCAFFOLD.yaml` (1550 lines) — §1.0–§1.7 only, no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1829 lines) — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (3211 lines) — single top-level key `scaffold_corner_design`

## Counts

- **Entities: 13** — Color, PigmentBatch, Formula, VoteCampaign, SafetyTest, AssortmentSpec, ProductionRun, InventoryLot, RetailAllocation, LicensedLine, AttractionSession, Ticket (absorbs school-group scheduling via kind=GROUP + waitlist), RecallCase. Flat topology, `api_prefix: /crayon-works`, clock endpoint unprefixed.
- **Endpoints: 37** (hard ceiling 38 respected; consolidated via one `transition`/`decision` verb endpoint per state machine, cascade-created SafetyTest/RecallCase/InventoryLot, filtered-list GET covering all 3 ProductionRun FKs in one endpoint).
- **Errors: 34** (top of band).
- **Roles: 11** (all opaque; segregation_of_duties model — batch creator ≠ certifier, formula submitter ≠ approver, line submitter ≠ brand approver; Licensor identity-bound to `licensor_user_id`).
- **State machines: 12** — cyclic (Color intro/retirement vote loops, Formula revision loop, LicensedLine two-party negotiation loop, ProductionRun hold-resume, InventoryLot deplete-revive), branching (SafetyTest PASS/FAIL, RetailAllocation, Ticket fork by kind), epoch-driven linear (VoteCampaign, AttractionSession), compound/auto (RecallCase).
- **Calculations: 9** — vote_tally (weighted_scoring), retail_allocation_waterfall (waterfall_allocation), ticket_dynamic_price (tiered_pricing), packing_penalty (aggregation w/ pinned rounding order), licensed_royalty (constraint_propagation, pinned evaluation order), recall_severity_classification (threshold), session_booked_units, run_production_mass_balance, spec_boxes_reconciliation; 4 with explicit divergent variants.
- **Complexity layers (4)**: optimistic_concurrency (2 OCC rules), cascading_side_effects, ops_run_checkpoint, version_pinning_on_approval.
- **§1.8 instances: 27 — exactly 3 per rule_id** (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
- **§1.9: 80 non-stub instances + 7 `excluded_because` stubs**, spread over all 9 taxonomy sections (entities 12, state_machines 22, calculations 7+4 stubs, validations 9, endpoints 6, errors 10+1 stub, rbac 6, complexity_layers 4+1 stub, consistency_model 2).

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_3447_crayon_manufacturing_color_retirement_experience_attraction/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_3447_crayon_manufacturing_color_retirement_experience_attraction/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_3447_crayon_manufacturing_color_retirement_experience_attraction/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    37
  §1.1 entities declared:     13
  §1.8 instances scanned:     27
  §1.9 instances scanned:     80
  Calls scanned (§1.8+§1.9):  1444

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Beyond lint, I ran custom audits: zero unbound `${var}` placeholders across 1444 calls, all 114 instance names unique, all `excluded_because` refs resolve, all literal dates ≥ the 2026-09-01T00:00:00Z clock default (stated in the clock endpoint description), all 34 error codes referenced, all action enums match endpoint semantics, all grounds refs resolve, no forbidden concurrency vocabulary. Every formula-derived assert literal (156/131 waterfall, 0.55 tally boundary, 2070/38250/20000/2500 prices, 76-vs-75 rounding divergence, 16000/12794 royalties, 1000-unit CLASS_II boundary, cooling/archive date arithmetic) was computed in Python before pinning.

## Self-audit of the nine differentiation clauses

R1 spans three distinct entity domains (RetailAllocation/InventoryLot boxes, VoteCampaign/Color ballots, LicensedLine royalty). R2 hits all three modes: (a) 3-input non-linear ticket pricing, (b) pinned per-line-then-sum rounding in packing penalties, (c) pinned evaluation order in the royalty waterfall. R3's three cyclic machines sit on three different entities (Color, LicensedLine, ProductionRun). R4's cascades originate from three different triggers (certification-decision REJECT depth-4, epoch tally depth-3, formula APPROVE depth-3) with each hop caused by the previous link. R5 uses three distinct error-category pairs (state×business_safety, business_temporal×business_constraint, state×business_referential). R6's boundaries are three different metrics on three different endpoints (weighted ratio via epoch tally, integer seat count via POST /tickets, variance units via run transition). R7 crosses three different entity pairs (Formula←SafetyTest, ProductionRun←Formula/PigmentBatch/AssortmentSpec, Ticket←AttractionSession). R8 uses three different interval semantics on three resources (half-open+buffer on venue-date sessions, closed-interval on per-color campaign windows, full containment in licensed terms). R9 conserves three different quantities (session booked_units == active-ticket sum, lot mass balance on_hand+committed+shipped == received, run crayon mass balance packed == boxes×box_size + waste). One design bug was caught and fixed during authoring (ERR_SPEC_DEPRECATED was shadowed by the entry-color check — the spec's derived DEPRECATED status is now the single run-gate for retired colors), and a pin-then-bump ordering issue in BRAND_APPROVE was corrected so REINSTATE's freshness check is satisfiable.

[Orchestrator verification: all three YAMLs parse; SCAFFOLD.yaml has no design keys; api_prefix=/crayon-works (domain-confirmed, not foreign); counts match report (13 entities / 37 endpoints / 34 errors / 11 roles / 12 SMs / 9 calcs / 27 §1.8 / 80+7 §1.9); lint re-run independently by orchestrator — clean verdict reproduced.]

## Step 3: Copy Shared Files — 2026-10-02T06:11:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3447_crayon_manufacturing_color_retirement_experience_attraction/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T06:35:00.000Z

The PRD is complete and fully verified.

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_3447_crayon_manufacturing_color_retirement_experience_attraction/workspace/PRD.md` — 347 lines, 9,544 words, 67.4 KB. The line count sits below the 700–1100 estimate only because the prose uses dense, long-form paragraphs; the byte volume is ~2.4x the skill's example PRD, consistent with a top-of-band scaffold. Written incrementally in 9 chunks (Write + quoted-heredoc appends), with a mid-build tail check and a final end-of-document confirmation (file ends cleanly at the §5 table's last row, not mid-sentence).

**Section list**: §1 Introduction (3 paragraphs) · §2 Global Specifications — 2.1 Roles/RBAC (all 11 roles, opaque-identity prose, Licensor `licensor_user_id` exception, GET-access shape), 2.2 Response Structure (byte-identical to `section-2.2-response-structure.md`, verified by diff), 2.3 Pagination, 2.4 Logical Clock & Epoch, 2.5 Common Resource Properties, 2.6 Numbers/Money/Rounding (all four rounding pins), 2.7 OCC, 2.8 Validation Pipeline (all 11 priority stages with error mapping and first-failure-wins), 2.9 Segregation of Duties (all 3 SoD pairs), 2.10 Season Window & 60-Day Lead Time · §3 Business Logic — 3.1 Colors & Voting, 3.2 Pigments/Certification/Recall, 3.3 Formulas & Safety Tests, 3.4 Specs & Production, 3.5 Allocation Waterfall, 3.6 Licensed Lines, 3.7 Sessions/Tickets/Waitlist, 3.8 Operations Epoch · §4 Endpoint table (4 columns, 37 rows) · §5 Error catalogue (2 columns, 34 rows).

**Coverage sweep (scaffold tokens vs PRD, all gaps patched)**:
- error_ids: 34/34 found · state names: 45/45 · calculation names: 9/9 · calculation constant names: 21/21 · constant values: 21/21 · endpoint paths: 37/37 · entity fields (backticked): 93/93 · endpoint input/query/path params (backticked): 60/60 · roles: 11/11 · enum values: 70/70.
- Three initial gaps were found and patched: `production_run_id` (added to §3.4), all 9 calculation names, and all 21 constant names (woven into their formulas' prose alongside the already-present values); OCC write-endpoint strings were also made explicit as method+path in §2.7. Re-run after patching: zero gaps in every class.
- Contract 3 (§3 path purity): 761 backticked tokens scanned in §3, 0 path tokens, 0 bare HTTP methods, 0 method+path combos.
- Quality scans: no fuzzy/approximating words, no operator pseudocode (`==`, `>=`, `+=`, `IN {…}` etc.) outside the verbatim JSON fences; a 69-phrase spot-check of the highest-risk rules (recall cascade hops, SHORTED newest-first ordering, packing rounding-order pin with the 76-vs-75 divergence example, royalty pinned evaluation order, head-of-line waitlist blocking, epoch 6-phase order, validation intra-category order, both revision loops, COMPLETED-not-terminal, spec deprecation as the single retired-color gate) — 69/69 present.

**Clock default**: stated verbatim in §2.4 and §4 — startup default exactly `2026-09-01T00:00:00Z`, never falls back to wall-clock, endpoint unprefixed at `/_clock/set_current_utc` with `to_iso8601`/`current_utc` named. **Both OCC rules**: stated in §2.7 prose with endpoint, occ field (`expected_assortment_spec_version` on allocation creation; `expected_formula_version` on every licensed-line transition), mismatch rejection `ERR_STALE_VERSION` (HTTP 412), the scaffold's rationale, the success-side version bump, and the explicit rule that no other endpoint takes a version field.

[Orchestrator spot-check: 347 lines, file ends cleanly at error-table rows; independent Python cross-check of SCAFFOLD.yaml vs PRD.md — all calculation constant names+values, all 37 endpoint paths, all 34 error ids present in PRD; clock default and unprefixed `/_clock/set_current_utc` confirmed; both OCC field names confirmed ×4.]

## Step 5: Generate Unit Tests — 2026-10-02T07:05:00.000Z

Generation complete and fully audited. Final report:

## Deliverables

**`test_helpers/` (1553 lines)** — under `/home/ubuntu/github/CodingPRD/tasks/task_3447_crayon_manufacturing_color_retirement_experience_attraction/test_helpers/`:
- `constants.py` (61) — every value transcribed from PRD prose (MIN_TURNOUT 10, thresholds 0.55/0.60, weight tables, season window 2027-06-01→2027-08-31T23:59:59Z, lead 60d, archive +30d, pricing tiers 0.5/0.8 with 0.9/1.25/0.85/0.75/1.15/0.80, packing 18.75/1.5/5, box sizes {8,16,24,64}, recall floors 1000/10000, cooling 7/14/30)
- `types.py` (386), `api_errors.py` (82, 34 errors registered with the framework), `api_client.py` (136 — 37 endpoint methods; clock endpoint is **unprefixed** `/_clock/set_current_utc` per PRD §4), `assertions.py` (165, incl. format-tolerant `assert_same_instant`), `factories.py` (139), `test_users.py` (72 — all roles opaque; `make_licensor_headers(licensor_user_id)` for the identity-bound Licensor), `fixtures.py` (487 — composite chains: `make_active_color`, `production_setup`, `production_setup_with_completed_run`, `two_color_run_at_packing`, `create_approved_licensed_line` with SoD-clean identities sm-1/qa-1, f-1/so-1, bm-1/lic-1/bm-2), `__init__.py` (25)

**`test_suite/` (3216 lines, 134 tests)** — `conftest.py` + 9 files: `test_01_colors_campaigns_epochs.py` (456, 19t), `test_02_vote_tally.py` (225, 9t), `test_03_pigments_certification_recall.py` (318, 12t), `test_04_formulas_safety.py` (267, 12t), `test_05_specs_production_runs.py` (568, 24t), `test_06_retail_allocations.py` (345, 14t), `test_07_licensed_lines_royalty.py` (399, 16t), `test_08_sessions_tickets.py` (490, 23t), `test_09_security_envelope.py` (78, 5t).

## Audit evidence
- **AST tag audit: CLEAN.** 27/27 §1.8 instances with exactly 2 tags; 80/80 non-stub §1.9 instances with exactly 1 tag; 0 untagged; 0 dangling tags; 0 tags on stubs; 0 duplicate corner tags; 134/134 functions tagged.
- **pytest `--collect-only -q`: `134 tests collected in 0.53s`**, no import/collection errors.
- **PRD verbatim citation pass**: all 177 docstring quotes of ≥8 words appear whitespace-normalized-verbatim in PRD.md (initial run found 24 elided/paraphrased quotes — all rewritten to exact PRD text, incl. `§` symbols and the `18.75 × 2` multiplication sign).
- Forbidden patterns: 0 skip/xfail, 0 "scaffold" mentions, 0 `implementation/` reads. Stub cross-references (7) all resolve to real §1.8 instances.

## Skipped instances
Only the 7 `excluded_because:` corner stubs (per spec, owned by their difficulty instances): `formula_approval_supersede_cascade_corner`, `waterfall_provisional_vs_final_variant_corner`, `tally_variant_divergence_corner`, `royalty_variant_divergence_corner`, `packing_penalty_rounding_order_corner`, `reinstate_with_stale_pin_returns_error`, `recall_cascade_end_to_end`. **No non-stub instance was skipped** — PRD covers every translated claim.

## Re-derivations / adjudications (noted per guard 3)
1. **`waitlist_promotion_head_of_line_blocking` setup order re-derived**: the yaml's creation order (30, 45, 10, 20) would CONFIRM the 10-unit group (30+10=40 ≤ 50) under the PRD's "created CONFIRMED when the whole group fits" rule, making the claimed precondition (G3 WAITLISTED, G4 CONFIRMED) unreachable. Test creates G1(30), G4(20) CONFIRMED first, then G2(45), G3(10) WAITLISTED — the asserted outcome is unchanged: refunding 20 leaves the 45-unit head blocking and never skips to the 10-unit entry; booked stays 30.
2. **`run_epoch_returns_counts_object`**: asserts `epoch_index` increments by exactly 1 between calls (plus opened counts 1→0) rather than absolute 1→2 — PRD §3.8 does not pin the numbering origin (two-reader rule).
3. **Instant-valued assertions** (`checked_in_at`, `introduced_on`, `retired_on`, `archive_after_date`, `cooling_until`) use instant-equality comparison, since PRD pins instants, not string formats (§2.5's 3-fractional-digit rule is stated for `created_at`/`updated_at` only).
4. **`missing_auth_headers`**: the instance's "no color was persisted" sub-claim is unobservable (PRD §4 has no list-colors endpoint); the 401 `ERR_UNAUTHENTICATED` claim is asserted in full.

[Orchestrator verification: independent AST audit reproduced — 134 tagged, 0 untagged, no difficulty instance <2 tags, no corner instance <1 tag, no dangling tags; `pytest --collect-only` collects 134 with no errors; skip/xfail grep matches are English prose only; constants spot-check (18.75 / 0.55 / season window / MIN_TURNOUT / lead-60 / recall floors) present in both PRD.md and test_helpers/constants.py.]

## Step 6: Generate Implementation — 2026-10-02T07:50:00.000Z

All checks pass. Final summary:

## Deliverable

Complete Python + Flask implementation in `/home/ubuntu/github/CodingPRD/tasks/task_3447_crayon_manufacturing_color_retirement_experience_attraction/workspace/implementation/` — 37 endpoints (36 under `/crayon-works` + unprefixed `/_clock/set_current_utc`), 13 entities, all state machines, 9 calculations, 34 error codes, 11 roles, 2 OCC rules. In-memory dicts only; no seeding; fresh process boots empty.

**File inventory (2,598 lines total, all modules < 300 lines):**
- `start.sh` (10) — guarded flask-import pip install, `exec python3 app.py`, foreground
- `requirements.txt` (1) — flask>=3.0
- `app.py` (78) — factory, envelope error handlers, clock endpoint, route registration (38 URL rules incl. Flask static)
- `constants.py` (112) — 54 constants
- `store.py` (86) — store + logical clock booting at exactly `2026-09-01T00:00:00Z`
- `errors.py` (50) — full 34-id catalog with PRD HTTP statuses
- `envelope.py` (46) — meta/response_type/data envelope, pagination meta
- `validation.py` (165) — pipeline stages 1–4 (auth, role, body shape, existence, pagination params)
- `calculations.py` (239) — tally, waterfall, ticket pricing, packing penalty, royalty, severity, session bounds, spec reconciliation
- `colors_votes.py` (188), `pigments_recall.py` (230, incl. depth-4 recall cascade), `formulas_safety.py` (208), `specs.py` (132), `runs.py` (289), `allocations.py` (186), `licensed.py` (169), `sessions_tickets.py` (243), `epoch.py` (166, six pinned phases)

**Constants cross-check (AST-based, identifiers only):** `AST check OK: every ALL-CAPS Name resolves; 54 constants defined exactly once in constants.py` — every import from constants resolves, no duplicates, no undefined-CONST bootstrap risk.

**Dead-check grep:** `OK: 34 ERR_* catalog ids each have definition + >=1 raise site; OK: 34 distinct ERR_* ids raised, all present in catalog (no KeyError→500 path); OK: every module-level function has >= 1 reference (route registration or call)`.

**Smoke test (self-run, dynamic ports 58395 then 53497; never hardcoded):** 66 checks, all green — creates per domain (color/batch/formula/spec/run/allocation/line/session/ticket), campaign open→vote→tally→color ACTIVE, SoD violations (403 `ERR_SOD_VIOLATION` ×3 surfaces), `ERR_CERTIFICATION_MARK_REQUIRED`, `ERR_FORMULA_NOT_APPROVABLE`, `ERR_SPEC_INVALID`, `ERR_PLANNED_START_TOO_SOON`, `ERR_BATCH_NOT_CERTIFIED`, OCC 412 `ERR_STALE_VERSION` on allocation create, season window 422, COMMIT→lot FIFO deduction→FULFILL, line SUBMIT→LICENSOR_APPROVE→BRAND_APPROVE with version pin, royalty GROSS recompute on read (600 = 0.1×6000), session overlap buffer (409) + exact-30-min-gap allowed, dynamic pricing 1035 = round(1000×0.9×1.15), GROUP waitlist→refund→promotion cascade (12420), `ERR_SESSION_FULL`, check-in window `ERR_TICKET_STATE`, retro-reject recall cascade (case OPEN, 2 runs affected, 88 units, CLASS_III, runs CANCELLED/QUARANTINED, lot QUARANTINED, line SUSPENDED), `ERR_RECALL_ACTIVE` gates, epoch CONTAINED→CLOSED, REINSTATE, paginated list (`limit=1, total_count=2, has_more=true`), envelope shape asserted on every response. One bug found and fixed by the smoke: allocation creation double-bumped `AssortmentSpec.version` (recompute + unconditional touch); now exactly +1 per PRD §3.5/§2.7.

**start.sh confirmation:** reads `$PORT` (default 10000 via `app.py:78`), binds `0.0.0.0`, `exec` foreground; verified via `bash start.sh` on a fresh dynamic port — prior state fully wiped on reboot (404 on previously created color). Only self-started PIDs were killed.

**Notable adjudications (PRD-literal choices):** user-supplied datetimes echoed verbatim; derived datetimes match the source string's fractional style; `created_at`/`updated_at` always 3-fractional-digit logical clock; vote weights held as `Decimal` internally (exact ratio boundary), serialized as float; session close pins `booked_units = 0` per the explicit epoch sentence; recall shorting capacity counts non-quarantined lots' `on_hand + committed`; epoch phase 5 may take OPEN→CONTAINED→CLOSED within one call if cooling already elapsed; `CERTIFY` on an already-CERTIFIED batch and re-recording a resolved safety test return 409/400 respectively (no dedicated catalog ids exist for those two undefined transitions).

[Orchestrator verification: independent boot smoke on dynamic port — clock set OK (unprefixed `/_clock/set_current_utc` returns current_utc), POST /crayon-works/colors creates PROPOSED color with envelope + 3-fractional-digit clock stamps + version 1, Consumer role correctly denied with ERR_UNAUTHORIZED; GET /crayon-works/colors list correctly absent per PRD §4; server killed by exact PID and reaped. Process-hygiene check: no orphan app.py processes attributable to this task (the one long-lived app.py on the host belongs to task_3360; transient pids observed were another pipeline's per-test sweep).]

## Step 7: Run Tests and Iterate — 2026-10-02T08:12:00.000Z

All 8 rounds pass 134/134. The final sweep's `results.1.json`–`results.8.json` remain in place in `workspace/implementation/` per the artifact-preservation rule.

## Summary

- **Iterations run:** 2 (sweep 1: 132/134 ×8 rounds with the same 2 deterministic failures; sweep 2 after fix: 134/134 ×8 rounds, all green).
- **Tests deleted:** none.
- **Fixes applied to `test_suite/`:** none.
- **Fixes applied to `test_helpers/`:** `/home/ubuntu/github/CodingPRD/tasks/task_3447_crayon_manufacturing_color_retirement_experience_attraction/test_helpers/fixtures.py` — added `make_sourcing_headers` to the module-level `from .test_users import (...)` (mirroring the existing `make_licensor_headers` re-export). The two failing tests call `fx.make_sourcing_headers("sm-1")` via the fixtures module namespace, but the function only lived in `test_users.py` and the package `__init__` — `fixtures.py` itself only imported it inside a function body, so the attribute lookup raised `AttributeError` before any request was issued.
- **Fixes applied to `implementation/`:** none — the implementation was already PRD-faithful for both rules (§3.2 batch starts in `QUARANTINE` with `created_by_user_id` from the registrar header; §2.8 stage 3 undeclared extra fields ignored).
- **Diagnostics applied:** STEP 0 failure detail (AttributeError, no HTTP traffic) → STEP 1a PRD verbatim coverage confirmed for both tests (PRD.md lines 175 and 135) → STEP 2 test-artifact bug in the helper layer, fixed at the import site. No assertion weakening, no deletions.
- **Sibling unasserted paths:** PRD §2.8 stage 3 says ignored-extra-fields "applies to all endpoints", but only the pigment-batch create path has a dedicated client-supplied-`status`/`version`/`created_by_user_id` spoof test (`test_batch_create_client_supplied_status_is_ignored_input`). Whether color, campaign, formula, spec, run, allocation, line, session, and ticket creates equally ignore spoofed server-owned fields (`status`, `version`, id-derived fields) is unasserted and remains an open PRD-alignment question for a later step.

[Orchestrator verification: all 8 `results.{i}.json` present in workspace/implementation/, each independently parsed — total 134, passed 134, failed 0, errors 0, skipped 0 in every round; fixtures.py:35 confirms the module-level `make_sourcing_headers` import; newest implementation/ source mtime is 07:50 (Step 6 era), predating the 08:09 sweep — Step 7 made zero implementation edits, consistent with its report.]

## Step 8: Finalize PRD — 2026-10-02T08:20:00.000Z

**ZERO-EDIT OUTCOME** — `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md` (347 lines each, 0% delta, matching md5 `d1db6b8f…`).

Per-item reasoning for each `<step_7_diff>` item:

- **`test_helpers/fixtures.py` re-export fix (the only fix applied).** Verified at `test_helpers/fixtures.py:34-35` — `make_sourcing_headers` now sits in the module-level `from .test_users import (...)` beside `make_licensor_headers`; the function itself lived in `test_users.py:34` all along. This is a pure Python packaging bug (AttributeError before any HTTP request was issued). It reveals no PRD silence and no PRD/impl mismatch — no pin-able behavioral choice exists to trace back to the PRD.

- **§3.2 batch born in `QUARANTINE` with `created_by_user_id` from the registrar header.** PRD.md line 175 already states this verbatim ("A new batch starts in `QUARANTINE`, and the registrar's `X-User-ID` is recorded as `created_by_user_id`"), and the implementation matches exactly (`implementation/pigments_recall.py:71-72` — `"status": "QUARANTINE", "created_by_user_id": user_id` inside the whitelisted `new_entity({...})`). The failing test quoted this PRD sentence verbatim; the failure was the fixture bug, not a behavioral gap. No edit.

- **§2.8 stage 3 undeclared extra fields ignored.** PRD.md line 135 already states this verbatim ("Undeclared extra fields are ignored: never echoed, never stored. … Applies to all endpoints."), and the spoof test (`test_batch_create_client_supplied_status_is_ignored_input`) quoted it verbatim. Implementation confirms the whitelist pattern at the batch site and everywhere else. No edit.

- **Sibling unasserted paths bullet.** Per the brief, this only becomes in-scope if it evidences a PRD sentence contradicting implementation. I enumerated every entity-creation and payload-handling site in `implementation/` to test the PRD's universal "applies to all endpoints" claim: all 13 `new_entity({...})` call sites (`colors_votes.py:61,105`, `pigments_recall.py:65,163`, `formulas_safety.py:65,86`, `specs.py:89`, `runs.py:127,214`, `allocations.py:54`, `licensed.py:65`, `sessions_tickets.py:89,156`) use explicit dict literals fed by `req_*`/`opt_*`/`data.get` extraction (`validation.py:43-104`); `new_entity` (`validation.py:138-150`) adds only server-managed fields; a grep for passthrough patterns (`update(data`, `**data`, `request.json`) found zero hits; serializers emit only declared fields; even nested spec `entries` are rebuilt as `{"color_id", "count"}` dicts (`specs.py:93`). The universal PRD claim matches universal implementation behavior — the bullet is a test-coverage observation only, belonging to the later completeness step. No edit.

No new mismatch was introduced: the file is byte-identical, verified with `diff -q` and md5sum.

[Orchestrator verification: `diff -q PRD.md PRD_FINALIZED.md` → byte-identical; md5 `d1db6b8fbb797c68817f934ba6cedd08` matches on both; 347 lines each.]

## Step 9: Complete PRD — 2026-10-02T08:35:00.000Z

All verification complete. The diff is fully verified against my edits, the sweep is green 8/8 at 134/134, and the background sweep process has exited. Final summary follows.

---

# Step 9 Summary — task_3447 PRD_COMPLETED.md

## Source vs. output
- `workspace/PRD_FINALIZED.md`: 347 lines, 67,391 chars (untouched)
- `workspace/PRD_COMPLETED.md`: 349 lines, 72,203 chars (+2 lines, +4,812 chars)
- Counts: **27 ambiguity-pins**, **1 mismatch-revision** (adjudicated defect), **1 implementation edit** (+2 consequent test-assertion repairs)

## Verbatim `diff PRD_FINALIZED.md PRD_COMPLETED.md`

```diff
58,59c58,59
< - The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
< - The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
---
> - The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`; twenty lowercase hexadecimal characters follow the prefix.
> - The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits. It is generated from the server's wall clock; the logical clock of §2.4 governs business rules and entity timestamps, never the envelope.
85a86,87
> Requests outside the endpoint catalogue of §4 still answer in this envelope: an unknown path is rejected with `ERR_NOT_FOUND` (HTTP 404), and an unsupported method on a known path is rejected with `ERR_INVALID_REQUEST` (HTTP 400).
>
88c90
< List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Both appear on list endpoints that declare them, such as the production-run list, which also accepts `limit` and `offset` alongside its domain filters.
---
> List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is bounded by a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Every list endpoint accepts both parameters. A `limit` below 1 or above 100, a non-integer `limit` or `offset`, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — out-of-range values are never silently clamped.
90c92
< Unless a subsection of §3 states a more specific ordering, every list endpoint returns resources sorted by `created_at` in ascending order; several collections add a per-collection monotonic sequence as the tie-breaker (for example, runs order by creation time and then `run_seq`, safety tests by creation time and then `test_seq`, and a session's waitlist by creation time and then `waitlist_seq`).
---
> Unless a subsection of §3 states a more specific ordering, every list endpoint returns resources sorted by `created_at` in ascending order; several collections add a per-collection monotonic sequence as the tie-breaker (for example, runs order by creation time and then `run_seq`, safety tests by creation time and then `test_seq`, and a session's waitlist by creation time and then `waitlist_seq`), and every collection without a named per-collection sequence breaks `created_at` ties by global creation order. Query filters are exact-match equality on the named field; a filter value that matches nothing yields an empty page, not an error.
98c100
< The logical clock's startup default is exactly `2026-09-01T00:00:00Z`. Before any clock-setting call has been made, the logical clock reads that instant, and it never falls back to wall-clock time on its own. A `PlatformAdmin` may move the clock to a supplied `to_iso8601` instant through the test-driving clock capability; the response reports the new value as `current_utc`. This capability is the one endpoint that lives outside the `/crayon-works` mount, at `/_clock/set_current_utc`.
---
> The logical clock's startup default is exactly `2026-09-01T00:00:00Z`. Before any clock-setting call has been made, the logical clock reads that instant, and it never falls back to wall-clock time on its own. A `PlatformAdmin` may move the clock to a supplied `to_iso8601` instant through the test-driving clock capability; the response reports the new value as `current_utc`, echoing the supplied string, and a `to_iso8601` value that is not a parseable ISO 8601 datetime is rejected with `ERR_INVALID_REQUEST` (HTTP 400). This capability is the one endpoint that lives outside the `/crayon-works` mount, at `/_clock/set_current_utc`.
111c113
< Every mutation counts, including system-driven ones: an epoch transition, a cascade that flips a spec to `DEPRECATED`, a recomputed aggregate such as `boxes_reserved`, and a `licensed_use_count` increment on a formula all refresh `updated_at` and advance `version` on the affected resource. No resource in this system is exempt from the common-fields convention.
---
> Every mutation counts, including system-driven ones: an epoch transition, a cascade that flips a spec to `DEPRECATED`, a recomputed aggregate such as `boxes_reserved`, and a `licensed_use_count` increment on a formula all refresh `updated_at` and advance `version` on the affected resource. No resource in this system is exempt from the common-fields convention. Both timestamps are stamped from the logical clock of §2.4. A recomputation that leaves every stored field unchanged is not a mutation: `updated_at` refreshes and `version` advances only when a field actually changes, and the read-time recomputations of §3.4 and §3.6 never advance either one.
135c137
< 3. **Request body shape.** Required fields are present, types and enum memberships are valid, and conditional-field rules are honored — `group_size` and `school_name` exactly when a ticket's `kind` is `GROUP`, `partner_name` exactly when a spec's `kind` is `CLASSROOM`. Undeclared extra fields are ignored: never echoed, never stored. Violations yield `ERR_INVALID_REQUEST` (HTTP 400). Applies to all endpoints.
---
> 3. **Request body shape.** Required fields are present, types and enum memberships are valid, and conditional-field rules are honored — `group_size` and `school_name` exactly when a ticket's `kind` is `GROUP`, `partner_name` exactly when a spec's `kind` is `CLASSROOM`. A stated numeric lower or upper bound on a field — such as `received_quantity_kg` above 0, `wholesale_price_cents` of at least 1, `planned_boxes` of at least 1, `requested_boxes` of at least 1, `royalty_rate` greater than 0 and at most 0.5, `start_minute` in [0, 1339], `duration_minutes` of at least 30, `capacity_units` of at least 1, `base_price_cents` of at least 0, or a `group_size` of at least 10 — is a request-shape rule unless a workflow names a more specific error for it. Undeclared extra fields are ignored: never echoed, never stored. Violations yield `ERR_INVALID_REQUEST` (HTTP 400). Applies to all endpoints.
140c142
< 8. **Temporal rules.** Date ordering and windows: `closes_on` strictly after `opens_on`, `session_date` not in the past, run end strictly after run start, and license `term_end` strictly after `term_start` (`ERR_DATE_ORDER`, HTTP 422); the sixty-day production lead time (`ERR_PLANNED_START_TOO_SOON`, HTTP 422); the season window on `requested_ship_date` (`ERR_SEASON_WINDOW`, HTTP 422); and containment of a licensed run's planned dates in the line's term (`ERR_LICENSE_TERM_WINDOW`, HTTP 422).
---
> 8. **Temporal rules.** Date ordering and windows: `closes_on` strictly after `opens_on`, `session_date` not in the past, run end strictly after run start, and license `term_end` strictly after `term_start` (`ERR_DATE_ORDER`, HTTP 422); the sixty-day production lead time (`ERR_PLANNED_START_TOO_SOON`, HTTP 422); and the season window on `requested_ship_date` (`ERR_SEASON_WINDOW`, HTTP 422). Containment of a licensed run's planned dates in the covering line's term (`ERR_LICENSE_TERM_WINDOW`, HTTP 422) is catalogued with the temporal rules but cannot be evaluated until a covering `APPROVED` line is known to exist, so it fires inside the stage-10 walk — after the formula-coverage, batch-certification, and spec-state gates, immediately after the `ERR_LICENSE_REQUIRED` gate (§3.4).
165c167
< A campaign carries the system's running ballot tallies: `votes_yes_weighted` and `votes_total_weighted`, both starting at 0, and `turnout_count`, the raw ballot count, also starting at 0. Its `outcome` — `PASSED` or `FAILED` — and its `tallied_at` instant remain null until the campaign is `TALLYED`. The campaign machine is epoch-driven: ...
---
> A campaign carries the system's running ballot tallies: `votes_yes_weighted` and `votes_total_weighted`, both starting at 0, and `turnout_count`, the raw ballot count, also starting at 0. Its `outcome` — `PASSED` or `FAILED` — and its `tallied_at` instant remain null until the campaign is `TALLYED`, at which point `tallied_at` is stamped with the logical-clock instant of the tallying epoch. The campaign machine is epoch-driven: ...
167c169
< While a campaign is `OPEN`, ... The response confirms `accepted`, echoes the `campaign_id`, and reports the `weight_applied`.
---
> While a campaign is `OPEN`, ... The response confirms `accepted`, echoes the `campaign_id`, and reports the `weight_applied` — the per-ballot segment weight, not multiplied by `count`. The weighted tallies (`votes_yes_weighted`, `votes_total_weighted`) and `weight_applied` are reported as JSON numbers.
177c179
< Certification is decided ... A decision attempted on a `REJECTED` batch is refused with `ERR_BATCH_TERMINAL` (HTTP 409), because `REJECTED` is terminal. A `CERTIFY` decision on a `QUARANTINE` batch ...
---
> Certification is decided ... A decision attempted on a `REJECTED` batch is refused with `ERR_BATCH_TERMINAL` (HTTP 409), because `REJECTED` is terminal; a redundant `CERTIFY` on an already `CERTIFIED` batch draws the same refusal. Within the business-safety stage, the segregation-of-duties check is evaluated before the certification-mark rule. A `CERTIFY` decision on a `QUARANTINE` batch ...
179c181
< A `REJECT` decision on an already `CERTIFIED` batch is the platform's recall trigger: the batch is retro-rejected to `REJECTED`, and if any production run references the batch, ... until the remaining committed demand fits within the `AVAILABLE` lots again; ...
---
> A `REJECT` decision on an already `CERTIFIED` batch is the platform's recall trigger: the batch is retro-rejected to `REJECTED`, the payload `reason` is stored as `rejection_reason` just as on a quarantine rejection, and if any production run references the batch, ... until the remaining committed demand no longer exceeds the sum of `boxes_on_hand` plus `boxes_committed` over the spec's non-quarantined lots; ...
183c185
< ... An `OPEN` case moves to `CONTAINED` once the epoch has verified the cascade has been applied to all affected runs, lots, allocations, and licensed lines. A `CONTAINED` case moves to `CLOSED` ...
---
> ... An `OPEN` case moves to `CONTAINED` once the epoch has verified the cascade has been applied to all affected runs, lots, allocations, and licensed lines; because the cascade is applied synchronously in the rejecting request, this verification always succeeds at the first epoch after creation, so every `OPEN` case becomes `CONTAINED` at the next checkpoint. A `CONTAINED` case moves to `CLOSED` ...
189c191
< Submission is the action `SUBMIT`, open to `Formulator` and `SafetyOfficer` alike. From `DRAFT`, ...
---
> Submission is the action `SUBMIT`, open to `Formulator` and `SafetyOfficer` alike; the remaining actions are decider-only, so a `Formulator` attempting `APPROVE`, `REJECT`, or `REQUEST_REVISION` is rejected with `ERR_UNAUTHORIZED` (HTTP 403), evaluated after the existence check and before the state gate. From `DRAFT`, ...
191c193
< ... It carries the `test_standard` applied — `ASTM_D4236` by default, or `EN71_3` — ... `recorded_by_user_id` captures the technician's `X-User-ID`. A failed test blocks ...
---
> ... It carries the `test_standard` applied — the submission cascade always assigns `ASTM_D4236`; `EN71_3` is a recognized value of the field but no current capability assigns it — ... `recorded_by_user_id` captures the technician's `X-User-ID`. Recording a result on a test that is no longer `SCHEDULED` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A failed test blocks ...
193c195
< ... both also obey the segregation rule, and both accept an optional `reason`. Any transition ...
---
> ... both also obey the segregation rule, and both accept an optional `reason`, which is accepted and not persisted on the formula. Any transition ...
203c205
< ... A run is born in `PLANNED` and receives a global monotonic `run_seq`; ...
---
> ... A run is born in `PLANNED` with `stage_before_hold` and `hold_reason` null, `packed_counts` null, and `packing_variance_units`, `packing_penalty_cents`, `boxes_produced`, and `waste_units` all 0, and receives a global monotonic `run_seq`; ...
205c207
< ... the computed penalty is still recorded against the run, and no inventory lot is created. ... in `AVAILABLE`, whose `boxes_received` ...
---
> ... the computed penalty is still recorded against the run, `boxes_produced` and `waste_units` remain at their initial 0, and no inventory lot is created. ... in `AVAILABLE` — or directly in `DEPLETED` when `boxes_produced` is 0, consistent with the availability cycle below — whose `boxes_received` ...
213c215
< ... the spec's `version` increments by 1 in the same request. Its `allocated_boxes_final` ...
---
> ... the spec's `version` increments by 1 in the same request — on every successful creation, including a zero-share creation that leaves `boxes_reserved` unchanged. Its `allocated_boxes_final` ...
215c217
< ... on every pool change — a run completing, a run being cancelled, or a lot being quarantined.
---
> ... on every pool change — a run being planned, a run completing, a run being cancelled, or a lot being quarantined.
223c225
< ... rejected with `ERR_STALE_VERSION` (HTTP 412) before anything else about the transition is considered. A formula's lines ...
---
> ... rejected with `ERR_STALE_VERSION` (HTTP 412) before anything else about the transition is considered. Action-level authorization follows the optimistic-concurrency check and precedes the state gate: the brand-side actions (`SUBMIT`, `BRAND_APPROVE`, `BRAND_REQUEST_REVISION`, `BRAND_REJECT`, `REINSTATE`) require `BrandManager`, and the licensor-side actions require a `Licensor` whose `X-User-ID` equals the line's `licensor_user_id`, else `ERR_UNAUTHORIZED` (HTTP 403). A formula's lines ...
229c231
< ... `REINSTATE` moves `SUSPENDED` back to `APPROVED` only when no `OPEN` or `CONTAINED` recall case touches the line's formula color, the line's formula is currently `APPROVED`, ...
---
> ... `REINSTATE` moves `SUSPENDED` back to `APPROVED` only when no `OPEN` or `CONTAINED` recall case touches the line's formula color — a case touches a color when its cascade quarantined a run whose spec contains that color, and a touching case rejects the reinstatement with `ERR_RECALL_ACTIVE` (HTTP 409), evaluated before the pin check — the line's formula is currently `APPROVED`, ...
231c233
< The line's `projected_royalty_cents` is a computed projection — the `licensed_royalty` rule — recomputed on every read of the line and again after any allocation or production-run mutation touching the line's formula color. Let the line's color ...
---
> The line's `projected_royalty_cents` is a computed projection — the `licensed_royalty` rule — evaluated lazily: it is recomputed on every read of the line and reflected fresh in transition responses, so it never reads stale after an allocation or production-run mutation touching the line's formula color, and a recomputation alone never advances the line's `version` or `updated_at` (§2.5). Let the line's color ...
239c241
< A `group_size` must be at least 10 and at most 100; above 100 the booking is rejected with `ERR_GROUP_TOO_LARGE` (HTTP 422). The session ...
---
> A `group_size` must be at least 10 and at most 100; above 100 the booking is rejected with `ERR_GROUP_TOO_LARGE` (HTTP 422), and below 10 it fails request shape with `ERR_INVALID_REQUEST` (HTTP 400). The session ...
255c257
< 1. **Campaign openings.** ... becomes `OPEN`, processed in `created_at` ascending order.
---
> 1. **Campaign openings.** ... becomes `OPEN`, processed in `created_at` ascending order with creation order breaking ties.
259c261
< 5. **Recall progressions.** ... move to `CLOSED`.
---
> 5. **Recall progressions.** ... move to `CLOSED`. The two movements are walked in that order within the phase, so a case whose cooling window has already elapsed before its first checkpoint moves `OPEN` to `CONTAINED` to `CLOSED` in a single epoch.
```

(The `...` elisions above are within-line context only; every changed line was replaced in full. The complete machine-verified diff is also saved at `/tmp/prd_completed_diff.txt`, 44,914 bytes, 26 hunks.)

## Per-change bullets

- §2.2 — revise — ambiguity — pinned `api_request_id` suffix (20 lowercase hex) — implementation/envelope.py:15
- §2.2 — revise — ambiguity — envelope `api_request_timestamp` comes from the server wall clock; logical clock governs rules/entities only — envelope.py:8-10 vs store.py:77-79
- §2.2 — insert — ambiguity — unknown path → ERR_NOT_FOUND 404; unsupported method → ERR_INVALID_REQUEST 400 — app.py:59-66
- §2.3 — revise — ambiguity — every list endpoint takes limit/offset; invalid values rejected with ERR_INVALID_REQUEST 400, never clamped — validation.py:115-135
- §2.3 — revise — ambiguity — collections without a named per-collection sequence tie-break by global creation order; filters are exact-match, no-match → empty page — validation.py:159-165, `_seq` sorts across all list endpoints
- §2.4 — revise — ambiguity — unparseable `to_iso8601` → ERR_INVALID_REQUEST 400; `current_utc` echoes the supplied string — app.py:32-37, store.py:81-83
- §2.5 — revise — ambiguity — entity timestamps stamped from the logical clock; unchanged recomputation is not a mutation; read-time recompute never advances version/updated_at — store.py:77-79, calculations.py:54-71 (`bump` flag), specs.py:108, licensed.py:86-88
- §2.8 stage 3 — revise — ambiguity — stated numeric bounds (quantity>0, price≥1, planned_boxes≥1, requested_boxes≥1, royalty_rate∈(0,0.5], start_minute∈[0,1339], duration≥30, capacity≥1, base_price≥0, group_size≥10) are request-shape ERR_INVALID_REQUEST — validations in pigments_recall.py:63, specs.py:75, runs.py:113, allocations.py:45, licensed.py:60, sessions_tickets.py:66-73,137
- §2.8 stage 8 — revise — **mismatch** — moved `ERR_LICENSE_TERM_WINDOW` out of stage 8 into the stage-10 walk (after formula/batch/spec gates and the ERR_LICENSE_REQUIRED gate). **Adjudication (a): defective as stated** — §2.8 stage 8 contradicted §3.4's own narrative ("with the run's planned dates fully contained in that line's term, a temporal-stage check" inside the linked-entity walk) and is unevaluable at stage 8 because containment presupposes a covering APPROVED line, which only the stage-10 gate establishes — runs.py:86-101
- §3.1 — revise — ambiguity — `tallied_at` stamps the tallying epoch's logical clock — epoch.py:32
- §3.1 — revise — ambiguity — `weight_applied` is the per-ballot segment weight (not × count); weighted tallies reported as JSON numbers — colors_votes.py:166-176, 43-44
- §3.2 — revise — ambiguity — redundant CERTIFY on an already-CERTIFIED batch → ERR_BATCH_TERMINAL — pigments_recall.py:186-187
- §3.2 — revise — ambiguity — within stage 7, SOD is evaluated before the certification-mark rule — pigments_recall.py:188-195
- §3.2 — revise — ambiguity — retro-rejection also stores payload `reason` as `rejection_reason` — pigments_recall.py:200-203
- §3.2 — revise — ambiguity — shorting stops when committed demand ≤ sum of `boxes_on_hand`+`boxes_committed` over non-quarantined lots — pigments_recall.py:87-103
- §3.2 — revise — ambiguity — synchronous cascade ⇒ every OPEN case is verified and CONTAINED at the next checkpoint — epoch.py:133-138
- §3.3 — revise — ambiguity — decider actions are SafetyOfficer-only; a Formulator attempting one gets ERR_UNAUTHORIZED after existence, before the state gate — formulas_safety.py:114-116
- §3.3 — revise — ambiguity — the submit cascade always assigns `ASTM_D4236` (EN71_3 recognized, never assigned) — formulas_safety.py:88
- §3.3 — revise — ambiguity — record-result on a non-SCHEDULED test → ERR_INVALID_REQUEST 400 — formulas_safety.py:189-190
- §3.3 — revise — ambiguity — formula decision `reason` accepted, not persisted — formulas_safety.py:112
- §3.4 — revise — ambiguity — run born with packed_counts null, hold fields null, counters 0 — runs.py:127-142
- §3.4 — revise — ambiguity — quality-hold path leaves boxes_produced/waste_units at initial 0 — runs.py:203-209
- §3.4 — revise — ambiguity — a zero-box completion creates its lot directly in DEPLETED — runs.py:221
- §3.5 — revise — ambiguity — spec version advances exactly 1 on every successful allocation creation, including zero-share — allocations.py:66-73
- §3.5 — revise — ambiguity — waterfall re-runs on run planning (pool change) — runs.py:144-146
- §3.6 — revise — ambiguity — line-transition action-level authorization sits after OCC, before the state gate — licensed.py:107-117
- §3.6 — revise — ambiguity — REINSTATE's recall-touch condition → ERR_RECALL_ACTIVE 409, before the pin check; "touches" = cascade quarantined a run whose spec contains the color — licensed.py:124-131, 91-96
- §3.6 — revise — ambiguity — royalty projection is lazy (recompute on read / transition response; never advances version for recompute alone) — licensed.py:82-88, 161
- §3.7 — revise — ambiguity — group_size below 10 → ERR_INVALID_REQUEST 400 — sessions_tickets.py:137-138
- §3.8 — revise — ambiguity — campaign-opening ties break by creation order — epoch.py:92-94
- §3.8 — revise — ambiguity — phase 5 can move a case OPEN→CONTAINED→CLOSED in one epoch when cooling already elapsed — epoch.py:133-143

**Known open item (§2.8 stage 3 "applies to all endpoints"): resolved as already-pinned.** Verified all ten entity-creation endpoints (`create_color`, `create_vote_campaign`, `create_batch`, `create_formula`, `create_spec` — which rebuilds entry dicts keeping only `color_id`/`count`, `create_run`, `create_allocation`, `create_line`, `create_session`, `create_ticket`) use whitelist field extraction; client-supplied `id`/`status`/`version`/`created_at`/`updated_at` are never read, stored, or echoed. No PRD edit needed.

## IMPLEMENTATION EDITS

1. **`workspace/implementation/colors_votes.py`, `cast_vote`** — POST /crayon-works/votes now returns HTTP 200 (was 201). PRD §4 explicitly enumerates "ballots" among the HTTP 200 returns, and §2.2 ties 201 to resource creation (a ballot returns a confirmation object, and no ballot resource exists in §2.5's thirteen). Adjudication rule (b): clear, self-consistent, implementable PRD claim that impl-gen deviated from — fixed impl rather than stripping the contract.
   - Consequent test-side repairs (assertions encoded the deviation, contradicting the PRD): `test_helpers/fixtures.py:105` (`cast_votes` 201→200) and `test_suite/test_02_vote_tally.py:29` (`validate_success(resp, 201)`→`200`). These were the only two 201-expecting vote sites (verified by grep across both trees).

**Post-edit 8-round sweep (run by me, results files preserved):**

| Round | passed/total |
|---|---|
| 1 | 134/134 |
| 2 | 134/134 |
| 3 | 134/134 |
| 4 | 134/134 |
| 5 | 134/134 |
| 6 | 134/134 |
| 7 | 134/134 |
| 8 | 134/134 |

All 8 result files exist at `workspace/implementation/results.{1..8}.json` with `passed == total == 134`.

[Orchestrator verification: PRD_COMPLETED.md exists at 349 lines with a real 54-changed-line diff over PRD_FINALIZED.md (not a silent no-op); impl edit confirmed — colors_votes.py mtime 08:27:30, both test-side repairs confirmed present (fixtures.py:105 asserts 200; test_02:29 `validate_success(resp, 200)`); all 8 results.{i}.json re-parsed — 134/134, 0 failed, 0 errors in every round, mtimes 08:31:48 postdate the impl edit, so the green sweep covers the edited implementation.]
