# Worklog — task_2985_executive_protection_travel_risk_management

## Step 1: Create task directory — 2026-09-06T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2985_executive_protection_travel_risk_management` and its `workspace/` subdirectory. Index pre-assigned by the orchestrating prompt (2985); no auto-allocation scan performed, per instruction (concurrent pipelines on this host).

## Step 2: Generate Scaffold — 2026-09-06T00:00:00.000Z

All three scaffold artifacts are complete and lint-clean.

## Deliverables

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 2914 (2912 after difficulty-directive strip) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2904 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4578 |

Top-level keys verified: `SCAFFOLD.yaml` has neither `scaffold_difficulty_design` nor `scaffold_corner_design`; the other two carry exactly one top-level key each. All three parse with `yaml.safe_load` and end at real structural boundaries.

## Counts

- **SCAFFOLD.yaml (§1.0–§1.7):** 13 entities, 49 endpoints, 6 roles, 7 state machines, 14 calculations (3 dual-variant pairs), 49 validations, 50 error codes, 2 concurrency rules. `domain_name: exec-protection-travel-risk`, `api_prefix: /exec-protection`, difficulty `expert_plus`.
- **§1.8 Difficulty Design:** 9 rules / 20 instances (2 per rule) / 458 calls.
- **§1.9 Corner Design:** 9 sections / **72 instances** — 46 full `test_recipe`s and 26 `excluded_because` stubs. Per section: entities 7, state_machines 16, calculations 15, validations 10, endpoints 5, errors 7, rbac 6, cross_cutting_complexity_layers 5, consistency_model 1.

## Lint

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(Coverage line: 49 endpoints, 13 entities, 20 §1.8 instances, 46 §1.9 recipe-bearing instances, 1135 calls scanned.)

Two violations were found on the first run and fixed: both captured `$.data.assignment_cost_cents` on `POST /detail-assignments`, where §1.1 declares the field as `cost_cents` (now captured together with `cost_basis`).

## Verified invariants

- All 72 §1.9 names are unique and none collides with the 20 §1.8 names; every stub cites a real `<rule_id> / <instance>` pair and carries no `test_recipe`.
- **All 50 error ids are triggerable** across §1.8+§1.9 (0 uncovered) — the last 22 were closed by the new `errors`, `rbac` and `cross_cutting_complexity_layers` sections.
- No forbidden simultaneity vocabulary; the only "concurrent" hits are the declared field `max_concurrent_engagements`.

## SCAFFOLD.yaml fixes made while authoring §1.9

1. The `ProtectiveDetailAssignment null -> CONFIRMED` precondition compared `certification_expires_at` against the leg's `depart_at` while `validations[priority=29]` compares it against the request's `ends_at`; the state-machine line now mirrors validation 29.
2. `validations[priority=40]` and the `ERR_NO_ELIGIBLE_VENDOR` catalog entry were broadened to cover a manual `POST /vendor-engagements` whose vendor mismatches the leg's country or the requested purpose — previously that documented precondition had no error code.

### Orchestrator note (post-subagent)

The scaffold generator copied the difficulty directive line "Generate task harder than expert level!" verbatim into `SCAFFOLD.yaml`'s `scenario:` block (line 8). Because `SCAFFOLD.yaml` is the sole input to the Step 4 doc generator, that line would have reached `PRD.md`. The orchestrator deleted the directive line and its trailing blank line from `SCAFFOLD.yaml` and re-verified the file still parses (13 top-level keys, `scenario` now begins "2985. Executive Protection..."). Grep for "harder than expert" across all three scaffold files now returns 0 hits.

## Step 3: Copy Shared Files — 2026-09-06T00:00:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-06T00:00:00.000Z

Step 4 complete.

**Output:** `workspace/PRD.md` — 451 lines, built in 10 verified appends (no single giant Write), ends at a real boundary (final row of the §5 table).

**Sections**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 12 subsections: 2.1 RBAC · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and Version Counters · 2.5 The Logical Clock · 2.6 Nested Paths and Left-to-Right Resolution · 2.7 Numeric Precision and Rounding Discipline · 2.8 Optimistic Concurrency on Planning Parents · 2.9 Segregation of Duties · 2.10 The Three Commitment Ledgers · 2.11 Validation Precedence · 2.12 Cascade Discipline
- §3 Business Logic & Workflows — 9 subsections: 3.1 Department Roster / Protectee Registry · 3.2 Threat Monitoring & Risk-Assessment Cycle · 3.3 Destination Advisories, Coverage Floors, Insurance Verification · 3.4 Trip Construction: Legs, Risk Bands, Advance Work · 3.5 Protective Details & Vendor Engagements · 3.6 Approval Ladder, Briefing, Provisional Commitment · 3.7 Check-Ins, Consent Boundaries, Duress · 3.8 Incident Response: Triage Fork and Join · 3.9 Settlement: Close, Final Cost, Perquisite Disclosure
- §4 Endpoint Definitions — 49-row table (Method | Path | Description | Authorized Role(s))
- §5 Error Code Catalogue — 50-row table (Error ID | HTTP Status)

