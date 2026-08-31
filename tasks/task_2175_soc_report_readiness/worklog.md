# Worklog — task_2175_soc_report_readiness

## Step 1: Create Task Directory — 2026-08-29T00:00:00.000Z

Created `tasks/task_2175_soc_report_readiness/` and `tasks/task_2175_soc_report_readiness/workspace/`.

## Step 3: Copy Shared Files — 2026-08-29T00:00:00.000Z

Copied `INSTRUCTION.md` to `tasks/task_2175_soc_report_readiness/workspace/INSTRUCTION.md`.

## Step 2: Generate Scaffold — 2026-08-29T00:00:00.000Z

All three artifacts are generated and lint clean.

### Verdict block (verbatim from `scaffold_lint.py`)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    68
  §1.1 entities declared:     15
  §1.8 instances scanned:     27
  §1.9 instances scanned:     63
  Calls scanned (§1.8+§1.9):  892

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

### Files

- `SCAFFOLD.yaml` (§1.0–§1.7, 3282 lines)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`, 27 instances)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`, 68 instances across all nine guide sections, 5 of them `excluded_because` stubs)

### Design summary

**Profile**: Compliance/audit × posture-driven gating; `entity_topology: graph`, `state_machine_shape: parallel`, `role_model: segregation_of_duties`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, ops_run_checkpoint]`. Expert-band top end: 15 entities, 68 endpoints, 48 errors, 10 calculations, 14 state machines, 7 roles, 2 OCC rules.

**Difficulty spine** (all nine §0.5 rules exceeded, 2–4 instances each):
- Dual-variant on two entity domains: `criteria_coverage` (readiness_view 2/5 vs attestation_view 0/5) and `exception_projection` (5.00 vs 6 on identical sample data).
- Combinatorial in all three modes: sample sizing (nested `min`/`max` + automation + report-type branches → 13 vs 4), `readiness_score` pinned per-category-round-then-average (33.33 vs the pooled 40.00), and `gap_debt_points` with the tier keyed on pre-surcharge base (28.75 vs the circular 32.50).
- Three depth-4 cascades from three different triggers (sample conclude → exception → control → gap → posture; carve-out switch → control scope → coverage-loss gaps → posture; calendar-run → missed evidence → ineffective control → gap → posture).
- Four validation priority pairs across four distinct category pairs (state/referential, safety/temporal, auth/existence, constraint/fiscal).
- Three interval semantics on three resources: half-open evidence periods (adjacency legal), closed bridge-letter windows (touching collides), buffered inclusive-subservice windows (≥1 clear day required).
- Three conserved quantities for the compensating invariants: distinct-criterion coverage count, weighted debt points, live exception count.

**Notes for downstream**: logical clock defaults to `2026-08-01T00:00:00.000Z`; every formula-derived assertion literal was computed with a Decimal `ROUND_HALF_UP` script rather than estimated. Independently verified beyond the linter: zero unbound `${var}` across 892 calls, 95 unique instance names, every one of the 48 error codes both referenced by a §1.4/§1.2 declaration and exercised by a design instance, all `excluded_because` stubs resolve to real §1.8 names, and no forbidden concurrency vocabulary anywhere. No sibling task directory was read.

## Step 4: Generate PRD — 2026-08-29T00:00:00.000Z

PRD generated at `workspace/PRD.md` — 460 lines, ~102 KB, written incrementally across five appends. No section truncated; the file ends correctly at the §5 error table with no audit footer.

**Structure**
- §1 Introduction (3 paragraphs — business pain, system scope, the two design commitments)
- §2: 2.1 Operators/RBAC · 2.2 Response Structure (verbatim) · 2.3 Pagination · 2.4 Identity, Timestamps & Logical Clock · 2.5 Stale-View Protection (OCC) · 2.6 Precision, Rounding & Interval Conventions · 2.7 The Order in Which a Request Is Judged (29-step validation ladder) · 2.8 Engagement Posture as Cross-Cutting Gate · 2.9 Nested Path Resolution & Denormalised Counters
- §3: nine subsections following the engagement lifecycle — engagement/system description → boundary & subservice orgs → criteria catalog, controls, two coverage views → ownership, evidence calendar, observation → readiness assessment & debt ledger → fieldwork sampling & exceptions → calendar ops-run → reporting/issue/distribution → bridge letters, CUECs, deflection waterfall
- §4: 68-endpoint table (4 columns) · §5: 48-error table (2 columns)

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 163 required tokens total (entity fields + endpoint inputs + query params + path params + computed-read output keys), 163 present, 0 missing
- endpoints[].request_body/input: all present, 0 missing
- endpoints[].query_params: all present, 0 missing
- endpoints[].path_params: all 15 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 35 checked, 35 expressed in prose (§2.7 renders the full ladder in numeric priority order, including the four explicit precedence notes: role-before-lookup, frozen-beats-everything-later, owner-before-window, uniqueness-before-ceiling), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (POST /soc/system-descriptions + expected_engagement_version + ERR_STALE_ENGAGEMENT_VERSION/412; POST /soc/audit-samples + expected_control_version + ERR_STALE_CONTROL_VERSION/412), 0 missing
- state_machines[].transitions: 14 machines / all transitions checked, all fully expressed with from/to, preconditions paired to error ids, and every side effect, 0 missing
- calculations[]: 10 checked, 10 fully expressed in operator-free prose (coverage dual-view, readiness_score pinned round-then-average, debt tiering from pre-surcharge base, posture precedence, sample sizing, dual-view projection, calendar generation, deflection waterfall, bridge coverage days, gap synthesis two-pass), 0 missing
- validations[] conditions: 35 checked, 35 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 68 endpoints checked, all side-effect sets and all applies_to enumerations expressed, 0 missing
- entities[].fields[] structured content: 15 entities checked, all defaults/initials/derivations reconstructible from prose (incl. TrustCriterion's absent updated_at/version), 0 missing
- sibling-branch symmetry: 6 groups checked (CONCLUDED_CLEAN vs CONCLUDED_EXCEPTIONS, ISOLATED vs PERVASIVE, DEFLECTED/PARTIALLY_DEFLECTED/MANUAL_RESPONSE, CARVE_OUT↔INCLUSIVE, readiness_view vs attestation_view, WITHDRAW edges), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1093
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 diffs byte-identical against `section-2.2-response-structure.md` (only a trailing blank separator line added). No fuzzy/approximating words used in any formula translation. The two withheld design-index files were never opened, grepped, or referenced.

One judgement call worth flagging: the scaffold lists `POST /soc/engagements/{engagement_id}/readiness-assessment` under the `ERR_ENGAGEMENT_PHASE_INVALID` scope but never declares its phase set in a §1.2 transition. I resolved it to the `READINESS` phase, which is the only reading consistent with the `READINESS → OBSERVATION` precondition that `readiness_assessed_at` be non-null.

## Step 6: Generate Implementation — 2026-08-29T00:00:00.000Z

The implementation is complete and verified.

### What was built

`workspace/implementation/`

```
start.sh              # guarded pip install + exec python3 app.py, 0.0.0.0:$PORT (default 10000)
requirements.txt      # Flask
app.py                # blueprint registration, error handlers, POST /_clock/set_current_utc
store.py              # in-memory dicts (15 collections), logical clock, ISO/decimal helpers
errors.py             # 47-entry error catalogue + per-entity NOT_FOUND map
envelope.py           # meta/response_type/data envelope + pagination meta
auth.py               # header auth, role + action-role gates, SubserviceContact identity, pagination
validators.py         # ERR_VALIDATION shape checks + body-FK resolution (step 6 before step 7)
calcs.py              # all 10 calculation constant sets and pure formulas
services.py           # derived-state engine + every cascade (coverage, debt, posture, carve-out,
                      # sample conclude/void, calendar-run, readiness synthesis, abandon)
