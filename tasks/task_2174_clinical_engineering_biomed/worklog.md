# Worklog — task_2174_clinical_engineering_biomed

## Step 1: Create task directory — 2026-08-29T14:39:19.000Z

Created `tasks/task_2174_clinical_engineering_biomed/` and `tasks/task_2174_clinical_engineering_biomed/workspace/`.

## Step 3: Copy shared files — 2026-08-29T14:39:40.000Z

Copied `INSTRUCTION.md` to `tasks/task_2174_clinical_engineering_biomed/workspace/INSTRUCTION.md`. (Run ahead of Step 2's completion; no dependency on the scaffold.)

## Step 2: Generate scaffold — 2026-08-29T15:27:52.000Z

Generated all three scaffold artifacts in `/home/ubuntu/github/CodingPRD/tasks/task_2174_clinical_engineering_biomed/`. No sibling task directory was read — the design came only from the scenario text and the scaffold-generator skill (plus its `references/claim-extraction-guide.md` and `scaffold_lint.py`).

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     12
  §1.8 instances scanned:     19
  §1.9 instances scanned:     75
  Calls scanned (§1.8+§1.9):  710

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5
and all §1.1 FKs have reverse-reachability in §1.5.
```

## SCAFFOLD.yaml (2007 lines)

`domain_name: clinical-engineering-biomed`, `api_prefix: /clinical-engineering`. Profile: **compliance_audit** primary × **quota_allocation** secondary, layers `optimistic_concurrency / cascading_side_effects / dual_variant_calculation / rate_threshold_triggers`, topology **flat** (prioritized by §0.3), shape **parallel**, role model **segregation_of_duties** (both 0%-represented options the skill flags). `difficulty_band: beyond_expert` is declared explicitly.

| Table | Count |
|---|---|
| §1.1 entities | 12 (Facility, Department, Vendor, DeviceModel, Device, PMTask, WorkOrder, LoanerAssignment, RecallNotice, RecallMatch, ServiceContract, SecurityFinding) |
| §1.2 state machines | 8 (Device ×2 parallel dimensions, WorkOrder, PMTask, RecallNotice, LoanerAssignment, ServiceContract, SecurityFinding) |
| §1.2.1 concurrency rules | 2 OCC (parent WorkOrder, parent Department) |
| §1.3 calculations | 13 |
| §1.4 validations | 26, strictly priority-ordered |
| §1.5 endpoints | 52 (51 business + `POST /_clock/set_current_utc`, default `2026-08-01T00:00:00Z`) |
| §1.6 errors | 41 |
| §1.7 roles | 5 (CEManager, BiomedTech, SecurityOfficer opaque; DeptSteward→Department, VendorRep→Vendor entity-backed) |

## Difficulty rule coverage (§1.8 — 19 instances, ≥2 per rule)

- **dual_variant_calc** (2): PM compliance strict 33.33 vs operational 50.00 on *Facility*; work-order estimate 82938 vs contract-adjusted final 25000 on *WorkOrder* — different entity domains.
- **combinatorial_formula** (2): mode **(b)** loaner rental rounds per-day then sums → 295037 (sum-then-round gives 295038); mode **(c)** department overhead tier keyed on *pre-debit* spend at exactly 50% → charge 9450, spend 509450.
- **non_linear_state_machine** (3): WorkOrder verify-FAIL **cycle**; Device **parallel** operational × security dimensions; RecallNotice **branching** fork-join with disjoint CLASS_I / CLASS_III side-effect sets.
- **transitive_cascade** (2): depth-4 from recall publish (matches → device DOWN → loaner CANCELLED → WO priority P3→P1); depth-3 from WO close (debit → budget ON_HOLD → facility posture HEIGHTENED).
- **priority_pair_validation_conflict** (2): `state` vs `business_fiscal`; `business_safety` vs `business_temporal`.
- **boundary_precision_check** (2): risk_score 25 MEDIUM vs 26 HIGH on `POST /devices`; empty denominator on `pm-audit` → strict 0.00 / operational 100.00.
- **cross_entity_state_dependency** (2): WorkOrder←Facility posture; LoanerAssignment←Device security_state.
- **resource_temporal_overlap** (2): **half-open** loaner intervals on Device (adjacency allowed) vs **closed** contract coverage on DeviceModel (touching endpoints collide).
- **compensating_invariant** (2): money (`Department.downtime_spend_cents` unchanged after cancel) and capacity (pool available-unit count restored on return).

## Corner coverage (§1.9 — 78 instances, 75 active + 3 `excluded_because` stubs)

entities 15 · state_machines 14 · calculations 10 · validations 13 · endpoints 5 · errors 12 · rbac 4 · cross_cutting_complexity_layers 5 · consistency_model 1.

## Verified beyond the linter

- Every one of the 52 endpoints is actually invoked by at least one recipe; every one of the 41 error codes is triggered by at least one instance.
- Zero unbound `${var}` across both design files (including in `assert:` lines); all `expected_*_version` payloads are captured `${var}`s, never literals.
- Instance names unique across both files; every stub's `difficulty_instance` resolves.
- No forbidden concurrency vocabulary anywhere.
- Every formula-derived assertion literal was computed with Decimal `ROUND_HALF_UP` before being written (82938, 295037, 509450, 123000, 60.63, 75.63, 68.13, 57.50, 53292, 33.33/50.00, 13500 s / 3.75 h / 28.00 h). One trap found and fixed during this pass: `labor_minutes/60 * rate * 1.5` evaluated left-to-right yields 43937.4999…, so §1.3 now pins multiply-first-divide-last, making the exact rational 43937.5 → 43938.

## Step 4: Generate PRD — 2026-08-29T15:36:56.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2174_clinical_engineering_biomed/workspace/PRD.md` (415 lines), built incrementally in six appends — no truncation.

**Structure:** §1 Introduction (3 paragraphs) · §2 with 11 subsections (2.1 RBAC, 2.2 verbatim envelope, 2.3 Pagination, 2.4 Identity/Versioning, 2.5 Logical Clock, 2.6 Cent Arithmetic & Rounding, 2.7 Stale-Version Guards, 2.8 Two State Dimensions, 2.9 Posture & Budget Gates, 2.10 Cascade Semantics & Conditional Restoration, 2.11 Request Rejection Order) · §3 with 9 domain subsections (campus setup, inventory & risk classification, PM calendar + audit epoch, work-order intake/repair cycles, closure & departmental debit, loaner coverage & rental billing, recall governance, security coordination, capital replacement planning) · §4 4-column endpoint table · §5 2-column error table. File ends at §5 with no audit footer.

**Verification counts (all machine-checked against SCAFFOLD.yaml):**

- Endpoints: **52 / 52** rows present in §4 (exact method+path match)
- Error codes: **41 / 41** in §5, and **41 / 41** also mentioned in §2/§3 narrative before the table
- Calculations: **13 / 13** expressed in prose (risk classification, PM compliance dual-denominator, work-order priority, service cost provisional+final, contract selection, loaner pool selection, rental cost, department downtime debit, recall match scan, replacement priority score, replacement plan allocation, turnaround, security remediation due)
- Validations: **26 / 26**, rendered as the explicit priority-ordered list in §2.11 plus scattered trigger conditions in §3
- State machines: **8 / 8** (Device×2 dimensions, WorkOrder, PMTask, RecallNotice, LoanerAssignment, ServiceContract, SecurityFinding); every declared transition pair and side-effect set expressed, including the divergent CLASS_I / CLASS_II–III fork and both cyclic loops
- Roles: **5 / 5** named with exact spelling and each `identity:` translated (2 entity-backed, 3 opaque)
- Entities: **12 / 12**; all state enum values present as exact backticked strings

**Hard contracts:**

```
Field coverage check:
- entities[].fields: 118 required, 118 present, 0 missing
- endpoints[].input/request_body/query/path params: 79 required, 79 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 26 checked, 26 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 8 machines / 45 transitions checked, all expressed, 0 missing
- calculations[]: 13 checked, 13 fully expressed (constants embedded, pinned evaluation orders stated), 0 missing
- validations[] conditions: 26 checked, 26 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 52 checked, expressed, 0 missing
- entities[].fields[] structured content: defaults/initial values/sources placed on owning entities, 0 missing
- sibling-branch symmetry: 6 groups (CLASS_I vs CLASS_II/III, PASS vs FAIL verify, MITIGATED vs ACCEPTED_RISK, strict vs operational denominator, POOL vs RENTAL, IN_HOUSE vs VENDOR costing), 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 863
- tokens starting with `/`: 0 | bare HTTP-method tokens: 0 | method+path tokens: 0
Status: PASS
```

§2.2 was pasted byte-identical from `section-2.2-response-structure.md`.

**Scaffold items I could not express as-is:** none omitted. Two notes: (1) `security_attestation_on_file` and `acquisition_cost_cents` carry no downstream rule in the scaffold, so they appear in narrative as record attributes only; (2) the scaffold header comment claims "38 error codes, 7 state machines" but the actual tables contain 41 and 8 — I generated against the tables, not the comment. The withheld design files were not opened.

## Step 6: Generate implementation — 2026-08-29T15:56:44.000Z

Implementation is complete at `/home/ubuntu/github/CodingPRD/tasks/task_2174_clinical_engineering_biomed/workspace/implementation/`.

## Modules written (17 files, ~2,700 LOC, all written incrementally)

| File | Role |
|---|---|
| `start.sh` | Guarded `pip install` (`if ! python3 -c "import flask"`), `exec python3 app.py` |
| `app.py` | Flask factory, blueprint registration under `/clinical-engineering`, error handlers, per-request store lock, `0.0.0.0:$PORT` (default 10000) |
| `util.py` | ISO-8601 ms formatting/parsing, exact `Fraction`-based round-half-up primitives |
| `errors.py` | 41-entry error→HTTP catalogue + `ApiError` |
| `envelope.py` | `meta`/`response_type`/`data` envelope; list `meta` carries `limit`/`offset`/`total_count`/`has_more` |
| `store.py` | In-memory dicts keyed by id, logical clock (defaults `2026-08-01T00:00:00Z`), `touch()` = `updated_at` + `version+1` |
| `validate.py` | Body/query well-formedness, unknown-key & computed-field rejection, pagination |
| `auth.py` | `X-User-ID`/`X-User-Role`, 5 roles, entity-backed ownership for `DeptSteward`/`VendorRep` |
| `calc.py` | All 13 calculations with pinned rounding orders |
| `services.py` | Cascades: conditional restore, quarantine, loaner cancellation/escalation, budget→posture, PM deferral, WO factory |
| `routes_core / _devices / _pm / _wo / _loaner / _recall / _contracts` | The 52 routes |

**Endpoint coverage: 52/52.** A programmatic diff of the Flask url_map against SCAFFOLD §1.5 reports `MISSING: []`, `EXTRA: []`.

**Verification:** three live smoke suites (~130 assertions) against a fresh `start.sh` process — all green. Covered: risk classification (44→CRITICAL), the PRD's pinned labour example (43,938), contract selection + exhaustion, pre-debit overhead tiers, per-day rental rounding, half-open loaner occupancy vs closed contract intervals, both repair cycles, PM audit dual denominators, CLASS_I vs CLASS_II divergent branches, quarantine cascade, segregation of duties, OCC 412s, and the full priority-1–26 rejection ladder. Store confirmed empty on every boot; no seeding, no disk I/O.

## PRD passages I found ambiguous, and how I resolved them

1. **`created_at`/`updated_at` clock source** — §2.5 lists the domain instants but omits these. Used the *logical* clock (consistent with "must not fall back to real wall-clock time"), with a monotonic insertion sequence as a stable secondary sort key so `created_at ASC` tie-breaks stay deterministic when the clock doesn't move.
2. **`ERR_DEVICE_QUARANTINED` on loaner creation** — §2.11(11) reads as covering both "the device under service" *and* the named loaner unit. Implemented both (downed unit first, then named unit). If the intent was named-unit-only, a quarantined downed unit would newly reject loaner coverage — this is the single riskiest reading in the build.
3. **Does the replacement-plan GET bump `version`?** — §2.10 says every touched row increments, but the scaffold lists version increments explicitly for every other endpoint and *not* for this read. Chose: persist `plan_rank`/`plan_funded`/score, do **not** bump `version` or `updated_at`.
4. **Plan rank/funding vs pagination** — computed rank and ran the waterfall over the *full* ranked set (the scaffold formula iterates `ranked`, unpaginated); pagination applies only to the response body.
5. **`assign` guard order** — §3.4 lists lockdown before retired; §2.11 places retired (10) before lockdown (13). Followed §2.11's global order (§2.11 is declared the ordering authority). Vendor existence on assign is checked at step 6 (body-FK), since §2.11(6) doesn't enumerate assign but a 404 is the only sensible code.
6. **Client-supplied instants** — echoed verbatim (parsed only for comparison), so `window_start` etc. round-trip byte-identically; `_clock/set_current_utc` likewise echoes `to_iso8601` as `current_utc`. Server-stamped instants use the normalized `...T..:..:...000Z` form.
7. **`VendorRep` reading `GET /vendors/{id}`** — both PRD §2.1 and scaffold validation 3 enumerate only WorkOrder and ServiceContract for VendorRep ownership, so no ownership check there. Likewise, list endpoints are not ownership-filtered (no PRD rule defines it).
8. **Resolving an already-terminal `SecurityFinding`** — no dedicated finding-state error exists; used `ERR_INVALID_SECURITY_STATE` (409), the only state code the scaffold assigns to that entity.
9. **`service_mode: IN_HOUSE` with a `vendor_id` present** — accepted, `vendor_id` left null (recording it would corrupt contract selection).
10. **Multiple field mutations in one request** — one `touch()` (version +1) per row per request, not one per field.

## Step 5: Generate unit tests — 2026-08-29T16:04:29.000Z

Test infrastructure and suite are complete and audited.

## Files written

**`test_helpers/`** (9 files, ~2,270 lines)
- `types.py` — 21 state/role enums + TypedDicts for all 12 entities (all carry `id`/`created_at`/`updated_at`/`version`, per PRD §2.4 "There are no identity-only resources in this domain")
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (52 endpoints + the logical clock)
- `api_errors.py` — all 41 error IDs + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions, `assert_budget_state_consistent`, `assert_timestamp_equals` (fraction-tolerant ISO compare)
- `factories.py` — payload factories + 4 canonical catalogue models and 4 device profiles with pre-verified risk scores (pump 38/CRITICAL, monitor 22/MEDIUM, pool 21/MEDIUM, scale 8/LOW)
- `constants.py`, `test_users.py` (per-instance builders `make_dept_steward_headers` / `make_vendor_rep_headers` for the two `entity_backed` roles), `fixtures.py` (1,016 lines, ~60 helpers across all 5 tiers), `__init__.py`

**`test_suite/`** (11 files, ~3,560 lines) — `conftest.py` plus `test_01_inventory_and_catalogue` … `test_10_concurrency_and_cascades`.

## Coverage

**127 tests**, all collect cleanly under pytest; pyflakes-clean; no `skip`/`skipif`/`xfail`; no scaffold references in emitted code.

| Queue | Instances | Translated | Skipped | Tests |
|---|---|---|---|---|
| A — Difficulty (§1.8) | 19 | 19 (all >= 2 tests) | 0 | 48 |
| B — Corner (§1.9) | 75 active + 3 stubs | 75 (all >= 1 test) | 0 | 79 |

All 3 `excluded_because:` stubs were verified to cross-reference a real difficulty instance and were **not** translated.

## Audits passed
- **Scaffold citation (C4):** every test docstring ends with exactly one `Design:` line; zero untagged, zero dual-tagged, zero unresolvable tags, zero stub tags emitted.
- **PRD citation (C1–C3):** 217 quoted sentences, **all 217 survive a literal whitespace-normalised match against `workspace/PRD.md`** (two initially-truncated §2.9 `budget_state` quotes were repaired to the full sentence).

## Notable adjudication
One assertion was dropped rather than emitted: `Corner/entities/device_create_optional_fields_apply_declared_defaults` asserts `lot_number == null`, but PRD §3.2 calls `lot_number` "an optional manufacturing `lot_number`" without naming a server-side default — that is the `default-value` silence pattern, so the test keeps the three defaults the PRD *does* name (`condition_score` 1, `utilization_hours` 0, `is_loaner_pool` false) plus the derived risk score, and omits the `lot_number` claim. No instance was skipped in full.

All computed literals in the design indices were independently re-derived from the PRD formulas before being asserted (e.g. 82938/25000 dual-variant cost, 295037 per-day rental rounding, 9450 T1 overhead, 33.33/50.00 compliance split, 60.63/68.13/75.63 replacement scores, 13500 s active repair).

## Step 7: Run tests and iterate — 2026-08-29T16:12:57.000Z

The task was already fully green. The 8-round parallel sweep passed on the first iteration, and I verified the result is genuine rather than vacuous or leak-tuned.

## Summary

**Iterations run:** 1 (plus a 3-mutant verification sweep)

**Sweep result — all 8 parallel rounds identical:**

| Round | passed | failed | errors | skipped | duration |
|---|---|---|---|---|---|
| 1–8 | 127/127 | 0 | 0 | 0 | ~160.5s each |

No flakiness: the union of failing tests across all 8 rounds is empty, and per-round durations were within 0.1s of each other.

**Tests deleted:** none. No test failed in any round, so the STEP 1 coverage / unique-derivability protocol was never triggered.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none. The working tree is byte-identical to its pre-existing state (only untracked-directory entries in `git status`; the sole new files are the `results.{1..8}.json` sweep artifacts).

### Verification that the green sweep is real

My standing concern with a first-sweep green is that vacuous, leak-tuned, and genuinely-complete suites all print the same `passed == total`. Three checks:

1. **Suite is fully live** — 127 collected tests match the 127 `def test_` functions across the 11 test files; `skipped == 0`, `errors == 0`. No `pytest.mark.skip` / `xfail` anywhere (the grep hits on "skip" are a waterfall-semantics test *name* and its docstring, not markers).

2. **Storage contract holds** — `store.py` is in-memory dicts only, explicitly empty on boot. Zero hits for `sqlite`, `open(`, `json.dump`, `pickle`, `/tmp`, `redis`, or `shelve` anywhere in `implementation/`.

3. **Mutation test — 3/3 mutants caught.** I copied the implementation into isolated scratch dirs (the real tree was never touched) and ran a full round against each:
   - **Mutant A** (calc constants: risk band 26→27, long-term discount day 7→8, empty-denominator constant 100→0, remediation SLA 7→8) → 5 targeted failures, incl. `test_risk_score_twenty_six_classifies_high` and `test_empty_denominators_report_asymmetric_compliance_constants`.
   - **Mutant B** (ownership enforcement disabled in `auth.py`) → `test_a_steward_may_not_report_a_fault_on_another_departments_device`, `test_a_vendor_rep_may_not_complete_another_vendors_repair`.
   - **Mutant C** (segregation-of-duties error id swapped, lockdown and quarantine-on-close guards short-circuited in `routes_wo.py`) → `test_a_technician_may_not_verify_their_own_repair`, plus both lockdown-posture tests.

   Each mutant failed exactly the tests owning the mutated rule and nothing else, which rules out both a vacuous suite and assertions tuned to the implementation.

### One incidental finding (not a failure, no action taken)

Mutating `SLA_HOURS["P2"]` from 24 to 25 was **not** caught. The suite asserts `sla_hours == 4` for P1 and `== 72` for P3 explicitly, and `test_helpers/assertions.py:135` has a general `assert data["sla_hours"] in (4, 24, 72)` — but no test drives a P2 order through that helper. PRD §3.4 does state the rule verbatim ("4 hours for `P1`, 24 hours for `P2`, 72 hours for `P3`"), so a P2 assertion would be fair game. I did not add one, since adding tests is outside the diagnostic protocol's mandate — flagging it in case you want that gap closed separately.

**Orchestrator note — results artifacts verified present after Step 7 exit:** all 8 of `workspace/implementation/results.{1..8}.json` exist on disk and each reports `passed=127 total=127 failed=0`.

## Step 8: Finalize PRD — SKIPPED — 2026-08-29T16:12:57.000Z

Skip condition met per the pipeline spec: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. `PRD.md` already determined every behavior the tests exercised, so there is no `<step_7_diff>` to patch and `PRD_FINALIZED.md` is not produced. Step 9 therefore starts from `PRD.md`.

## Step 9: Complete PRD — 2026-08-29T16:21:44.000Z

Done. `PRD_COMPLETED.md` is written; no other file was created, moved, or modified (all eight `results.{1..8}.json` are untouched).

## Summary

- **Source vs completed**: `PRD.md` 415 lines / 81,784 chars → `PRD_COMPLETED.md` 415 lines / 92,477 chars (**+10,693 chars**, 0 line delta — every change is an in-paragraph insert or revision; no new sections, no new paragraphs).
- **Counts**: 35 edits total — **26 ambiguity-pins**, **9 mismatch-revisions**.
- All 10 generator-declared resolutions were verified against the code and pinned; the scan also turned up ~25 further silences/mismatches.

### Changes

- §2.1 — revise — ambiguity — headers: absent/empty **or whitespace-only** → `ERR_UNAUTHENTICATED` — `auth.py:16`
- §2.1 — insert — **mismatch** — ownership is *not* universal: facility read and vendor read carry no check; no list endpoint is ownership-checked or filtered; `WorkOrder`/`LoanerAssignment` owned transitively via device→department; a `VendorRep` reading an order with null `vendor_id` is refused; unresolvable ids skip the check — `routes_core.py:53,218,185`, `auth.py:48-95`
- §2.1 — insert — ambiguity — department read compares the path id to `X-User-ID` without a lookup, so an unknown id answers `ERR_OWNERSHIP_VIOLATION` ahead of the 404 (sole exception) — `auth.py:42`, `routes_core.py:181`
- §2.2 — insert — ambiguity — `api_request_timestamp` read from the logical clock, errors included — `envelope.py:186`, `app.py:55`
- §2.3 — insert — ambiguity — enum-valued list filters validated → `ERR_INVALID_REQUEST`; non-integer `limit`/`offset` too; id filters matched literally — `validate.py:165-194`
- §2.3 — insert — ambiguity — `created_at` ties broken by a monotonic insertion sequence, never by `id`; same tie-break in every §3 ranking — `store.py:184,200`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` sourced from the logical clock — `store.py:171,188`
- §2.4 — insert — ambiguity — one `version` increment per row **per request**, not per field — `store.py:186-189`
- §2.4 — insert — ambiguity — wrong-JSON-type inputs also `ERR_INVALID_REQUEST` — `validate.py:61-99`
- §2.4 — insert — **mismatch** — all `note`/`reason` inputs validated then discarded; only the resolve `note` persists as `resolution_note` — `routes_core.py:65`, `routes_pm.py:118`, `routes_wo.py:155,208,337`, `routes_recall.py:192`, `routes_devices.py:148`
- §2.5 — revise — ambiguity — clock endpoint returns a bare `{"current_utc": …}` echoing `to_iso8601` **verbatim** — `routes_core.py:256-257`
- §2.5 — insert — ambiguity — server-stamped instants normalized to 3 fractional digits; client-supplied instants stored/echoed character-for-character; recall-shifted PM windows the lone exception — `util.py:105-109`, `services.py:358-360`
- §2.6 — insert — ambiguity — two-decimal figures serialized as JSON numbers (`100.0`, `43.5`), not fixed-width strings — `util.py:166-170`
- §2.11 step 3 — revise — **mismatch** — scope corrected to match §2.1 — `auth.py:42-95`
- §2.11 step 6 — insert — **mismatch** — assign's `vendor_id` existence checked at step 6, ahead of state (9) and approval (24) — `routes_wo.py:122`
- §3.2 — insert — ambiguity — `utilization_hours` is a whole integer >= 0 — `routes_devices.py:48`
- §3.2 — revise — ambiguity — PATCH: one `version` bump however many fields; a no-field PATCH is accepted and still bumps; retirement guard after body validation — `routes_devices.py:120-138`
- §3.3 — insert — ambiguity — PMTask creation defaults (`result`/`completed_at`/`completed_by_user_id` null, `labor_minutes` 0, `on_time` false) — `routes_pm.py:41-44`
- §3.3 — insert — ambiguity — `labor_minutes` a whole integer >= 0 — `routes_pm.py:75`
- §3.4 — revise — **mismatch** — origin finding advances **only** from `OPEN`; must exist at step 6; never blocks intake — `routes_wo.py:64,76-78`
- §3.4 — revise — **mismatch** — assign precondition order replaced by the §2.11 global order; `VENDOR` without `vendor_id` = `ERR_INVALID_REQUEST`; `IN_HOUSE` **with** `vendor_id` accepted, `vendor_id` left null — `routes_wo.py:119-140`
- §3.4 — insert — ambiguity — a segment with zero/negative elapsed contributes 0 rather than subtracting — `routes_wo.py:33-34`
- §3.4 — revise — **mismatch** — WO cancel: `loaner_status` → `UNCOVERED` only when a deployed loaner was released; **no** P1 escalation; timing fields not finalised — `routes_wo.py:342-354`
- §3.5 — revise — ambiguity — `sla_met` compares the *rounded* two-decimal `active_repair_hours` — `routes_wo.py:305-310`
- §3.5 — revise — **mismatch** — origin finding moved to `MITIGATED` from `OPEN` as well as `REMEDIATION_SCHEDULED`; device stamped exactly once whether or not restoration fires — `routes_wo.py:315-327`
- §3.6 — insert — ambiguity — downed unit `RETIRED`/`QUARANTINED` guards, and a named loaner unit that is `VULNERABLE`/`QUARANTINED` → `ERR_DEVICE_QUARANTINED` ahead of all four loaner checks — `routes_loaner.py:84-90`
- §3.6 — insert — ambiguity — candidate ranking tie-break extends to insertion sequence after `created_at` — `routes_loaner.py:123-124`
- §3.6 — revise — **mismatch** — P1/sla-4 escalation applies on the recall and quarantine paths only; the WO-cancellation path is excluded — `services.py:254-260`, `routes_wo.py:351`
- §3.7 — insert — ambiguity — `PENDING` is not an accepted disposition input → `ERR_INVALID_REQUEST` — `routes_recall.py:191`
- §3.7 — insert — ambiguity — `REMOVED` leaves `recall_hold` `true` — `routes_recall.py:209-211`
- §3.8 — insert — ambiguity — resolving an already-terminal finding → `ERR_INVALID_SECURITY_STATE` (409) — `routes_contracts.py:383-385`
- §3.8 — revise — **mismatch** — `MITIGATED` lifts a quarantine on **any** `QUARANTINED` device; no causation is recorded; one device version bump — `services.py:324-341`
- §3.9 — insert — ambiguity — paging applied last, to the response body only; rank + waterfall run over the whole non-retired fleet and are written to every such device — `routes_core.py:130-154`
- §3.9 — insert — ambiguity — `fiscal_budget_cents` is a query parameter, whole integer >= 0 — `routes_core.py:128`
- §3.9 — insert — ambiguity — the plan read persists `plan_rank`/`plan_funded`/`replacement_priority_score` **without** touching `updated_at` or `version` — `routes_core.py:133-152`

**Orchestrator note — post-Step-9 artifact verification:** `workspace/PRD.md` (415 lines) and `workspace/PRD_COMPLETED.md` (415 lines) both present; all 8 `results.{1..8}.json` still on disk. `PRD_FINALIZED.md` absent as expected (Step 8 skipped). Pipeline complete.