**Coverage audit (mechanical, all clean)**
```
endpoints:            49/49  0 missing
errors:               50/50  0 missing
entities:             13/13  0 missing
state machines:        7/7   (RiskAssessment.status, Trip.approval_state,
                              Trip.readiness_state, ProtectiveDetailAssignment.status,
                              VendorEngagement.status, Incident.status,
                              InsurancePolicy.status)
state values:         27/27  0 missing
calculations:         14/14  (all expressed in prose, both variants where dual)
roles:                 6/6   0 missing
```

**Hard Contract 1 — Field-Name Coverage: PASS.** 131/131 `entities[].fields[].name`, 81/81 `endpoints[].input` identifiers (optional `?` markers stripped), and 80/80 enum values parsed out of `constraints` all appear as backtick tokens in PRD.md. 0 missing.

**Hard Contract 2 — Rule Coverage: PASS.** All 49 validations appear with their error id and gate condition; all 27 state transitions across the 7 machines are narrated including sibling-symmetric hops (`PENDING_REVIEW→DENIED` / `PENDING_COMPLIANCE→DENIED`, `READY→CLOSED` / `DEGRADED→CLOSED`, all three incident resolve edges); both OCC rules (`expected_trip_leg_version`, `expected_vendor_version`, HTTP 412) and all five cascades (A–E) are specified.

**Hard Contract 3 — §3 Path Purity: PASS.** 1075 backtick tokens scanned inside the `## 3.` … `## 4.` slice; 0 violations.

§2.2 verified byte-identical to `skills/prd-bench-doc-generator/section-2.2-response-structure.md`.

**Two scaffold issues resolved rather than propagated**

1. *Unsatisfiable submit-time briefing gate.* `Trip.approval_state`'s `DRAFT → PENDING_REVIEW` transition carries a precondition that `briefing_ack_at` be non-null when `max_leg_risk_band ∈ {HIGH, EXTREME}`, but validation priority 21 only permits the briefing-ack action while `approval_state ∈ {PENDING_REVIEW, PENDING_COMPLIANCE}` — so the gate can never be satisfied. Resolved in favour of the validations table (priority 32 puts the briefing requirement on the APPROVE decision). No submit-time briefing gate is in the PRD.

2. *Unmapped precondition.* The detail-assignment create precondition `RiskAssessment(...).status == APPROVED` has no `applies_to` entry in the validations table. Expressed in §3.5 and mapped to `ERR_ASSESSMENT_NOT_APPROVED`.

### Orchestrator verification (truncation guard)

`tail -20 workspace/PRD.md` shows 20 complete, well-formed `| \`ERR_*\` | <status> |` table rows ending with `ERR_SECURITY_BUDGET_EXCEEDED | 402`. The file terminates at a real structural boundary (end of the §5 catalogue table), not mid-sentence. Section headings present: §1 (line 3), §2 (11), §3 (178), §4 (340), §5 (396). No regeneration required. Grep for "harder than expert" / "SCAFFOLD" in PRD.md: 0 hits — the difficulty directive did not leak.

## Step 6: Generate Implementation — 2026-09-06T00:00:00.000Z

All Step 6 work is finished and verified. Nothing is left running and the scratch dir is cleaned.

## Deliverable

`workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | foreground launcher, `cd "$(dirname "$0")"`, `$PORT` (default 10000), `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0.0` |
| `app.py` | 56 | app factory, blueprint registration, `ApiError`/`HTTPException`/`Exception` handlers, `0.0.0.0` bind |
| `errors.py` | 121 | all 50 error ids -> HTTP status + default message |
| `util.py` | 177 | logical clock default, instant parse/format, Decimal helpers, ROUND_HALF_UP, Decimal-preserving JSON encoder |
| `store.py` | 164 | 13 in-memory dicts, `audit_row`/`event_row`/`touch`, query helpers |
| `envelope.py` | 58 | object/list/error envelopes with `req_`+20-char ids and clock-derived timestamps |
| `auth.py` | 86 | 6 roles, `endpoint(*roles)` decorator, executive ownership, opaque CO/SysOp ids |
| `payload.py` | 208 | typed field extractors, interval rule, pagination |
| `calc.py` | 420 | enums/constants + all calculation functions |
| `serializers.py` | 273 | one per entity; audit quad on rows, `id`/`created_at` only on the two event types |
| `derive.py` | 642 | 11 FK resolvers, recomputes, cascades A-D, vendor selection, ledgers |
| `routes_core.py` | 296 | staff, protectee registry, consent, survey, exposure signals, disclosure, clock |
| `routes_risk.py` | 299 | destination ratings, insurance, assessment cycle |
| `routes_trips.py` | 624 | trips, legs, approval chain, briefing, check-ins, incident report, close |
| `routes_ops.py` | 509 | advance progress, detail assignments, vendors, engagements, incident triage/resolve/close |

3944 lines total; every file passes `ast.parse`. No `__pycache__`, no stray files.

## Coverage (machine-verified, not asserted)

- **Endpoints: 49/49.** Diffed the Werkzeug url_map against the PRD §4 table by (method, normalised path): zero missing, zero extra.
- **Error codes: 50/50.** The set of `ERR_*` in PRD.md equals `ERROR_STATUS`'s keys equals `DEFAULT_MESSAGE`'s keys, and every one of the 50 is actually raised somewhere in the code (no dead declarations).
- **State machines: 7** — assessment, policy, trip `approval_state`, trip `readiness_state`, assignment, engagement, incident.
- **Calculations: 14** PRD-declared formulas across 23 helper functions.
- **Validations: 49** implemented in §2.11's declared 14-level precedence order — call-site ordering is auth -> role -> shape -> typed field -> interval -> existence (path before body) -> ownership -> OCC -> domain bands -> state -> resource-specific.
- **RBAC: 6 roles**; ComplianceOfficer and SystemOperator ids are treated as opaque and never compared to entity ids.

## Storage

In-memory only. A persistence audit for `sqlite|shelve|pickle|open(|json.dump(|.write(|tempfile|/tmp` across all 14 modules returns nothing. A fresh boot showed clock at exactly `2026-08-01T00:00:00.000Z` and `total_count: 0` on every list endpoint — nothing is seeded.

## Smoke tests

Five probes on port 21500: 401 `ERR_UNAUTHENTICATED`, 403 `ERR_UNAUTHORIZED_ROLE`, 422 `ERR_INVALID_REQUEST`, 201 create-executive, 404 `ERR_EXECUTIVE_NOT_FOUND` — all with correct envelope shape.

Then a **91-call end-to-end scenario** covering the full lifecycle. **All 91 returned the expected status, including all 17 deliberate negative cases** (SoD 409, duplicate rating 409, duplicate leg sequence 409, leg outside window 422, waiver 403, stale leg version 412, stale vendor version 412, premature decision 409, wrong-stage approver 409, track-incompatible triage 422, premature resolve 409, premature close 409, re-suspend 409, `limit=0`/`offset=-1` 400).

Spot-checked derived values on the wire: exposure 39.09 (decayed) vs assessment snapshot 40.00 (full weight), composite 60.00 -> HIGH, FR composite 29.00 -> MODERATE with a 50,000,000-cent coverage floor, planned 144 h / 1,620,000 cents -> final 142 h / 1,597,500 cents FINAL, perquisite split 4,389,500 -> 438,950 taxable + 3,950,550 business at rate `0.10`, ledger settling to committed 0 / spent 4,389,500 / `open_degraded_trip_count` 0.

Both servers were killed by their specific PIDs (1289260, 1367825) located via `ss -ltnp`; both ports confirmed free. No `pkill` was used at any point.

## PRD/SCAFFOLD disagreements, all resolved toward PRD.md

1. **Incident triage: track compatibility before vendor selection.** §3.8's prose orders the compatibility check before activation, contradicting §2.11's within-band-(b) listing. Followed document order (§3.8). Vendor selection stays before the insurance gates.
2. **Engagement creation: capacity before eligibility.** §2.11 puts `ERR_VENDOR_CAPACITY_EXCEEDED` ahead of `ERR_NO_ELIGIBLE_VENDOR`; the §3.5 narrative implies the reverse. Followed §2.11.
3. **Assessment review SoD applies to both outcomes**, not just APPROVE — per §2.9 plus §2.11 item 8.
4. **Trip decision: readiness precondition before the briefing gate** — §2.11 item 9 precedes item 11.
5. **`ERR_APPROVAL_LEVEL_MISMATCH` is narrow**: only the cross-stage case (Director at `PENDING_COMPLIANCE`, CO at `PENDING_REVIEW`). Every other non-pending state yields `ERR_TRIP_INVALID_APPROVAL_STATE`. SoD is skipped for ComplianceOfficer, whose id is opaque.
6. **Incident-triage cadence uses `check_in_interval_hours(duress_active, "DEGRADED", band)`** rather than §3.8's literal "forced to 2 hours", so a duress-active trip correctly stays at 1 h.
7. **The EXTRACTION branch does not re-derive `lead_agent_covered`** — leg versions are absent from §3.8's enumerated touched-row set.
8. **`resolution_note` on incident resolve is accepted and validated but not persisted** — no such field exists on the incident entity in §2.
9. **A withheld check-in stores and emits both location fields as null**, per the consent-snapshot rule.
10. Two fidelity defects found during self-review and fixed: `report_incident` now raises `ERR_INCIDENT_NOT_FOUND` (not `ERR_TRIP_LEG_NOT_FOUND`) for an unresolvable `affected_leg_sequence_no`; and body-level staff FKs (`authored_by_staff_id`, `created_by_staff_id`) are now existence-checked to `ERR_STAFF_NOT_FOUND`.

Isolation was respected throughout: `test_suite/`, `test_helpers/`, both design YAMLs, and all sibling `task_*/` directories were never read, listed, globbed, or grepped. `worklog.md` was not touched. Only `.scratch/step6` was removed; the sibling `.scratch/step5` (still in use by the concurrent test generator) is intact.

## Step 5: Generate Unit Tests — 2026-09-06T00:00:00.000Z

Step 5 is complete.

## Deliverables (both at the task root, nothing under `workspace/`)

- `test_helpers/`
- `test_suite/`

```
test_helpers/__init__.py                       62
test_helpers/api_client.py                    364
test_helpers/api_errors.py                    125
test_helpers/assertions.py                    185
test_helpers/constants.py                     354
test_helpers/factories.py                     356
test_helpers/fixtures.py                      572
test_helpers/test_users.py                     98
test_helpers/types.py                          28
test_suite/conftest.py                         31
test_suite/test_01_registry_and_protectees.py 310
test_suite/test_02_exposure_and_assessments.py 450
test_suite/test_03_destinations_and_insurance.py 544
test_suite/test_04_trip_construction_and_advance.py 457
test_suite/test_05_detail_assignments.py      454
test_suite/test_06_vendors.py                 649
test_suite/test_07_approval_ladder.py         535
test_suite/test_08_checkins_and_incidents.py  595
test_suite/test_09_settlement_and_disclosure.py 566
test_suite/test_10_auth_and_rbac.py           570
                                             7305 total
```

## Counts

- **85 tests**, 65 distinct Design tags, **40 queue A / 45 queue B**.
- Queue A: all **20** instances have **>=2** tests (verified per-instance).
- Queue B: **45 of the 46** non-stub instances have >=1 test; the 26 `excluded_because:` stubs were not translated, as instructed.
- Audit result: `problems: 0` — every test has exactly one `Design:` line, every tag's section/rule_id matches the owning yaml block, every tag names a real instance, and every `PRD §X.Y: "..."` citation is byte-verbatim against `workspace/PRD.md`.
- All 10 test modules import cleanly under `sys.path` rooted at the task dir; no duplicate test function names anywhere in the suite.

## SKIPPED design instances (1)

- `Corner/endpoints/consent_patch_stores_the_scope_and_expiry_it_is_given` — the recipe PATCHes `consent_scope: "FULL_ITINERARY"`, which is not one of the PRD's three declared scopes (`NONE` / `TRIP_ONLY` / `CONTINUOUS`, PRD §3.1). Under PRD §2.11 priority 3 that payload is `ERR_INVALID_REQUEST` 422, so the instance's asserted 200-with-stored-scope outcome is not uniquely derivable from the PRD. Left as a gap — no weakening, no xfail, no placeholder.

## Design-vs-PRD conflicts resolved PRD-first (assertion follows the PRD, instance still covered)

1. `Corner/errors/close_rejects_an_unended_trip_then_an_open_incident_then_an_unsettled_detail` — design asserts a final close total of `112500`; PRD §3.9's third component adds the `response_cost_cents` of CLOSED incidents (3,060,000), so `3_172_500` is asserted (taxable 317,250 / business 2,855,250 / spent 3,172,500).
2. `Corner/rbac/an_executive_cannot_read_or_act_on_another_protectees_records` — the recipe's consent PATCH uses `FULL_ITINERARY`, which would return 422 ahead of ownership (§2.11: shape is priority 3, ownership priority 7); the test sends `TRIP_ONLY` so `ERR_NOT_RESOURCE_OWNER` 403 is the uniquely-derived outcome.
3. The destination-rating supersede cascade instance asserts `DEGRADED` with interval 2, but its own LEAD_AGENT window does not cover its leg, so the PRD-derived `ADVANCE_IN_PROGRESS` is asserted.

## Path proof

```
$ ls -d .../task_2985_.../{test_helpers,test_suite}
.../test_helpers
.../test_suite
$ ls .../workspace/
INSTRUCTION.md  PRD.md  implementation  summarize_sweep.py  sweep.sh
$ find .../workspace -maxdepth 3 -name test_helpers -o -maxdepth 3 -name test_suite
(no output)
```

No test dirs exist under `workspace/`; nothing was read from or written to `workspace/implementation/`; `worklog.md` untouched. Scratch artifacts (the auditor `t2985_check.py` and coverage `t2985_cover.py`, useful for Step 7) remain in `.scratch/step5/`; the parent `.scratch/` was never deleted. No servers were started, so no `pkill` was ever needed.

### Orchestrator verification

`ls workspace/` shows only `INSTRUCTION.md  PRD.md  implementation  summarize_sweep.py  sweep.sh` — no stray `test_helpers/` or `test_suite/` under `workspace/`, so the known Step 5 misplacement failure did not occur. `grep -c "def test_"` across `test_suite/*.py` totals 85, matching the subagent's count. `workspace/sweep.sh` (setsid-safe 8-round sweep with a `SWEEP_DONE` sentinel) and `workspace/summarize_sweep.py` (per-round `results.$i.json` union summarizer, keyed on `status`/`error_message`) were pre-written by the orchestrator for Step 7's use.

## Step 7: Run Tests and Iterate — 2026-09-06T00:00:00.000Z

Clean sweep achieved.

## Summary

**Iterations run:** 3

**Final per-round pass counts:** rounds 1–8 all `85/85` (union of failing tests across all 8 rounds = 0)

**Tests deleted:** none. Every failing test passed STEP 1a (PRD verbatim coverage) and STEP 1b (unique derivability); all three failures were STEP 2 test-artifact bugs.

**Fixes applied to `test_helpers/`:** none — the bugs were local to two test modules, not to shared fixtures.

**Fixes applied to `test_suite/`:**

- `test_suite/test_06_vendors.py` — `_cascade_world()` (the shared builder for `test_suspending_a_vendor_cancels_its_engagement_and_clears_its_hours` and `test_the_suspension_cascade_reaches_the_check_in_cadence`), two bugs:
  1. Its `fx.create_trip(...)` relied on the factory default `primary_destination_country_code=COUNTRY_PT`, but the world only publishes an `SO` rating — so the PRD-faithful server correctly returned `ERR_DESTINATION_RATING_NOT_FOUND` (§2.6: "a trip creation whose `primary_destination_country_code` … names a country for which no rating has been published"). Added `primary_destination_country_code=c.COUNTRY_SO`, matching the majority call sites in `test_03` and `test_07`.
  2. It called `fx.ack_briefing()` *before* `fx.submit_trip()`, i.e. while `approval_state` was still `DRAFT`, so the server correctly returned `ERR_TRIP_INVALID_APPROVAL_STATE` (§3.6: acknowledgement "is permitted only while the trip's `approval_state` is `PENDING_REVIEW` or `PENDING_COMPLIANCE`"). Swapped the two calls.

- `test_suite/test_10_auth_and_rbac.py` — `test_an_executive_cannot_read_or_act_on_another_protectees_records` compared the owner's post-attack `version` against `w.exec_row["version"]`, a snapshot taken at *registration* (version 1). The row has since legitimately advanced three times under PRD rules (residential-survey write, assessment-approval `threat_level` recompute, submission's `committed_budget_cents` commitment), hence `assert 4 == 1`. Replaced the stale snapshot with a `version_before` read taken immediately prior to the intruder's refused writes, which is the assertion the test actually means ("a refused consent revision must not mutate the protectee's row") and is strictly more faithful to PRD §2.4.

**Fixes applied to `implementation/`:** none. No implementation defect was found — all 85 tests pass against the untouched PRD-faithful server.

### Orchestrator verification (independent re-check of the sweep)

Ran `python3 workspace/summarize_sweep.py` over the 8 on-disk `results.$i.json` files (all mtime 05:27, all ~25.7 KB) rather than trusting the subagent's report. Output:

```
round 1..8: CLEAN  passed=85 total=85  non-passing entries=0
=== UNION OF FAILING TESTS ACROSS ALL ROUNDS: 0 ===
ALL 8 ROUNDS CLEAN: True
```

The summarizer's `total-passed` vs union-size cross-check raised no key-name warning, so this is a genuine clean sweep and not a schema-keying artifact. Removed the stray `workspace/implementation/__pycache__` left by the runs.

### Orchestrator decision on Step 8

Step 7 ran 3 iterations with 2 `test_suite/` files fixed, so the Step 8 skip condition (zero iterations beyond baseline) is **not** met and Step 8 will run. Note in advance, however, that Step 7 applied **0 `implementation/` fixes** and **0 deletions** — the three defects were purely test-artifact bugs (a factory-default country mismatch, a fixture call-order inversion, and a stale version snapshot), none of which reveals a PRD silence or a PRD/impl divergence. A byte-identical or near-identical `PRD_FINALIZED.md` is therefore the legitimate expected outcome of Step 8 here; the real alignment work falls to Step 9's full impl scan.

## Step 8: Finalize PRD — 2026-09-06T00:00:00.000Z

## Result

`PRD_FINALIZED.md` was created and is **byte-identical to `PRD.md`** (md5 `81348a13ab5e891d40d6800b6a01eb0a`, 451 lines each, 0% delta). **Zero edits.** All three Step 7 defects were test-artifact bugs whose governing behavior is already stated verbatim in `PRD.md` and matched exactly by `implementation/`.

## Per-diff-item verification (why no edit)

**Item 1 — `test_06._cascade_world()` trip create with an unrated country → `ERR_DESTINATION_RATING_NOT_FOUND`**
- Impl path: `routes_trips.py:103-111` (`create_trip` existence pass: `get_executive` → `get_staff` → `get_assessment` → `get_rating(primary_destination_country_code)` → `get_policy`), raising via `derive.py:72-76` (`get_rating` → `ERR_DESTINATION_RATING_NOT_FOUND`, 404 per `errors.py`).
- PRD §2.6 already says verbatim: "so does a trip creation whose `primary_destination_country_code` … names a country for which no rating has been published," and §5 pins the 404. Impl == PRD. Pure fixture bug (factory default `COUNTRY_PT` in a world that only published `SO`).

**Item 2 — `fx.ack_briefing()` before `fx.submit_trip()` → `ERR_TRIP_INVALID_APPROVAL_STATE`**
- Impl path: `routes_trips.py:383-393` (`acknowledge_briefing`: `get_trip` → `require_executive_owns` → state check `approval_state in ("PENDING_REVIEW","PENDING_COMPLIANCE")` → `briefing_ack_at = store.now()`). This is the only ack site; `briefing_ack_at` is also required at approval (`routes_trips.py:364`) and cleared by both cascades (`derive.py:516`, `derive.py:567`).
- PRD §3.6 already pins the permission window verbatim, and the rejection identifier is forced by §2.11 item 9 + §5 (`ERR_TRIP_INVALID_APPROVAL_STATE` is the only trip-approval-state error in the catalogue; 409). Ownership-before-state matches §2.11 (7 before 9). Considered inserting the error name explicitly, then rejected it: PRD uses the same unnamed-error style for the neighbouring decision-stage and approval-readiness gates (`routes_trips.py:349`, `:361`), which are outside the Step 7 diff, so a partial pin would add no determinacy and Step 9 owns any systematic pass. Pure fixture ordering bug.

**Item 3 — `test_10` stale `version` snapshot (`assert 4 == 1`)**
- Impl paths enumerated for the subject "Executive-row `version` advances": `store.py:70-86` (`touch` refreshes `updated_at` and bumps `version`, de-duplicated per request via `g._touched_rows`, i.e. exactly one increment per row per operation); every `touch(executive)` site — `routes_core.py:160` (consent revision), `:176` (residential survey), `:208` (exposure-signal append / score re-derive), `routes_trips.py:291` (submission budget commitment), `:622` (close settlement), `derive.py:270` / `:294` (degrade / recover — `open_degraded_trip_count`), `:479` (assessment-approval `threat_level`), `:587` (denial ledger restore).
- The three legitimate advances behind `version == 4` are `routes_core.py:176`, `derive.py:479`, `routes_trips.py:291`, each mutating a field PRD explicitly says that operation mutates (§3.2 survey write; §3.2 hop one `threat_level`; §3.6 `committed_budget_cents`). §2.4's universal rule plus §2.12 invariant one already determine all three; the §3.2 closing enumeration is illustrative, not exhaustive, and `touch`'s per-request de-duplication means the impl never double-bumps the protectee even when a cascade both re-levels a trip and degrades it — so no clarifying edit was needed and none could have been added without risking a false universal claim.
- The refused-write half is also determined: `auth.require_executive_owns` (`auth.py:74-78`) raises `ERR_NOT_RESOURCE_OWNER` before any mutation in `revise_consent` (`routes_core.py:152-162`), matching §2.11 (shape 3 → existence 6 → ownership 7) and §2.4.

No `implementation/` fix existed in the diff, so there was no impl-side divergence to mirror. Scratch dir `.scratch/step8/` was created and left empty; `PRD.md`, `worklog.md` and `PRD_COMPLETED.md` were untouched.

### Orchestrator note

Independently confirmed with `md5sum`: `PRD.md` and `PRD_FINALIZED.md` are byte-identical. Per the skill this is the *legitimate* outcome for Step 8 when Step 7 applied zero `implementation/` fixes — the only thing Step 8 is allowed to align is impl-pinned behavior revealed by the Step 7 diff, and all three Step 7 defects were test-artifact bugs. (A byte-identical **Step 9** output would by contrast mean the scan never ran; Step 9 is therefore being run as partitioned sequential passes with an explicit non-identity check.)

## Step 9: Complete PRD — 2026-09-06T00:00:00.000Z

Run as **four sequential module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md` (pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2–4 were forbidden from copying so as not to destroy prior edits). Partitioning was chosen because Step 8 made zero edits, which meant the entire alignment burden fell on Step 9, and a single-agent full scan of a 3,944-line implementation against a 451-line PRD reliably under-covers.

### Pass 1 — cross-cutting infrastructure + `routes_core.py` (18 edits, +5,767 chars)

Slice: `app.py`, `envelope.py`, `errors.py`, `util.py`, `store.py`, `auth.py`, `payload.py`, `serializers.py`, `routes_core.py`. Result: 451 lines, md5 `cc98cdcb…`, 16 ambiguity-pins + 2 mismatch-revisions.

Highlights: authentication validates only header presence/role-name membership (an unknown `X-User-ID` authenticates and only fails later at ownership/SoD/FK resolution); `api_request_id` is `req_` + exactly 20 chars of A–Z0–9; `api_request_timestamp` comes from the logical clock, not wall time; list tie-breaks are creation order and descending orderings tie-break descending; list filters are literal equality so an undeclared enum value matches no rows rather than 422, and undeclared query params are ignored; sub-millisecond precision is kept for comparisons but **truncated** on render; the clock accepts moves in either direction; score inputs are range-checked at supplied precision *then* rounded (>100 rejected even if it would round to 100.00); SoD never catches a `ComplianceOfficer` because its id is opaque; three transport-level ids outside the §5 catalogue (`ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500).
Two mismatch-revisions: §2.6's "before the sub-resource payload is examined at all" was removed (every route parses/validates the body *before* resolving the path parent, so a malformed body yields 422 even when the parent does not exist), and §2.11 item 5 gained a carve-out for the release's `actual_ends_at` interval check, which compares against a *stored* field and so runs after existence and before the state precondition.

### Pass 2 — `routes_risk.py` + `routes_trips.py` + their `calc.py`/`derive.py` paths (31 edits, +9,439 chars)

Result: 451 lines, md5 `ffaa6bdb…`, 24 ambiguity-pins + 7 mismatch-revisions.

Mismatch-revisions: composite score is **rounded then capped**, not capped then rounded; the draft assessment's derived components are `0.00` not `0`; Cascade B's version enumeration omitted the **protectee** (touched unconditionally by hop one); `perquisite_rate_applied` starts at `0.00`; Cascade D's version list omitted the affected **staff rows** and the protectee, and the denied trip keeps its `provisional_security_cost_cents`; the duress hop-two re-anchor is applied **after** the degradation edge and overrides its forward-only min-rule; the duress chain's `open_degraded_trip_count` increment is conditional on the trip still being `READY`.
Notable pins: authorship mismatches are `ERR_NOT_RESOURCE_OWNER` and are checked after both references resolve; the three decision-note minimums (`RETURN`/`REJECT`/`DENY`) are payload-shape checks at ladder position 3 while their sibling branches are bounded only by the 500-char max; an **empty** rating-revision body is a valid no-op that still runs the whole cascade and re-versions everything; `sequence_no` need not start at 1, be contiguous, or match chronology, and legs may overlap in time; re-acknowledging a briefing is permitted and re-stamps `briefing_ack_at`; readiness reconciliation only ever lifts `ADVANCE_IN_PROGRESS → READY`; the auto-opened duress incident's fixed narrative `Duress check-in filed by the protectee.`; close moves readiness only, leaving `approval_state` `APPROVED` forever.

### Pass 3 — `routes_ops.py` + its ops-only `calc.py`/`derive.py` paths (23 edits, +9,480 chars)

Result: 451 lines, md5 `677dd191…`, 20 ambiguity-pins + 3 mismatch-revisions.

Mismatch-revisions: the MEDEVAC branch's cadence is the degraded value (2 h, or 1 h under duress) with `next_check_in_due_at` untouched, and the cadence rewrite happens on all three tracks even when the trip was already `DEGRADED`; the EXTRACTION branch explicitly decrements `committed_detail_hours` by the assignment's `planned_billable_hours` (the PRD had claimed the ledger "sums only `CONFIRMED` rows", which the impl does not do); and one narrow correction to a pass-2 sentence (see cross-pass note below).
Notable pins: `hours_between` is never handed a non-positive duration and a sub-minute positive window yields 0, with the 4-hour release floor applied after conversion; OCC `expected_*_version` values are plain integers so 0/negative fail at ladder position 10 rather than as shape errors; the trip-not-live rejection is `ERR_TRIP_INVALID_APPROVAL_STATE`, that id covering the `readiness_state = CLOSED` half too; engagement completion reads no body, never examines trip state (so an engagement is completable after its trip closed) and does not revisit the frozen cost; Cascade A hop three is provenance-agnostic and not reference-counted and re-derives legs of already-`CLOSED` trips; the residual vendor tie-break is registration order; incident resolve/close write only the incident row.
Carry-forward adjudications: rest-buffer both-sidedness, `active_overlapping_engagements`' half-open intersection and the EXTRACTION `starts_at > now` rule were already uniquely pinned; **Cascade A's victim ordering was deliberately left unpinned** because under the frozen clock and the one-`touch`-per-row-per-request rule every cross-victim observable is an order-independent sum, so a PRD claim would over-determine the impl.

### Pass 4 — reconciliation (11 edits, +3,507 chars)

Result: 451 lines, **135,008 chars**, md5 `397fe180a91bf4f264b3bdec958fdcf7`.

Mandate was to *fix* rather than report cross-pass seams. Four false universals were found and repaired: (1) §3.7's claim that "every cascade" can push a trip into `DEGRADED` — engagement completion, incident resolve, incident close and Cascade D never touch readiness; rewritten to name the seven real degraders; (2) §3.7's four-condition degradation list, which missed `report_incident` and the unconditional triage degrade; (3) §3.9's "the only place they are gated against each other" — four sites read both dimensions in one gate; re-scoped to "the last of the four gates"; (4) §3.4's claim that `insurance_policy_id` may be "attached later" — `routes_trips.py:125` is its only writer and there is no trip-revision endpoint, so a trip created without a policy can never clear the submission insurance gate. Five other universals survived verification, including the two-site forward-only-rule exception.
Three direct contradictions adjudicated from source: the leg is re-derived once per cancelled liaison engagement but its `version` advances exactly once per request (`store.touch` dedupes on `id(row)`); §2.11 band (b) listed `ERR_NO_ELIGIBLE_VENDOR` before `ERR_INCIDENT_TRACK_INCOMPATIBLE` while triage checks `track_permitted` first (list reordered, verified not to disturb `engage_vendor`'s capacity-before-eligibility order); and the four assignment-create gates were narrated in a non-evaluation order, now pinned as liveness → leg version → cert → rest buffer → assessment.
Deferred item (a) — the `payload.py` nullable-string convention — was **decided and stated once** at the end of §2.11 item 3: uniform for the string class (all nine optional string sites are `nullable=True` and an explicit null reads as `None`), with the three genuine exceptions named (`enum_field`, `country_field`, `int_field`/`score_field` all reject an explicit null). No per-site pin was pruned, because each also records a *storage* fact the general rule cannot cover and those facts genuinely diverge across endpoints.
Deferred item (b) — §3.9's four-hour floor — **confirmed correct** against `calc.py:324-326` and `routes_ops.py:220-226`; no change.
Seam checks: all three §2.10 ledgers had under-specified compensating actions (each named only one reverser) and were widened from impl — money also unwound by close, staff-hours also by release and the EXTRACTION stand-down, vendor-hours also by completion. All five cascades were re-verified where the firing route and victim rows sit in different partitions. A 10-gram shingle scan found 25 repeated spans, all parallel structure across different endpoints or the deliberate reciprocal cross-reference; nothing removed.
Left unpinned: `triage_incident`'s `ERR_TRIP_LEG_NOT_FOUND` sits after a band-(b) check, violating existence-before-business ordering, but is unreachable (`report_incident` already proved the leg exists and no leg-delete endpoint is declared) — documenting an unobservable ordering would have meant a false ladder exception.

### Cross-pass conflict handling

Exactly one contradiction crossed a partition boundary: pass 2 wrote that the duress re-anchor is "the one place the forward-only rule does not have the final say," which pass 3 then proved false by finding the shelter-in-place triage branch. Pass 3 corrected it narrowly (both paragraphs now say "only two places" and name each other) and reported the correction rather than silently overwriting; pass 4 re-verified the pair and confirmed exactly two such sites exist. No other cross-pass contradiction was found.

### Orchestrator final verification

```
81348a13ab5e891d40d6800b6a01eb0a  workspace/PRD.md
81348a13ab5e891d40d6800b6a01eb0a  workspace/PRD_FINALIZED.md
397fe180a91bf4f264b3bdec958fdcf7  workspace/PRD_COMPLETED.md   451 lines / 135,008 chars
```

- `PRD_COMPLETED.md` is **not** byte-identical to its source (+28,274 chars, +26.5% over `PRD_FINALIZED.md`'s 106,734), so the scan genuinely ran — 83 edits across the four passes.
- Heading count identical to `PRD_FINALIZED.md`; §4 still 49 rows; §5 still 50 rows matching `implementation/errors.py`; file ends on the last error row (`ERR_SECURITY_BUDGET_EXCEEDED | 402`), a real section boundary.
- `find` over `implementation/`, `test_suite/` and `test_helpers/` for `*.py` newer than the sweep (05:27) returns nothing: Steps 8 and 9 touched documentation only, so Step 7's verified 8×85/85 clean sweep still holds for the shipped artifacts.
- Grep for "harder than expert" / "scaffold" in `PRD_COMPLETED.md`: 0 hits.

**Pipeline complete.**