routes/*.py           # 15 resource modules covering all 68 endpoints
```

Storage is in-memory only, and every collection is verified empty on a fresh boot — nothing is seeded, preloaded, or hardcoded.

### Key spec decisions (PRD-first)

- **Validation order** follows PRD §2.7's 29 steps literally, including the deliberate inversions: ownership before submission-window, uniqueness before distribution ceiling, role check before path-id lookup, boundary-scope-mismatch (422) before boundary-locked (409).
- **`ERR_INVALID_STATE` vs `ERR_TRANSITION_NOT_ALLOWED`**: an action/disposition/method with no outgoing edge from the current state → `ERR_TRANSITION_NOT_ALLOWED`; an edge that exists but whose preconditions fail → `ERR_INVALID_STATE`. Action-less endpoints (submit, conclude, void, lock-boundary, issue, deflect, mapping delete) report `ERR_INVALID_STATE` on from-state mismatch. This is the only reading that keeps both catalogue entries reachable, and matches scaffold check 150's wording.
- **Engagement `version`** bumps only on the six operations PRD §2.4 "lists in full" (SD authored, SD approved, boundary locked, phase transition, readiness assessment, calendar-run). Denormalised recomputes never bump it — otherwise the enumeration could not be complete, and OCC on `expected_engagement_version` would be unusable.
- **`evidence_scheduled_count`** uses the literal per-edge deltas from §3.4 (PRD §2.9 says stated increments win over "recomputed"), which knowingly diverges from §3.3's status-based prose — the two sections contradict each other and the delta rules are the operational ones.
- **Rounding** is `Decimal` + `ROUND_HALF_UP` throughout; readiness score rounds per category *then* averages (pinned order); debt tier is selected from the pre-surcharge base only.

### Verification

Seven scripted end-to-end suites (each on a fresh server) all pass, covering: the full SCOPING→ISSUED ladder; SD supersession + review loop + SoD; boundary lock/scope coherence; both coverage views disagreeing (66.67 readiness vs 33.33 attestation); readiness score with an empty category (50.00); readiness-assessment idempotence; sample sizing across all frequency/automation/risk/SOC-1 combinations; zero-population direct-to-`CONCLUDED_CLEAN`; the depth-4 exception cascade (`open_exception_count`→FROZEN, base 11 → 12.65 with the 15% tier); PERVASIVE escalation to `DESIGN_DEFICIENT` + CRITICAL gap; full void compensation; the depth-4 carve-out cascade with `COVERAGE_LOSS` gaps; calendar-run evidence-miss → `TESTED_INEFFECTIVE`; bridge-letter closed-interval overlap (touching endpoints rejected); subservice buffer arithmetic; the deflection waterfall and the revoke un-deflect cascade; and the auth/pagination/404/422 matrix.

Note: the agent did not open `test_suite/` or `test_helpers/` — those are the withheld artifacts for this stage, so the implementation is derived only from PRD.md, SCAFFOLD.yaml and INSTRUCTION.md.

## Step 5: Generate Unit Tests — 2026-08-29T00:00:00.000Z

Test infrastructure and suite are generated and verified.

### What was produced

**`test_helpers/`** (2,365 lines, 9 files)
- `types.py` — 21 status/role enums + 15 entity TypedDicts. `TrustCriterion` correctly omits `updated_at`/`version` (`common_fields: false`); every other entity carries them.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (all 60 including `/_clock/set_current_utc`).
- `api_errors.py` — 48 error IDs + HTTP map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions plus domain invariants (`assert_debt_decomposition` re-derives the three-step tier arithmetic; `assert_coverage_ordering` pins attestation <= readiness).
- `factories.py`, `constants.py`, `test_users.py` (per-role builders; `make_subservice_contact_headers` takes the real org id, since `SubserviceContact` is the one entity-backed role).
- `fixtures.py` (868 lines) — primitives plus the phase-ladder builder `setup_engagement_at(phase=SCOPING|READINESS|OBSERVATION|FIELDWORK, criteria=..., controls=[...])`, and tier-4 `setup_issued_engagement` / `setup_delivered_report` (zero-population ADHOC control -> auto-`CONCLUDED_CLEAN` -> 100 % attestation -> `ISSUE` -> `DELIVER`), which is what makes the bridge-letter and questionnaire fixtures reachable at all.

**`test_suite/`** (4,740 lines, 10 files + conftest) — **117 tests, all collecting cleanly.**

### Coverage against the design-index contract

- **Queue A**: all **27** difficulty instances x exactly 2 tests = **54** tests.
- **Queue B**: all **63** non-stub corner instances x 1 test = **63** tests.
- The **5** `excluded_because:` stubs were *not* translated; each stub's `difficulty_instance` pointer was verified to resolve to a real name in the difficulty index.
- Zero instances skipped — every one passed the PRD-first two-condition filter.

Verified by a checker script (AST-walks every test): 117 tests, 90 distinct tags, **0 problems**; every quoted PRD span survives a whitespace-normalized literal match against `PRD.md`; exactly one `Design:` line per docstring, all resolving to real `rule_id`/`section` + `name` pairs. No `skip`/`skipif`/`xfail` anywhere; no "scaffold"/table references in generated code.

### Two judgment calls worth flagging

1. **Three tests use `validate_error_is_one_of`** instead of an exact code: `corner_system_description_approve_directly_from_draft_rejected`, `corner_abandoned_engagement_accepts_no_further_transitions`, `corner_gap_verify_from_open_rejected`. PRD §2.7 step 14 ("the row's own current state satisfies the requested transition's **originating state**", -> `ERR_INVALID_STATE`) and step 16 ("the action is an outgoing edge from the row's current state", -> `ERR_TRANSITION_NOT_ALLOWED`) both describe the same failure, so two PRD-only implementers could reasonably ship either code. This is the skill's `error-precedence` Silence pattern; the tests still pin HTTP 409 and full post-state. **This is a latent PRD ambiguity** — worth tightening §2.7 if you want the exact code asserted.

2. `ERR_SAMPLE_INCOMPLETE` was *not* relaxed the same way, because §3.6 names it explicitly for that exact scenario ("a short sample rejected as `ERR_SAMPLE_INCOMPLETE`"), which overrides the generic step-14 reading.

All the design indices' pre-computed literals were independently re-derived and matched (sample sizes 13/4/10/2, `deviation_rate` 0.2500/0.5000/0.1000, `projected_failures` 5.00/10.00/4.00, `projected_failures_upper` 6, debt 28.75/18.40/12.65/23.00, `readiness_score` 33.33, `coverage_days` 63/59/32/152, deflection ratios 0.5000/0.2500).

## Step 7: Run Tests and Iterate — 2026-08-29T00:00:00.000Z

The task was already in a passing state. Here is the report.

### Summary

**Iterations run: 1** (one 8-round parallel sweep — no fixes were required).

**Sweep result:** all 8 concurrent rounds returned `117 / 117` passed, `0` failed, `0` errors, `0` skipped. The union of failing tests across all 8 rounds is empty — no flakiness surfaced. Single-round duration ~147s.

**Tests deleted:** none. The diagnostic protocol never engaged, since STEP 0 found no failing tests in any round.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

#### Anti-vacuity check

Because a first-sweep green can mask a vacuous or leak-tuned suite, the agent mutation-tested it: changing a single constant in `workspace/implementation/calcs.py` (`TIER_2_RATE` from `Decimal("0.15")` to `Decimal("0.20")` — the PRD §3.5 mid-tier surcharge rate) dropped the suite to **107 passed / 10 failed**, hitting the debt-tier tests plus every downstream posture cascade (`test_surcharge_reads_the_tier_off_the_pre_surcharge_base`, `test_a_base_of_twenty_five_still_freezes_the_engagement`, `test_the_evidence_miss_cascade_adds_a_gap_and_restricts_the_engagement`, and 7 others). The constant was restored and verified byte-identical. The green sweep is genuine, not vacuous.

#### Notes on the two pre-flagged ambiguities

Both were already resolved correctly upstream, which is why they produced no failures:

- **§2.7 steps 14 vs 16 (`ERR_INVALID_STATE` vs `ERR_TRANSITION_NOT_ALLOWED`)** — a real PRD ambiguity. Step 5's generator had already applied the error-precedence-silence relaxation to the three affected tests, using `validate_error_is_one_of` while still pinning HTTP 409 and full post-state. That is exactly what the protocol prescribes, so no further action. If you want the exact code assertable, §2.7 needs tightening in the PRD, not in the tests.
- **§3.3 vs §3.4 on `evidence_scheduled_count`** — these only genuinely contradict on the `SUBMITTED -> REJECTED` edge (§3.4 says "increases by one", but the row lands in `REJECTED`, not `SCHEDULED`, so §3.3's status-based recompute would not count it). §2.9 arbitrates this explicitly: *"it means recomputed from the current rows — not incremented optimistically — unless the text says 'increased by' or 'decreased by'."* The implementation follows the literal deltas, which is the reading §2.9 mandates, and the tests agree. Not a defect.

No files under `test_suite/`, `test_helpers/`, or `workspace/implementation/` were modified; the working tree is unchanged apart from the eight `results.${i}.json` artifacts in `workspace/implementation/`.

**Orchestrator verification:** all 8 `results.{1..8}.json` re-read independently — each reports passed=117, failed=0, total=117, errors=0, skipped=0.

## Step 8: Finalize PRD — SKIPPED — 2026-08-29T00:00:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD_FINALIZED.md` is not produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-08-29T00:00:00.000Z

`workspace/PRD_COMPLETED.md` is written.

### Source vs output

| | PRD.md (source; `PRD_FINALIZED.md` absent) | PRD_COMPLETED.md |
|---|---|---|
| Lines | 460 | 460 |
| Bytes | 101,724 | 108,335 (**+6,611**) |
| §4 endpoint rows | 68 | 68 |
| §5 error rows | 48 | 48 |
| Top-level sections | §1–§5 | §1–§5 |

All 23 edits are 1:1 in-line replacements on 22 existing lines — no lines, paragraphs or sections added or removed.

### Counts
- **Ambiguity pins (PRD silent): 18**
- **Mismatch revisions (PRD said something else): 5**

### Changes

- §2.1 — insert — ambiguity — the action-actor role check (`ERR_ROLE_NOT_PERMITTED` for a permitted role that is not the named actor) is part of §2.7 step 3: before path-id resolution and before shape validation, and fires only for a recognised field value; an absent/unknown value falls to `ERR_VALIDATION` — `auth.py:38-47`, `routes/engagements.py:111-116`
- §2.3 — revise — ambiguity — `created_at` ordering ties broken by creation sequence — `store.py:157`
- §2.7 step 6 — insert — ambiguity — multiple body FKs resolve in a fixed owning-parent-first order (per-route list) — `routes/boundary_components.py:34-35`, `routes/gaps.py:40-42`
- §2.7 step 14 — **revise** — **mismatch** — step 14 runs *after* step 16 on action-carrying endpoints, so a wrong originating state there is `ERR_TRANSITION_NOT_ALLOWED`; `ERR_INVALID_STATE` covers only the transition's further preconditions, and remains the wrong-state code on the eight non-action endpoints — `routes/engagements.py:123-171`, `routes/audit_exceptions.py:232-235`
- §2.7 step 16 — **revise** — **mismatch** — edge test is evaluated immediately after step 13, before step 14 — `routes/gaps.py:92-105`, `routes/report_distributions.py:107-112`
- §2.9 — insert — ambiguity — counter recomputes touch neither `updated_at` nor `version`; the literal `evidence_scheduled_count`/`evidence_accepted_count` deltas do bump the control; the §3.7 sweep does not — `store.py:130-141`, `routes/evidence_requests.py:65-66,156-162`, `services.py:563-564`
- §3.1 — insert — ambiguity — SD `SUBMIT_REVIEW` component-count and engagement-in-`SCOPING` failures report `ERR_INVALID_STATE` — `routes/system_descriptions.py:104-109`
- §3.1 — insert — ambiguity — SD `APPROVE`'s `SCOPING` precondition is `ERR_INVALID_STATE` and is judged *before* SoD and CSOC — `routes/system_descriptions.py:113-125`
- §3.1 — insert — ambiguity — non-`APPROVED` lock is `ERR_INVALID_STATE`; re-locking an already-locked description is accepted and re-bumps the engagement `version` — `routes/system_descriptions.py:153-165`
- §3.2 — insert — ambiguity — same-method `set-method` is `ERR_TRANSITION_NOT_ALLOWED`; `CARVE_OUT` with null narrative is `ERR_INVALID_STATE` — `routes/subservice_orgs.py:84-89`
- §3.2 — revise — ambiguity — `inclusive_control_count` defined as controls naming the org with `in_scope` true — `services.py:282-288`
- §3.3 — **revise** — **mismatch** — `evidence_scheduled_count` is a running per-edge total, not a status recompute; a `REJECTED` row holds it one above the `SCHEDULED` row count; decrements floor at 0 — `routes/evidence_requests.py:65,125,161`, `services.py:563`
- §3.3 — revise — ambiguity — duplicate members in `applies_to_report_types` rejected — `validators.py:81-92`
- §3.3 — insert — ambiguity — a control registered against a carve-out org is minted `in_scope` false but `design_status` `DESIGN_DRAFT` — `routes/controls.py:48,60`
- §3.4 — insert — ambiguity — all five `START_OBSERVATION` conditions, frozen posture included, report `ERR_INVALID_STATE` — `routes/engagements.py:134-147`
- §3.4 — insert — ambiguity — bulk calendar returns 201 with the array of generated requests (not the control); a sub-period span returns an empty array with count 0 — `routes/controls.py:167-191`
- §3.5 — insert — ambiguity — readiness-assessment response body is the updated engagement row — `routes/engagements.py:207-216`
- §3.6 — **revise** — **mismatch** — a draw superseding a *concluded* sample advances the control's `version` by two (void cascade + explicit bump); superseding a `DRAWN`/`TESTING` sample by one — `routes/audit_samples.py:81-93`, `services.py:476-492`
- §3.6 — **revise** — **mismatch** — the `EXCEPTION_CASCADE` gap is created whenever >=1 exception row is minted, independent of whether the control's operating track actually moved — `services.py:452-464`
- §3.8 — insert — ambiguity — `START_REPORTING`/`ISSUE` consult only the posture-open gate, so a *frozen* engagement also gets `ERR_ENGAGEMENT_RESTRICTED`, and the gate precedes the edge test — `routes/engagements.py:120-125`, `services.py:645-647`
- §4 — revise — ambiguity — `/soc/engagements` list documented as filterable by status and report type — `routes/engagements.py:99-104`
- §4 — revise — ambiguity — `/soc/trust-criteria` list documented as filterable by category — `routes/trust_criteria.py:57-59`
- §4 — revise — ambiguity — `/soc/criteria-mappings` list documented as filterable by mapping type — `routes/criteria_mappings.py:78`

### Notes on the two flagged sites
Both upstream-flagged sites were confirmed independently and resolved against the implementation, not the tests:

1. **§2.7 14 vs 16** — the implementation applies the *inverse* of the PRD's stated ladder. Every action/disposition/method endpoint (`engagements`, `system-descriptions`, `controls`, `gaps`, `report-distributions`, `cuecs`, `subservice-organizations` `set-method`, `audit-exceptions` `evaluate`, `evidence-requests` `review`) does the edge lookup first and only then runs `ERR_INVALID_STATE` preconditions. The eight endpoints with no action field keep `ERR_INVALID_STATE` for a wrong originating state. Both steps were rewritten to state this and to cross-reference each other.
2. **§3.3 vs §3.4** — the implementation is purely literal per-edge deltas for `evidence_scheduled_count` (`+1` on schedule, `= n` on bulk generate, `-1` floored at 0 on `SCHEDULED -> SUBMITTED` and on the ops-run miss, `+1` on `REJECT`). §3.4/§3.7 were already correct; §3.3's status-based definition was the wrong one and was revised, with the observable `REJECTED` divergence spelled out.

`ERR_NOT_FOUND` / `ERR_METHOD_NOT_ALLOWED` / `ERR_INTERNAL` exist in `errors.py` as framework fallbacks but are absent from §5; the catalogue was left at 48 rows per the row-count constraint.

**Orchestrator verification:** `PRD_COMPLETED.md` re-checked — 460 lines, all five top-level sections present, file ends correctly at the §5 error table.
