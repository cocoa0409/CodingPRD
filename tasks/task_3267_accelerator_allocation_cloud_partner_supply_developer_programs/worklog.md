# Worklog — task_3267_accelerator_allocation_cloud_partner_supply_developer_programs

## Step 1: Create task directory — 2026-09-30T15:51:00.000Z

Task directory `./tasks/task_3267_accelerator_allocation_cloud_partner_supply_developer_programs` was pre-allocated by the caller and already contained `workspace/`. No index computation performed; no other `task_*` directory created.

## Step 2: Generate scaffold artifacts — 2026-09-30T16:38:00.000Z

All three artifacts are written and verified. Scaffold generation complete.

**Files written** (all in `/home/ubuntu/github/CodingPRD/tasks/task_3267_accelerator_allocation_cloud_partner_supply_developer_programs/`):

| File | Lines | Top-level key(s) |
|---|---|---|
| `SCAFFOLD.yaml` | 3,671 | scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, concurrency_guards, calculations, validations, errors, roles, endpoints |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 3,787 | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4,263 | `scaffold_corner_design` only |

**Lint verdict (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    113
  §1.1 entities declared:     21
  §1.8 instances scanned:     24
  §1.9 instances scanned:     40
  Calls scanned (§1.8+§1.9):  944

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Entity model — 21 entities, graph topology, split into supplier-global collections (PartnerAccount, AcceleratorProduct, SupplyNode, SolutionBlueprint, ExportLicenseGrant) and FK-linked dependents (AllocationHold, ValidationEvidence, EnterpriseSubscription, HardwareDeployment, SoftwareStackLicense, DeveloperProgramMembership, PreviewSoftwareGrant, ConfidentialityAcknowledgement, DemandForecast, EvaluationLoan, ProofOfConceptMilestone, LifecycleCommitment, FrictionPenalty, AllocationEpoch, AuditTrailEntry, SupplyContract).** Two deliberate traps: `AllocationHold` is rooted at `PartnerAccount` so its demand-conversion is guarded by `expected_partner_version`, while a second, non-OCC `expected_allocated_units` guard compares a raw counter on `AcceleratorProduct`; and `SoftwareStackLicense` is a child of the SKU even though the prose reads as if it belongs to the partner.

**Counts:** 14 state machines / 57 transitions (three genuinely cyclic — PartnerAccount rejection→reapply, SupplyNode friction→open, HardwareDeployment terminate→reinstate; one parallel pair, subscription status × deployment activation_state); 22 calculations; 32 validations in a 32-tier priority order; 113 endpoints; 36 errors; 7 roles; 3 OCC concurrency rules + 1 non-OCC guard.

**§1.8 coverage:** 9/9 rules, 24 instances (≥2 each) — dual_variant_calc 2, combinatorial_formula 3 (three distinct modes), non_linear_state_machine 3, transitive_cascade 3 (two depth-3 chains from different triggers, one depth-2), priority_pair_validation_conflict 3 (constraint/fiscal, safety/referential, temporal/fiscal), boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 3 (half-open months, closed days + buffer, open months + grace tail), compensating_invariant 2. All formula-derived asserts are pre-computed literals (e.g. 900000 vs 1440000 cents; 23187 vs 23188; 800.0 vs 950.0; 117 vs 200 credit units; hotness 7.0 = HOT).

**§1.9 coverage:** 40 active instances across all nine taxonomy sections (entities 6, state_machines 6, calculations 4, validations 7, endpoints 3, errors 5, rbac 2, cross-cutting layers 6, consistency model 1) plus 19 `excluded_because:` stubs citing real §1.8 instance names.

Two audit notes worth passing on: the difficulty and corner design files went through a JSON round-trip to break YAML anchor sharing (PyYAML aliasing let one instance's `captures:` leak into a sibling, which silently changed a fixture), and `concurrency_rules.write_endpoint` values were re-prefixed with the `api_prefix` so they resolve against §1.5.

Orchestrator verification on disk: `SCAFFOLD.yaml` 3671 lines / `SCAFFOLD_DIFFICULTY_DESIGN.yaml` 3787 / `SCAFFOLD_CORNER_DESIGN.yaml` 4263; 113 `- method:` endpoint entries present; difficulty file carries exactly one top-level key `scaffold_difficulty_design`, corner file exactly one `scaffold_corner_design`.

## Step 3: Copy shared files — 2026-09-30T16:39:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `./workspace/INSTRUCTION.md` (1424 bytes). Build contract: `start.sh` reads `$PORT` (default 10000), binds `0.0.0.0`, runs foreground; evaluator runs `bash start.sh` from `./implementation/`.

## Step 4: Generate PRD document — 2026-09-30T16:52:00.000Z

The PRD is complete and all three hard contracts verified mechanically. Final summary:

## Output

**`/home/ubuntu/github/CodingPRD/tasks/task_3267_accelerator_allocation_cloud_partner_supply_developer_programs/workspace/PRD.md`** — 484 lines, ~13,170 words.

## Section list

- **§1 Introduction** (3 paragraphs: scarcity, regulation, auditability; logical clock)
- **§2 Global Specifications** — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim fixed block) · 2.3 Pagination · 2.4 Partner Standing, Qualification and Program Eligibility · 2.5 Export Control, Destination Bands and Performance Density · 2.6 Supply Pool Temperature, Friction and Band Compliance · 2.7 Allocation Prioritisation and Displacement Ordering · 2.8 Ledger Conservation: Capacity and Entitlement · 2.9 Subscription Billing, Settlement and Seat Bounds · 2.10 Common Resource Properties and Nested Path Resolution · 2.11 Precision, Rounding and the Logical Clock · 2.12 Optimistic Concurrency, Allocation Guards and Request Evaluation Order
- **§3 Business Logic** — 3.1 The Accelerator Catalog and SKU Lifecycle · 3.2 Partner Onboarding, Qualification and Standing · 3.3 Supply Pools: Temperature, Friction and Stage Lifecycle · 3.4 Allocation Holds, Value Scoring and Preemptive Displacement · 3.5 Demand Forecasting, Horizon Bands and Forfeit Exposure · 3.6 Software Stacks, Developer Programs and Confidential Preview Access · 3.7 Hardware Deployments, Export Gating, Subscriptions and the Entitlement Ledger · 3.8 Evaluation Hardware Loans and Proof-of-Concept Milestones · 3.9 Supply Contracts and Long-Term Availability Commitments · 3.10 Epochs, Checkpoint Sweeps and the Audit Trail · 3.11 Licence Hold Groups and Grouped Deployment Dispatch
- **§4 Endpoint Definitions** (114 rows, 4 columns) · **§5 Error Code Catalogue** (36 rows, 2 columns)

## Scaffold elements carried over

| Element | Count |
|---|---|
| Entities | 21 (137 distinct field names) |
| State machines | 14 (57 transitions) |
| Calculations | 22 |
| Validations | 32 (priority ordering expressed as an explicit 29-step precedence in §2.12, plus rule-specific ordering in §3) |
| Endpoints | 113 (80 distinct input identifiers) |
| Errors | 36 |
| Roles | 7 (all `identity:` fields translated; `PartnerOps` entity-backed, six opaque) |
| Concurrency rules / guards | 3 OCC + 1 `expected_allocated_units` guard |

## Deliberate non-coverage

- **`LicenseHoldGroup` / `DeploymentGroup` / `LicenseHold` are not scaffold entities** — they appear only as endpoint paths, RBAC entries and `validations[].applies_to` targets. Rather than invent their fields, §3.11 covers them by describing the gates they inherit and naming the literal inputs the scaffold does declare (`members`, `expected_allocated_units`, `expected_partner_version`), so the endpoint table and RBAC remain faithful without fabricated schema.
- **7 duplicate `(method, path)` endpoint pairs** in the scaffold (e.g. `GET /accelerators/allocations` appears twice) were deduplicated to one row each in §4.
- **Two endpoint inputs could not be honoured as literal field names**: `POST /epochs/{epochId}/close` and `POST /blueprints/{blueprintId}/retire` declare no `path_params`, but their paths require those segments. I used the scaffold's own singular-segment spelling (`{blueprintId}`/`{partnerId}` elsewhere) rather than the malformed plural form, which is not a valid identifier.

## Hard-contract reports (transcript only — not in PRD.md)

```
Field coverage check:
- entities[].fields: 137 required, 137 present, 0 missing
- endpoints[].request_body: 80 required, 80 present, 0 missing
- endpoints[].query_params: 0 required, 0 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 32 checked, 32 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- concurrency_guards: 1 checked, 1 expressed, 0 missing
- state_machines[].transitions: 57 checked, 57 fully expressed, 0 missing
- calculations[]: 22 checked, 22 fully expressed, 0 missing
- validations[] conditions: 32 checked, 32 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 32 checked, 32 expressed, 0 missing
- entities[].fields[] structured content: 137 checked, 137 reconstructible from prose, 0 missing
- sibling-branch symmetry: 14 groups checked, 14 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 582
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Every one of the 36 error IDs appears both in the §5 catalogue and inline with its trigger condition in §2/§3; §2.2 matches `section-2.2-response-structure.md` byte-for-byte (only the trailing section separator differs). No pseudocode, comparison operators, or fuzzy hedging remained after a final token scan; the file ends at §5 with no audit footer.

## Step 5: Generate unit test suite — 2026-09-30T18:55:00.000Z

Everything verifies. Final state is complete and self-consistent.

## Summary

Generated complete test infrastructure for `task_3267_accelerator_allocation_cloud_partner_supply_developer_programs`, driven **only** by the two design indices.

### Files written

**`test_helpers/`** (1,962 lines)
| File | Lines |
|---|---|
| `__init__.py` | 29 |
| `types.py` | 377 |
| `api_client.py` | 413 |
| `api_errors.py` | 85 |
| `assertions.py` | 126 |
| `constants.py` | 126 |
| `factories.py` | 220 |
| `fixtures.py` | 553 |
| `test_users.py` | 33 |

**`test_suite/`** (3,574 lines) — `conftest.py` (44) plus 19 numbered `test_*.py` files (101–313 lines each).

### Totals
- **108 tests**, all collected by pytest, all `py_compile`-clean, all importable against the framework.
- **Queue A (Difficulty)**: 24/24 instances, **52 tests**, minimum 2 per instance (every instance ≥2, as required; all at exactly 2 except none below).
- **Queue B (Corner)**: 40/40 non-stub instances, **56 tests**, minimum 1 per instance; the 19 `excluded_because:` stubs were not translated (cross-references resolve).

Per-rule/per-section tallies are in the table above.

### Verification performed
- **Design tags**: 108/108 tests carry exactly one `Design:` line, and it is the final docstring line. No untagged, dual-tagged, or dangling tags (all resolve to real instances).
- **PRD citations**: all 155 quote fragments pass a literal ≥8-word substring grep of `PRD.md` (0 failures). Removed all endpoint-table citations (they do not survive verbatim) and re-anchored those tests to rule-bearing prose.
- **No scaffold leakage**: no occurrences of "scaffold"/table/§1.x references in generated code.
- **No skip/xfail** anywhere.
- **Numerics independently re-derived** (round-half-even fee schedules, `1.95`, `23187`, `[7.0→HOT]`, `117/200` credit, the third-Saturday bands/deadlines, the 95-day eligibility gap and its 550.0 confirm-vs-saturating-estimate separation, `2555`/`1825` floors) before asserting them.

### Instances SKIPPED under the PRD-first filter
**None.** Every non-stub instance in both queues passed both conditions (verbatim PRD coverage AND unique derivability). The only untranslated entries are the 19 `excluded_because:` stubs, which the skill forbids translating regardless.

### Scaffold/path mismatches adjudicated
1. **`fixtures.py` and `PRD.md` location.** The skill's tree shows inputs at the working-dir root, but the actual layout is `workspace/PRD.md`. Generated code lives at the task root per the prompt.
2. **Two §1.9/§1.8 numeric constants are not PRD-derived.** `2.0` (the friction-penalty base score) and `SUPPLY_CEILING_HEADROOM_UNITS` appear only in the scaffold, not the PRD. I did not hard-code either — the friction-score test asserts sign, and the ceiling test uses a forecast of 1000 units so headroom is never the binding term (the 1001-vs-1000 boundary follows from the forecast alone).
3. **Deliberate ordering trap in license-hold groups.** PRD §3.11 names `ERR_LICENCE_GROUP_DUPLICATE_MEMBER` while §4/§5 use `ERR_LICENSE_GROUP_DUPLICATE_MEMBER`, and no design-index instance exercises it — so it is correctly never asserted.
4. **Softened two assertions for unique-derivability**: the WARM-vs-COOL deviation expects `FRICTION_HOLD` with a positive score rather than the scaffold's exact `2.0` (the base score is not PRD-stated); the preemption test asserts the displaced score ordering via the observable output states rather than the raw `275.0` sub-score (the ranking formula is PRD-stated, but the tie-break sub-claim is not load-bearing).
5. **`PartnerOps` is the sole `entity_backed` role**; every ownership-gated call threads the live entity id through `make_partner_ops_headers(partner_id)`. The tests exercise role denial only where the role is formally exclusive without a self-exclusion ambiguity (e.g. `PartnerOps` calling `/qualify`), since PRD §3.2 also says a `PartnerOps` caller is "treated as operating on its own account" for its own sub-collections.

Orchestrator verification on disk: `test_helpers/` 1962 lines across the 9 declared modules; `test_suite/` 3574 lines across `conftest.py` + 19 `test_*.py`; 108 `def test_` functions; 108 `Design:` tag lines (52 `Difficulty/`, 56 `Corner/`); the only `skip`/`xfail` grep hit is docstring prose at `test_suite/test_11_listing_and_not_found.py:59`, not a pytest marker.

## Step 6: Generate implementation — 2026-09-30T18:01:30.000Z

The implementation is complete and verified.

## What was built

A complete Python + Flask implementation in `/home/ubuntu/github/CodingPRD/tasks/task_3267_accelerator_allocation_cloud_partner_supply_developer_programs/workspace/implementation/` — 25 files, 4,871 lines, all written as small focused modules and each verified on disk before the next was started.

**Files (line counts):** `calc.py` 363, `routes_holds.py` 421, `routes_memberships.py` 340, `routes_partners.py` 309, `services.py` 286, `routes_deployments.py` 270, `routes_groups.py` 244, `routes_epochs.py` 243, `routes_loans.py` 228, `routes_subscriptions.py` 218, `routes_forecast.py` 201, `routes_lifecycle.py` 201, `util.py` 186, `rules.py` 171, `constants.py` 164, `routes_supply.py` 151, `error.py` 145, `routes_catalog.py` 135, `auth.py` 92, `store.py` 110, `routes_blueprints.py` 128, `routes_stacks.py` 128, `app.py` 77, `envelope.py` 51, `start.sh` 9, `requirements.txt` 1.

**Endpoints wired: 119 registered accelerator routes, covering all 106 declared (method, path) pairs** with zero gaps — verified by diffing the live Flask URL map against `SCAFFOLD.yaml`'s endpoint table programmatically. The extra count is duplicate paths declared twice in the scaffold. Thirteen scaffold-implied endpoints that `roles:` references but never declares are also implemented (`/partners/{id}/terminate|reapply`, `/supply-nodes/{id}/drain|bind`, `/blueprints/{id}/retire`, `/epochs/{id}/close`, `/deployment-groups*`, `/license-hold-groups*`, plus `GET` list surfaces).

**State and clock (one-line summary):** all state lives in a `Store` of plain dicts keyed by UUID in `store.py`, which starts empty on every boot; the only row created at start-up is `AllocationEpoch` index 0 in `OPEN` status — required because PRD §2.12 item 11 makes an open epoch a precondition of every allocation-creating call, and every other entity in the system hangs off the store the tests build through the API. The logical clock initialises to exactly `2026-09-01T00:00:00Z` from the `_clock/set_current_utc` default.

**Verification performed:** booted via both `python3 app.py` and `bash start.sh` on six scratch ports (all killed by exact PID, no broad kill patterns), then drove ~120 live requests across five probe scripts. Confirmed numerically against the PRD's worked examples: the third-Saturday band rule (`2026-09-01`→MEDIUM/`2026-10-16`, `2026-09-18`→SHORT/`2026-09-20`), unit-based rate 1.95 at 250 units vs 1.75 time-based, density 1350→LOW declared vs 1400→HIGH computed, 25-seat BUSINESS settling 900000→1440000, credit 200/117 at the 40-seat boundary, late fee capping at 15.0 for both 30 and 31 days, and 10%-ceiling ring-fence rounding. Also exercised: preemption displacement (lowest-score prefix → RECLAIMED with ledger debit −50 and pool held untouched), the suspend→terminate→entitlement-release cascade, and all four SoD/export ordering claims on deployment termination.

**Three real bugs found and fixed during verification:** the separation-of-duties gate was comparing against the audit chain instead of `activation_actor_user_id` (so handover could never satisfy it); internal bookkeeping fields were leaking onto the wire (now filtered by leading underscore in `serialize`); and list ordering fell back to random UUIDs as a tie-break when the logical clock doesn't advance (now uses a private mint sequence, so lists are deterministic in creation order).

**One judgement call worth flagging:** the `ERR_SUPPLY_CEILING_EXCEEDED` rule reads "partner.committed_volume_units plus the requested quantity must not exceed partner.committed_volume_units plus entitlement_units_held plus headroom" — the committed-volume term appears on both sides and cancels, so with headroom 0 a freshly-registered partner could never allocate anything at all. I resolved this by treating the "configured supply-ceiling headroom" as a real constant and set it to 10000 units in `constants.py`, making the binding constraint `entitlement_units_held + 10000`. If the reference implementation instead seeds committed volume at partner registration, that constant is the one line to change.

Orchestrator verification on disk: 26 files present (25 sources + `requirements.txt`), 4,871 total lines, all under ~450 lines per file. `start.sh` is executable, guards the `pip install` behind an `import flask` check (deliberate: 8 concurrent rounds would otherwise contend), and `exec python3 app.py`. Smoke boot on scratch port 48231 returned `{"status":"ok"}` with all 14 `routes_*` routers registered, and `POST /accelerators/_clock/set_current_utc` round-tripped to `2026-09-01T00:00:00.000Z`. Server PID killed by exact PID; no broad kill patterns used.

## Step 7: Test and fix iteration loop — 2026-09-30T21:12:00.000Z

Clean 8-round sweep: 108/108 in every round, zero errors, zero skips.

## Summary

**Iterations run:** 6 full diagnostic+fix passes (initial sweep + 5 targeted rounds), then one clean 8-round parallel stability sweep (108/108 in all 8 rounds, 0 errors/skips).

**Tests deleted:** None. Every assertion that survived tracing traced to verbatim PRD prose.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` — `create_partner` now registers as `PartnerOps` (PRD §4 declares `POST /accelerators/partners` PartnerOps-only; the fixture sent `PlatformAdmin`, cascading 403s into ~102 setup failures).
- `fixtures.py` — `create_deployment` now sends the declared `partner_id` input field (the activation qualification gate and the suspension/termination cascades all read it).
- `fixtures.py` — `create_validated_partner` mints a certified blueprint when none is passed (filing evidence requires `blueprint_id`), and leaves the partner in `APPLIED` when `qualified=False` so callers can drive their own rejection rounds.
- `fixtures.py` — `create_supply_contract` now sends the `partner_id` holder (PRD §3.9).
- `fixtures.py` / `test_users.py` — added a second `SupportAccountManager` identity; the separation-of-duties gate (PRD §3.7) refuses a terminator matching the activator, so handover must use a different operator id.

**Fixes applied to `test_suite/`:** Added `partner_id` to all `create_deployment` call sites; added missing `get_subscription`/`get_deployment` imports (test_12); corrected test_01's fee assertions to PRD §2.9 verbatim (`annual_fee_cents` = per-seat fee, `billed_fee_cents` = 25×36000); corrected test_19's `allocated_units` expectation to `150` (PRD §3.7: `min(250 released, 400 allocated)` leaves 150, not 0 — the design seed's `alloc_final == 0` contradicted the PRD and its sibling test); made test_09 drop the reclaim before terminating so depth-1 reap is exercised.

**Fixes applied to `implementation/`:**
- `routes_deployments.py` — added `partner_id` as the operating-partner body reference; reordered the export gate (priority 6) above the partner FK; made any bound subscription count as "covering" so a RECLAIMED row still permits termination (depth-1 moves only ACTIVE/SUSPENDED).
- `routes_holds.py` — fixed `licence_group` shape, band-vs-ceiling hard-constraint rule (priority 9 fires when a tier-over-ceiling hold cannot be supplied from unheld capacity), reversal of the ranking for displacement (lowest score first), preempting holds land COMMITTED, bulk members default to one unit, and the missing `ERR_HOLD_TIER_EXCEEDS_BAND` import.
- `routes_subscriptions.py` — accept `{license_id: ...}` licence-group members.
- `routes_lifecycle.py` — moved the 365-day horizon gate from creation to grant, ordered above the units rule (PRD §3.9); corrected half-open contract-window collision to allow adjacency.
- `routes_memberships.py` — corrected NDA open-month window with one-month grace tail.
- `routes_epochs.py` — epoch sweep now flags standing holds that out-rank a re-derived ceiling and moves the pool into `FRICTION_HOLD`.
- `routes_supply.py` — allow FRICTION_HOLD → OPEN.
- `routes_partners.py` — the suspension cascade terminates the deployment but no longer reclaims the subscription (PRD §3.2 preserves the bind).
- `routes_catalog.py` — `lifecycle_min_remaining_days` defaults to 0.
- `calc.py` / `constants.py` — FR/DE/SG/CA classify `TIER_2_LICENSE_REQUIRED`; friction penalty score = base × 2^(tiers over ceiling); `SUPPLY_CEILING_HEADROOM_UNITS = 1000`; `ENTITLEMENT_CEILING_UNITS = 100000` (both from the design seeds' stated constants).

No skip/xfail markers, no weakened assertions, no seeded data in the implementation.

Orchestrator verification on disk: all 8 `results.{1..8}.json` present, each reporting `passed=108 total=108 errors=0 skipped=0` (mtimes 21:10). No `.py` file under `workspace/implementation/`, `test_helpers/` or `test_suite/` is newer than `results.1.json` (latest source write 21:06:45, `test_suite/test_19_consistency_saga.py`) — so the clean sweep is not invalidated by post-sweep writes.

## Step 8: Finalize PRD — 2026-09-30T21:37:00.000Z

I've produced `PRD_FINALIZED.md`. Final verification: both files are 484 lines (0.0% line-count delta), the section structure (31 headings, 4 code fences, 154 table rows) is unchanged, and every edit is an in-place sentence modification within an existing paragraph.

## Summary

**PRD.md vs PRD_FINALIZED.md:** 484 lines each — **0.00% delta** (15 paragraphs edited in place; 30 changed diff lines).

Path: `/home/ubuntu/github/CodingPRD/tasks/task_3267_accelerator_allocation_cloud_partner_supply_developer_programs/workspace/PRD_FINALIZED.md`

### Changes (one bullet per edit)

- §2.5 — revise — destinations DE/FR/SG/CA classify `TIER_2_LICENSE_REQUIRED` by country (US `TIER_1_CLEARED`, CN `TIER_3_PROHIBITED`), not by density — `implementation/calc.py:200-213`, `implementation/constants.py:75-79`
- §2.7 — insert — an incoming hold that displaces a prefix lands directly in `COMMITTED` — `implementation/routes_holds.py:253,264`
- §2.12 (item 9) — insert — the band rule is a hard constraint for a single hold only when the pool can't cover it from unheld capacity; the licence hold group treats every overshoot as hard — `implementation/routes_holds.py:145-150`, `implementation/routes_groups.py:69-70`
- §3.1 — insert — a SKU opens with `lifecycle_min_remaining_days` = 0 — `implementation/routes_catalog.py:35`
- §3.3 — revise — penalty `score` = base 1.0 × 2^(tiers over ceiling), so a non-violation scores 1.0 — `implementation/calc.py:178-184`, `constants.py:70`
- §3.4 (hold creation) — insert — a bulk member with no explicit quantity reserves 1 unit; a bare value is read as its quantity — `implementation/routes_holds.py:83-89`
- §3.4 (supply ceiling) — insert — headroom = 1000 units — `implementation/routes_holds.py:167`, `constants.py:52`
- §3.4 (band-vs-hard) — revise — hard constraint applies iff the pool can't cover the hold from unheld capacity — `implementation/routes_holds.py:145-150`
- §3.7 (deployment create) — insert — `HardwareDeployment` carries `partner_id` (the operating partner), resolved last, and the export gate runs before it (export error precedes `ERR_PARTNER_NOT_FOUND`) — `implementation/routes_deployments.py:78-95`
- §3.7 (subscriptions) — revise — the covering requirement is any bound subscription row (RECLAIMED/EXPIRED included); only ACTIVE/SUSPENDED move to RECLAIMED at depth 1 — `implementation/routes_deployments.py:213-223`
- §3.7 (activation) — insert — entitlement ceiling = 100000 units — `implementation/routes_subscriptions.py:144`, `constants.py:53`
- §3.7 (termination asymmetry) — insert — the suspension cascade terminates the deployment and releases entitlement but does not reclaim the subscription; the bind is preserved — `implementation/routes_partners.py:260-285`
- §3.9 (contracts) — revise — a contract starting in the month after the existing end month is legal, not `ERR_CONTRACT_WINDOW_OVERLAP` — `implementation/routes_lifecycle.py:62-70`
- §3.9 (commitments) — insert — the horizon floor and unit-availability bound are evaluated at grant, not at request — `implementation/routes_lifecycle.py:112-115,158-165`
- §3.10 (sweeps) — insert — the passing sweep re-flags standing REQUESTED/COMMITTED holds now over a re-derived ceiling into `FRICTION_HOLD` with a fresh `BAND_VIOLATION` penalty, without re-flagging — `implementation/routes_epochs.py:78-121`

### Per-edit pre-edit search log

Every edit's subject was searched across *all* impl call-sites, not just the Step 7 site:

1. **Export classification** — subject: how a destination resolves to a class. Enumerated: `calc.export_control_classification`, `rules.classification_for`/`check_export_gate`/`active_export_grant`, callers in routes_deployments (`_create`, `_activate`, `_terminate`), routes_groups. Confirmed every path routes on the code, so the deploy gate is reachable; rephrased to name the country mapping and dropped the old "US" as a grant-unlockable claim. (c) widened to a general mapping.
2. **Preempting hold commit** — subject: state of a displacing hold. Enumerated: `_reserve` (commits_on_create), `_build_hold`, preempt candidate path, `recompute_node` held-units; the licence-group preempt (`routes_groups._preempt_group`) sets no state, so scoped the claim to the single-hold path. (c) scoped to "an incoming hold that displaces".
3. **Priority-9 gate** — subject: which allocation paths treat overshoot as hard. Enumerated: `_build_hold` (requires `tier_over_ceiling AND insufficient_capacity`), `_reserve` friction path, `routes_groups._create_license_group` (unconditional). (c) distinguished single-hold from group.
4. **lifecycle_min_remaining_days** — subject: the field's initial value. Enumerated: `routes_catalog._create/_update/_advance_lifecycle/_promote_evaluation_pool/_rerun_lifecycle_floor`, `calc.lifecycle_commitment_floor`; initializer is the only 0. (c) none.
5. **Friction score** — subject: the scoring formula. Enumerated: `calc.friction_penalty_score` (all tier pairs), `routes_holds._reserve` (hold over ceiling, index ≥1), `routes_epochs._apply_band_violations` (same), `routes_epochs._sweep_loans` (LATE_CANCEL via `SCORE_BASE`). Confirmed base is always 1.0. (c) none.
6. **Bulk member default** — subject: member quantity. Enumerated: `routes_holds._bulk_create` (dict-without-quantity → 1; bare → int). (c) none.
7. **Headroom** — subject: the configured headroom. Enumerated: `routes_holds._build_hold` ceiling expression, `constants.SUPPLY_CEILING_HEADROOM_UNITS` (only user). (c) none.
8. **Band hard-vs-friction** — see 3. (c) same distinction added.
9. **Deployment partner_id** — subject: the body field and its resolution order. Enumerated: `_operating_partner`, `_deployment_partner`, `_create`, `_activate`, `_terminate`, `_handover`, suspend cascade, `bound_stack_ids_for`; confirmed all read `deployment["partner_id"]`. Re-checked relative precedence: `_create` resolves the product by `require` before the partner, and the export gate before the partner — softened to "resolved last" + "export gate precedes it". (c) narrowed an initial over-broad "after the path resources" claim.
10. **Covering subscription** — subject: the covering predicate. Enumerated: `routes_deployments._terminate` (`if not bound_subs`), `routes_subscriptions._create/_activate` (TERMINATED check), `released_entitlement_for`, `services.deployment_service_ready`; confirmed readiness/ledger consider only ACTIVE while the covering check counts any row. (c) widened to include RECLAIMED/EXPIRED rows.
11. **Entitlement ceiling** — subject: the ceiling value. Enumerated: `routes_subscriptions._activate`, `constants.ENTITLEMENT_CEILING_UNITS` (only user). (c) none.
12. **Suspension cascade** — subject: whether it reclaims the subscription. Enumerated: `routes_partners._suspend`/`_terminate_deployment`, vs `routes_subscriptions._reclaim`; confirmed the shared helper omits the reclaim. (c) none.
13. **Contract adjacency** — subject: `ERR_CONTRACT_WINDOW_OVERLAP` trigger. Enumerated: `routes_lifecycle._create_contract` collision loop. (c) none.
14. **Commitment gates** — subject: where the horizon/units gates live. Enumerated: `_create_commitment` (only `parse_utc`), `_grant` (grace then units then version). (c) none.
15. **Epoch re-flag** — subject: the sweep's hold/ceiling re-derivation. Enumerated: `_sweep_nodes`, `_apply_band_violations`, `recompute_node` (held_units excludes `_band_violation`), `_sweep_penalties`. Noted the extra check fires inside `_sweep_nodes` after release, so worded it to avoid contradicting the existing release sentence. (c) none.

**Reverted for HARD SCOPE:** I initially pinned the membership grace period to 30 days (`routes_memberships.py:117`, `constants.py:97`), but that value is not a `<step_7_diff>` item, so I reverted it — §3.6 keeps PRD's original unspecified "membership grace period". (Worth noting for a future pass: PRD's §3.6 is silent on this value while `test_helpers/constants.py:84` declares 90; only the impl's 30 ends up mattering behaviorally.)

No skips/xfails/seeded data were used; no files other than `PRD_FINALIZED.md` were written.

Orchestrator verification on disk: `PRD.md` 484 lines, `PRD_FINALIZED.md` 484 lines; `diff` reports exactly 30 changed lines (15 paragraphs, in-place). Only `PRD_FINALIZED.md` was newly created in `workspace/` — no implementation or test file was modified by this step.

## Step 9: Complete PRD — 2026-10-01T04:06:00.000Z

PRD_COMPLETED.md is written. Summary:

**Source vs output**
- Source: `/home/ubuntu/github/CodingPRD/tasks/task_3267_accelerator_allocation_cloud_partner_supply_developer_programs/workspace/PRD_FINALIZED.md` (existed; copied per step 0) — 484 lines, 96,777 chars.
- Output: `.../workspace/PRD_COMPLETED.md` — 488 lines, 104,605 chars (+4 lines, +7,828 chars ≈ +8.1%).
- Structure preserved: no new sections, no new error rows, heading set identical, code fences unchanged.

**Counts:** 22 ambiguity-pins, 14 mismatch-revisions (36 changed statements, 36 diff hunks).

**Changes** (`section — insert|revise — ambiguity|mismatch — what changed — impl ref`)

- §2.2 — insert — ambiguity — `api_request_timestamp` is a real server stamp, not the logical clock — `implementation/envelope.py:18-22`
- §2.3 — insert — ambiguity — `offset<0` / non-integer `limit`/`offset` are malformed input — `implementation/util.py:150-169`
- §2.3 — insert — ambiguity — list ordering breaks `created_at` ties by server mint sequence — `implementation/util.py:181-189`
- §2.4 — insert — ambiguity — zero-delivery partner resolves on-time ratio to 1.0 — `implementation/calc.py:333-338`
- §2.5 — insert — ambiguity — `granted_units` is never compared to any quantity — `implementation/rules.py:136-145`
- §2.6 — insert — ambiguity — a fresh pool keeps the declared tier until its first mutation — `implementation/routes_supply.py:34`, `implementation/services.py:102-111`
- §2.7 — revise — mismatch — displacement candidate set is restricted to the same pool (PRD said whole-SKU); the rank surface stays SKU-wide — `implementation/routes_holds.py:297-310`, `routes_supply.py:62-74`
- §2.10 — insert — ambiguity — opaque `id` is distinct from `sku_code`/`node_code`/`blueprint_code`/`license_code` — `implementation/util.py:22-24`
- §2.10 — insert — ambiguity — id resolution also accepts the natural key as tolerance — `implementation/rules.py:27-47`
- §2.12 item 29 — revise — mismatch — shape rule also rejects booleans-as-ints, empty required strings, non-integer version tokens as `ERR_INVALID_REQUEST` — `implementation/util.py:96-124`, `rules.py:87-112`
- §3.2 — insert — ambiguity — `origin_epoch_index` defaults to 0 — `implementation/routes_partners.py:41`
- §3.2 — revise — mismatch — evidence filing gates on `APPLIED`+`ACTIVE`, reports `ERR_BLUEPRINT_NOT_FOUND` for an unknown blueprint, and never consults `blueprint_status` (removes the `RETIRED` → `ERR_BLUEPRINT_NOT_CERTIFIED` sentence) — `implementation/routes_partners.py:85-108`
- §3.2 — revise — mismatch — acceptance also enforces `required_validation_minutes`; evidence rejection bumps `era_index` on last-accepted loss — `implementation/routes_blueprints.py:79-110`
- §3.2 — insert — ambiguity — qualification audit filed under the partner's own id — `implementation/routes_partners.py:136`
- §3.3 — insert — ambiguity — stage capability is also the manual return path (`BINDING`/`FRICTION_HOLD`→`OPEN`); every other pairing, incl. same-stage, is `ERR_INVALID_STATE` — `implementation/routes_supply.py:86-110`
- §3.4 — revise — mismatch — commit bumps the partner version; `consume_reservation` debits the just-reserved quantity so net capacity movement is zero — `implementation/routes_holds.py:330-347`
- §3.4 — insert — ambiguity — `cancellation_forfeit_units` = `forfeit_rate` × quantity rounded half-even to 1dp; no forecast ⇒ 0; `as_user_id` absent ⇒ caller recorded — `implementation/routes_holds.py:350-406`
- §3.5 — revise — mismatch — `ERR_FORECAST_NOT_COMMITTED` also covers an unresolvable, wrong-partner, or wrong-SKU forecast — `implementation/routes_holds.py:152-164`
- §3.5 — insert — ambiguity — band/deadline have no separate timestamp; `acknowledged_at` is the sole anchor — `implementation/routes_forecast.py:89-96`
- §3.6 — insert — ambiguity — **membership grace period pinned to 30 days** (the flagged leftover) — `implementation/routes_memberships.py:117,141`, `implementation/constants.py:97`
- §3.6 — insert — ambiguity — request requires caller's own `ACTIVE` partner; certification is not tested here — `implementation/routes_memberships.py:35-49`
- §3.6 — insert — ambiguity — evaluate refuses non-`REQUESTED` with `ERR_INVALID_STATE`; missing accepted pack reports `ERR_QUALIFICATION_NOT_MET` — `implementation/routes_memberships.py:98-114`
- §3.6 — insert — ambiguity — renewal deadline instant counts as elapsed — `implementation/routes_memberships.py:134-136`
- §3.6 — insert — ambiguity — lapse/breach revocation cascade shares revoke handling but preserves status (no `ACTIVE`→`REVOKED` escalation) — `implementation/routes_memberships.py:165-196`
- §3.6 — revise — mismatch — lapsed renewal does not re-stamp the deadline nor re-test accepted evidence — `implementation/routes_memberships.py:138-144`
- §3.6 — revise — mismatch — ack collision is `new_start ≤ existing_start+1` month, not "start strictly before existing end − one" — `implementation/routes_memberships.py:214-221`
- §3.6 — revise — mismatch — grant gate checks the named ack reference is `BOUND` (unknown or non-`BOUND` ⇒ `ERR_NDA_NOT_BOUND`) rather than keying on the preview flag — `implementation/routes_memberships.py:258-260`
- §3.7 — insert — ambiguity — an unresolvable manifest `license_id` reports `ERR_LICENSE_GROUP_UNRESOLVED` — `implementation/routes_deployments.py:41-57`
- §3.7 — insert — ambiguity — activation records the acting id as activation actor; `bound_stack_ids` is sorted, de-duplicated, existing-only — `implementation/routes_deployments.py:150-154`, `services.py:232-250`
- §3.7 — insert — ambiguity — ring fence is created once, at first activation of a promoted SKU — `implementation/routes_deployments.py:160-164`
- §3.7 — insert — ambiguity — subscription creation provisions only `annual_fee_cents`; `billed_fee_cents`/`settled_fee_cents` stay 0 — `implementation/routes_subscriptions.py:86-89`
- §3.7 — insert — ambiguity — subscription creation does not itself test partner certification — `implementation/routes_subscriptions.py:66-69`
- §3.7 — revise — mismatch — subscription expiry fires at `clock ≥ activated_at + 365d` ("passes" pinned) — `implementation/routes_epochs.py:194-206`
- §3.7 — revise — mismatch — reinstatement stamps `settlement_epoch_index` with the currently open epoch index — `implementation/routes_subscriptions.py:162-179`
- §3.7 — insert — ambiguity — deployment group takes `group_satisfied` from the request; dispatch moves `PENDING` members to `ACTIVATED` — `implementation/routes_groups.py:195-228`
- §3.8 — insert — ambiguity — loan opens with `required_return_at` and node unset — `implementation/routes_loans.py:44-54`
- §3.8 — insert — ambiguity — overdue penalty node = loan's node else first SKU pool (skipped if none); score 1.0 — `implementation/routes_epochs.py:143-176`
- §3.9 — insert — ambiguity — commitment opens with `commitment_floor_days` 0 — `implementation/routes_lifecycle.py:116-124`
- §3.10 — insert — ambiguity — epoch 0 seeded `OPEN` at start-up with `half_life_next` COOL; successor band sums pool rates (COOL when none); close capability is separate and has no promotion — `implementation/store.py:42-50`, `routes_epochs.py:32-74`
- §3.10 — revise — mismatch — sweep band-violation re-flag removes the hold's quantity from held units, matching §3.3 — `implementation/routes_epochs.py:101-121`, `services.py:77-83`
- §3.11 — revise — mismatch — `expected_allocated_units` is optional for the group (compared only when supplied) — `implementation/routes_groups.py:86-88`
- §3.11 — revise — mismatch — duplicate-member error spelled `ERR_LICENSE_GROUP_DUPLICATE_MEMBER` — `implementation/routes_groups.py:82`
- §3.11 — revise — mismatch — group preempt consumes the ranking highest-first, not lowest — `implementation/routes_groups.py:163-170`
- §3.11 — insert — ambiguity — member quantity must be positive; one line per member; batch advances the partner once; body refs resolve up front — `implementation/routes_groups.py:44-124`
- §4 — insert — ambiguity — added `/supply-nodes/{id}/drain` and `/supply-nodes/{id}/bind` rows — `implementation/routes_supply.py:147-148`
- §4 — insert — ambiguity — added `GET /epochs` and `GET /epochs/{id}` rows — `implementation/routes_epochs.py:264-265`

**Notes / residual judgment calls**
- The §3.2 edit deliberately removes the only PRD sentence that asserted `ERR_BLUEPRINT_NOT_CERTIFIED`, because the implementation never raises it; that catalogue row is now unreachable (it is still listed in §5, which is the "complete set the API may emit" and was left untouched). Flagging it if you want the row removed too.
- §2.4 leaves the on-time-ratio tier-1 path as written (it cannot clear 0.8 under the stated formula once any deliveries exist), matching `calc.partner_priority_class`; I pinned only the zero-delivery resolution.
- I treated the tests strictly as cross-reference. Two places where implementation and tests disagree (the `test_helpers` `MEMBERSHIP_GRACE_DAYS = 90` constant, and the same-actor/covering-subscription sequencing of §2.12 item 8 vs item 19) were resolved in favor of implementation, per the instructions; the grace-period pin explicitly uses 30 as directed.

Orchestrator verification on disk: `PRD_COMPLETED.md` present, 104,605 bytes, 488 lines, 31 `#` headings (identical heading set to `PRD.md`), terminating correctly at the final §5 error-catalogue row (`ERR_EVIDENCE_INSUFFICIENT`). `worklog.md` entry for this step appended after the interrupt (the subagent had returned but the orchestrator had not yet logged it). No implementation or test file was modified by this step: `find workspace/implementation -name '*.py' -newer results.1.json` returns nothing, so the Step 7 clean 8-round sweep remains valid.