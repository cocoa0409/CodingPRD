# Worklog — task_2790_home_battery_storage_installation_utility_rebate

## Step 1: Create task directory — 2026-09-04T21:51:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2790_home_battery_storage_installation_utility_rebate` and its `workspace/` subdirectory. Index 2790 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed.

## Step 2: Generate scaffold — 2026-09-04T23:04:00.000Z

All three scaffold artifacts for task 2790 are complete and lint-clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2790_home_battery_storage_installation_utility_rebate/`):
- `SCAFFOLD.yaml` — 2826 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2696 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` — 5489 lines

`workspace/` and `worklog.md` untouched (timestamps unchanged). No sibling task directory was read at any point.

**SCAFFOLD.yaml (§1.0–§1.7)** — no `scaffold_difficulty_design` / `scaffold_corner_design` keys present.
- 13 entities: InstallerAccount, Site, LoadCalculation, BatterySystem, Permit, InterconnectionApplication, IncentiveProgram, RebateClaim, CommissioningTest, MonitoringAlert, ByodEnrollment, DispatchEvent, DispatchPerformance (flat topology, `api_prefix: "/"`)
- 10 state machines, 2 OCC concurrency rules, 7 calculations, 15 ordered validations (priority ladder 10→70), **65 endpoints**, 57 errors, 6 roles (segregation_of_duties model, `identity:` declared)
- complexity_profile: workflow_orchestration / compliance_audit; layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`; state machine shape parallel+cyclic+branching; consistency immediate; difficulty expert_plus

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)** — 9 rule_ids / **23 instances**: dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)** — 9 sections / **86 instances (54 live + 32 `excluded_because` stubs)**: entities 11 (11/0), state_machines 12 (8/4), calculations 13 (5/8), validations 8 (3/5), endpoints 5 (5/0), errors 25 (13/12), rbac 5 (5/0), cross_cutting_complexity_layers 6 (3/3), consistency_model 1 (1/0). All 57 catalog errors are reachable across §1.8 + §1.9; every stub cites an existing §1.8 instance by `rule_id / instance_name` and carries no `test_recipe`; instance names are unique across the §1.8 ∪ §1.9 union.

**Lint verdict (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2790_home_battery_storage_installation_utility_rebate/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2790_home_battery_storage_installation_utility_rebate/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2790_home_battery_storage_installation_utility_rebate/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    65
  §1.1 entities declared:     13
  §1.8 instances scanned:     23
  §1.9 instances scanned:     54
  Calls scanned (§1.8+§1.9):  1376

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

One thing for the caller to action: `SCAFFOLD.yaml`'s `scenario:` block still begins with the line `Generate task harder than expert level!` because the scenario text was to be copied verbatim. Per the known leak path (scaffold scenario → PRD.md), that line should be stripped before Step 3.

**Orchestrator post-step action (per known leak guard):** the subagent's flagged line was stripped — removed line 4 (`Generate task harder than expert level!`) plus the following blank line from `SCAFFOLD.yaml`'s `scenario:` block. `grep -rn "harder than expert"` over the task dir is now clean, and all three YAMLs re-parse under `yaml.safe_load`. Line counts after the strip: SCAFFOLD.yaml 2824, SCAFFOLD_DIFFICULTY_DESIGN.yaml 2696, SCAFFOLD_CORNER_DESIGN.yaml 5489.

## Step 3: Copy shared files — 2026-09-04T23:05:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T23:22:00.000Z

PRD generated and verified. `/home/ubuntu/github/CodingPRD/tasks/task_2790_home_battery_storage_installation_utility_rebate/workspace/PRD.md` — **490 lines**, written incrementally (1 `Write` + 8 `cat >> … <<'PRDEOF'` appends, none over ~250 lines), so no output-cap truncation. `tail -40` confirms it ends cleanly at the last §5 table row (`| \`ERR_PROGRAM_BUDGET_EXHAUSTED\` | 422 |`) — a real section boundary, no audit footer, no mid-sentence cut.

**Section list**

- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 Actors, Identity Headers and RBAC · 2.2 API Response Structure (byte-verbatim, `cat`-ed from the canonical file) · 2.3 Pagination · 2.4 Flat Collections, Path Identifiers and Reverse Discovery · 2.5 Common Resource Properties and the Logical Clock · 2.6 Optimistic Concurrency on Aggregate Parents · 2.7 Units, Precision and Rounding Discipline · 2.8 The Two-Dimension System Status Model · 2.9 Cascade Discipline · 2.10 Ledger Invariants: Incentive Money and Dispatch Capacity · 2.11 The Model Catalog and Firmware Comparison · 2.12 Rejection Precedence (12 subsections, domain-derived)
- §3 Business Logic & Workflows — 3.1 Certifying an Installer and Recording the Premises · 3.2 Sizing the Backup: The Load Calculation · 3.3 Designing, Locking and Building the Bank · 3.4 Permitting and Field Inspection · 3.5 Interconnection: From Application to Permission to Operate · 3.6 Commissioning: Tests, Verdicts and the Commissioning Cascade · 3.7 Incentives: Programs, the Stacking Waterfall and Claim Adjudication · 3.8 Living With the System: Alerts, Warranty Claims and Expansions · 3.9 Bring Your Own Device: Enrollment, Dispatch and Settlement (9 subsections, within the 5–9 band)
- §4 Endpoint Definitions — 1 intro paragraph + 4-column table (Method, Path, Description, Authorized Role(s))
- §5 Error Code Catalogue — 2-column table (Error ID, HTTP Status)

**Coverage confirmation (machine-diffed against SCAFFOLD.yaml)**

- **65 endpoints**: all 65 rows present, set-identical to the scaffold's method+path pairs (0 missing, 0 extra), in scaffold order, and **all 65 rows' authorized-role cells match the scaffold's `roles` exactly** (0 mismatches).
- **57 errors**: all 57 in §5 with correct status codes, and every one of the 57 also appears in §1–§3 narrative with its trigger condition (§5 has no conditions column, per spec).
- **13 entities**: all 148 `fields[].name` across all 13 entities present verbatim in backticks; all 10 state machines' 52 transitions and every state name covered.

```
Field coverage check:
- entities[].fields: 148 required, 148 present, 0 missing
- endpoints[].request_body: 79 required, 79 present, 0 missing
- endpoints[].query_params: 23 required, 23 present, 0 missing
- endpoints[].path_params: 13 required, 13 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 15 checked, 15 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint + expected_battery_system_version / expected_dispatch_event_version + ERR_STALE_SYSTEM_VERSION / ERR_STALE_EVENT_VERSION all named), 0 missing
- state_machines[].transitions: 52 checked, 52 fully expressed, 0 missing
- calculations[]: 7 checked, 7 fully expressed, 0 missing
- validations[] conditions: 15 checked, 15 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 40 checked, 40 expressed, 0 missing
- entities[].fields[] structured content: 148 checked, 148 reconstructible from prose, 0 missing
- sibling-branch symmetry: 15 groups checked, 15 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 793
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Contract 2's numeric side was also checked mechanically: every distinct numeric constant in `calculations`, `concurrency_rules` and `state_machines` appears in the PRD (the two apparent gaps, `0.4` and `0.25`, are present as "40 percent" and "25 percent"; the only other unmatched integers are `validations[].priority` ordinals, which §2.12 conveys as an explicit 15-step ordering rather than as raw numbers).

**Scaffold contradictions resolved** (each by majority of entity defaults / state machine / endpoint `side_effects`, worth flagging to whoever writes the test suite): expansion rows open at `DESIGN_DRAFT` / `NOT_APPLIED` / `UNREGISTERED` (not the state machine's `DESIGN_LOCKED` / `APPLICATION_SUBMITTED`); `revision_round_count`, `supplemental_round_count` and `claim_round_count` advance on the review/entry edge, not on resubmission; alert acknowledgement is `CertifiedInstaller`-only per the endpoint `roles`; the expansion cost input is the incremental `installed_cost_cents`; permit expiry at mark-installed maps to `ERR_PERMIT_EXPIRED`; settlement blocked by a still-`PENDING` participation maps to `ERR_PERFORMANCE_STATE_INVALID`. `MODEL_INVERTER_FAMILY` and the CRITICAL-severity BYOD note are written descriptively since no scaffold validation enforces them.

Constraints honored: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced; `worklog.md` was neither read nor modified; the three contract reports live in this message only, not in PRD.md or any sibling file.

**Orchestrator truncation guard (per the known doc-generator failure mode):** independently verified — `wc -l` = 490; `grep "^#"` shows all five top-level sections (§1–§5) with §2 at 12 subsections and §3 at 9; `tail -25` ends on a complete §5 error-table row. Not truncated. `grep -in "harder than expert|scaffold|test_recipe"` over PRD.md is clean, so neither the difficulty directive nor any design-index vocabulary leaked in.

## Step 6: Generate implementation — 2026-09-05T00:07:00.000Z

Implementation complete and verified live.

## Files created (all under `/home/ubuntu/github/CodingPRD/tasks/task_2790_home_battery_storage_installation_utility_rebate/workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `app.py` | 78 | Flask factory, blueprint registration, error-envelope handlers (400/404/405/HTTPException/Exception) |
| `common.py` | 364 | Decimal/ISO-8601/firmware primitives, all domain enums, model catalog, thresholds |
| `store.py` | 138 | In-memory dict store, `_seq`, logical clock, `view()`/`touch()`/`where()` |
| `envelope.py` | 83 | `ok`/`created`/`collection`/`error` response envelopes + pagination meta |
| `errors.py` | 109 | All 57 error codes with PRD §5 HTTP statuses |
| `shape.py` | 238 | Payload validators (`fk`, `enum`, `number`, `integer`, `firmware`, `window`) |
| `security.py` | 148 | `guard` RBAC decorator, 6 roles, path-only ownership, entity-backed roles |
| `calc.py` | 281 | 7 calculations: load sizing, bank derivation, rebate award, verdicts, delivery, settlement |
| `rules.py` | 178 | Ledger mutators (reserve/disburse/reverse/release), territory + test-window conflict checks |
| `cascades.py` | 153 | Cascades A–D |
| `routes/core.py` | 150 | Installers, sites, logical clock |
| `routes/loadcalc.py` | 166 | Load calculations |
| `routes/systems.py` | 336 | Banks: design, lock, install, commission, warranty, expansions |
| `routes/permits.py` | 164 | Permits + field inspections |
| `routes/interconnection.py` | 206 | Applications, review, PTO |
| `routes/incentives.py` | 362 | Programs, claims, adjudication, pay, clawback, void |
| `routes/tests.py` | 131 | Commissioning tests |
| `routes/alerts.py` | 133 | Monitoring alerts + warranty claim cycle |
| `routes/byod.py` | 378 | Enrollments, dispatch events, participations, settlement |
| `routes/__init__.py` | 0 | package marker |
| `start.sh` | 10 | reads `$PORT`, binds `0.0.0.0`, `exec python3 app.py` in the foreground |
| `requirements.txt` | 1 | `flask>=2.0` |

**3807 lines total.** `python3 -m py_compile` over all 20 `.py` files: COMPILE_OK.

## Endpoint count
`app.url_map` yields **exactly 65** routes, matching PRD §4 one-for-one (the PRD's table also has exactly 65 rows). Note the PRD declares no list endpoints for installers or sites — only `GET /installers/{id}` and `GET /sites/{id}` — so those two collection GETs correctly return 405.

## Smoke test result
Launched `PORT=51790 bash start.sh`, ran four scripted functional passes (~150 requests), then killed by PID and `fuser -k 51790/tcp`; port confirmed free afterward.

Green end-to-end: full happy path (site -> load calc -> design -> permit -> interconnection -> 4 tests -> commission -> PTO -> warranty -> claim reserve/submit/approve/pay), both OCC rules (412 on stale system and event versions), both SoD checks (403 on PTO grant and claim pay), all four cascades (A revokes to `SUPPLEMENTAL_REVIEW`/`APPLICATION_SUBMITTED`; B re-prices 705000->690000 at commissioning; C supersedes the base bank; D suspends at clawback 2 and moves draft banks to `DESIGN_HOLD`), the three-bucket ledger invariant (`remaining+reserved+paid == total` at every step, 100000000 throughout), the permit correction limit (3 rounds then 409), stacking waterfall truncation, budget/commitment rejections, the shortfall-penalty branch, and enrollment withdrawal cancelling pending participations while releasing `enrolled_pledged_kw`.

Every computed figure was hand-checked against the PRD: load sizing (14.56/25.48, 19.56 after resubmission override, measured 15.0 and essential-loads 7.5/10.88), bank derivation (67.5/25.0, 47.6/18.4, expansion 6 units -> 71.4/27.6 with summed cost 3500000), rebate award with export multiplier (185000 x 0.90 = 166500), and settlement (gross 5000, penalty (10x0.8-5)x1000x0.5 = 1500, net 3500; bonus tier from the post-update ratio: 5625 -> 281 bonus -> 5906).

State/isolation: restarting via `start.sh` produced empty collections for every entity, no on-disk artifacts exist (only `.py`/`.sh`/`.txt`), and a grep for `sqlite|open(|json.dump|pickle|shelve|/tmp/|seed` returns nothing — storage is purely in-process and nothing is seeded at startup.

Two notes for downstream: the scaffold assigns `ERR_TEST_WINDOW_CONFLICT` and `ERR_TERRITORY_CAPACITY_EXCEEDED` HTTP 422 while PRD §5 says 409 — I followed the PRD (409). Also, the PRD checks only three prerequisites at design time (certification, approved calc, capacity), so inverter-family, firmware-minimum and unit-ceiling rules deliberately fire only on expansion, per §3.3 vs §3.9 and precedence step 14.

## Step 5: Generate unit tests — 2026-09-05T01:41:00.000Z

The suite is complete. Final report:

## Output location
Both directories are at the **task root** (`/home/ubuntu/github/CodingPRD/tasks/task_2790_home_battery_storage_installation_utility_rebate/`), not inside `workspace/`. Nothing under `workspace/implementation/` was created, read or written; `worklog.md` was not touched.

## Files created

`test_helpers/` (3011 lines): `__init__.py` 305, `api_client.py` 555, `api_errors.py` 160, `assertions.py` 184, `constants.py` 122, `factories.py` 545, `fixtures.py` 569, `test_users.py` 106, `types.py` 465.

`test_suite/` (5233 lines): `conftest.py` 76 — queue A: `test_01` 176, `test_02` 239, `test_03` 116, `test_04` 86, `test_05` 124, `test_06` 253, `test_07` 250, `test_08` 136, `test_09` 264, `test_10` 215, `test_11` 169, `test_12` 104 — queue B: `test_20_entity_shapes` 441, `test_21_state_machine_edges` 325, `test_22_calculation_corners` 280, `test_23_validation_gates` 216, `test_24_endpoint_contracts` 260, `test_25_error_catalogue` 401, `test_26_error_gates` 454, `test_27_rbac` 312, `test_28_concurrency_and_layers` 264, `test_29_consistency` 72.

## Counts and verification
- **101 tests** collected cleanly by pytest (`--collect-only`, 0.48 s, no server needed), 101 `Design:` tags — one per test, none untagged, none dual-tagged.
- **Queue A: 23 of 23 LIVE instances -> 46 tests.** **Queue B: 54 of 54 LIVE instances -> 55 tests** (the `export_commitment_flag...` validations instance is a two-arm claim and needed two tests). All 9 corner sections covered: entities 11, state_machines 8, calculations 5, validations 3, endpoints 5, errors 13, rbac 5, cross_cutting_complexity_layers 3, consistency_model 1.
- **Zero instances skipped.** Every LIVE instance passed the PRD-first two-condition filter. The 32 corner instances carrying `excluded_because` were not translated and no stub was touched (machine-verified).
- **Citations:** all 101 tests' `PRD <section>: "..."` lines verified as verbatim substrings of `workspace/PRD.md` (0 failures). No occurrence of "scaffold" or design-file references anywhere in generated code. `pyflakes` clean across both directories; all modules `py_compile` and import.

## Substitutions where the recipe contradicted the PRD (assertions weakened nowhere)
1. `uncertified_installer_design_creation_rejected` — recipe's `PWX_D` model and client-set `certification_status: SUSPENDED` are impossible (§2.11 catalog is closed; §3.1 "the transition to `SUSPENDED` is never a client decision"). Substituted: an installer certified for `[PWX_A]` only asked for a `PWX_B` design, and a second arm whose expiry is amended to `2026-07-31` (before the clock epoch, exclusive bound). Both yield `ERR_INSTALLER_NOT_CERTIFIED`.
2. `each_of_the_six_roles_...` — recipe posts `certification_level: MASTER`; §3.1 closes the enum to `NONE|CERTIFIED|ADVANCED`, so the amendment demotes to `CERTIFIED`.
3. `installer_acting_on_another_installers_system...` — only the permit-submit trigger is emitted; the `POST /commissioning-tests` trigger names its parent in the **body**, and §2.1 scopes ownership to "requests that name an existing resource in the path", so `ERR_NOT_RESOURCE_OWNER` is not uniquely derivable there.
4. `grant_pto_by_the_reviewer_who_approved...` — the bank is commissioned and the clock advanced first; with a merely INSTALLED bank a tier-6 state error would pre-empt the tier-8 segregation error the instance is about.
5. `submitting_a_voided_claim...` — the project is fully finished (commissioned, PTO, warranty ACTIVE) before the probe so VOID is the only possible objection.
6. `settle_report_delivery_and_file_claim_from_dead_states...` — trigger order rearranged (second delivery report before settlement; warranty registered inside its 30-day window before the file-claim probe) so each 409 isolates one defect; all four end-state assertions kept verbatim.
7. `expansion_with_wrong_gateway_old_firmware_or_too_many_units...` — base is a PTO-granted project, since §3.8 requires COMMISSIONED **and** PTO_GRANTED.

## Non-derivable assertions replaced (never dropped silently)
Absolute `version == N` assertions from the recipes were replaced everywhere with relative ones (`after == before + 1`, or unchanged-after-a-refused-write), because §2.5 declares only that `version` "increases by exactly one on every mutation" and never states the opening value. This affected the entity-shape, permit-issue, program round-trip, alert-acknowledge, participation, capacity-commitment-bounds, expansion-triad, stale-version and consistency tests. `assert_created_record` is deliberately unused in queue B for the same reason. One recipe assertion ("no Site row exists") was dropped because §4 declares no `GET /sites` list endpoint, and a non-derivable `net_payment_cents == 0` on a cancelled performance was dropped.

**Orchestrator post-step verification:** `test_helpers/` and `test_suite/` are both at the task root with no stray copies under `workspace/` (checked via `find workspace -type d -name 'test_*'`); 22 `test_*.py` files carry 101 `Design:` tags; only one `worklog.md` exists in the tree (no cwd-drift stray).

## Step 7: Run tests and iterate — 2026-09-05T01:12:00.000Z

Clean 8-round sweep achieved. All 8 parallel rounds: **101/101 passed, 0 failed, 0 errors, 0 skipped.**

## Summary

**Iterations run:** 2

**Tests deleted:** none. No test failed PRD coverage or unique-derivability — the entire failure population traced to one upstream fixture bug.

**Fixes applied to `test_helpers/`:**
- `test_helpers/factories.py` — `installer_payload()`, `certification_amendment_payload()`, `permit_issue_payload()`: date-only datetime literals (`"2027-06-30"`, `"2028-06-30"`) replaced with full ISO-8601 UTC instants with three fractional digits (`"2027-06-30T00:00:00.000Z"` etc.). PRD §2.5 states verbatim: *"All datetime values — inputs and outputs alike — are ISO 8601 UTC with three fractional digits."* A bare calendar date is not an instant, so the PRD-faithful implementation correctly rejected it with `ERR_INVALID_REQUEST`.
- `test_helpers/fixtures.py` — the permit-issuing fixture's `expires_on` default, same correction.

**Fixes applied to `test_suite/`** (same class of fixture-literal bug, in tests that construct their own datetimes inline):
- `test_03_permit_lifecycle.py` — the `expires_on` argument and the corresponding round-trip equality assertion, updated to the canonical instant form the server echoes back.
- `test_21_state_machine_edges.py` — module constant `PERMIT_EXPIRY`.
- `test_26_error_gates.py` — module constant `LAPSED_EXPIRY` (still strictly before the logical clock's `2026-08-01T00:00:00Z` origin, so it remains the lapsed-certification case PRD §3.1 describes).
- `test_07_validation_precedence.py` — an inline permit `expires_on`.

**Fixes applied to `implementation/`:** none. The implementation was already PRD-faithful; its `shape.py::Payload.iso()` rejection of date-only strings is exactly the §2.5 rule, and per the cardinal rules I did not weaken it to accommodate the malformed fixtures.

**Key finding for feedback:** 98 of 101 tests failed identically (`Setup step failed with HTTP 400: ERR_INVALID_REQUEST - Field 'certification_expires_on' must be an ISO 8601 UTC instant`) because installer creation is the root of nearly every fixture chain. This is the classic single-upstream-fixture-bug-masquerading-as-many-implementation-bugs pattern; the unit-test-generator emitted date-only strings for fields PRD calls "instants".

Note: the eight `results.N.json` files from the final sweep remain in `workspace/implementation/` (that path is fixed by the sweep command shape) — remove them if the implementation directory is meant to ship clean.

**Orchestrator independent verification (per the known "subagent claims a clean sweep" hazard):** all 8 `results.N.json` files exist and each reports `101/101 passed, 0 failed, 0 errors, 0 skipped`; the final sweep completed at 01:08 UTC with a 184.3 s per-round duration. `test_suite/` still holds 101 `def test_` functions and 101 `Design:` tags, matching Step 5's output exactly — confirming the zero-deletions claim.

**Step 8 skip decision:** NOT skipped. Step 7 ran 2 iterations with 0 deletions and 0 `implementation/` fixes but non-zero `test_helpers/` and `test_suite/` fixes, so the skill's skip condition (zero of all four categories) is not met. Step 8 runs; a byte-identical `PRD_FINALIZED.md` would be a legitimate outcome here, since every Step 7 fix was a fixture-literal bug rather than a PRD silence or PRD/impl mismatch.

## Step 8: Finalize PRD — 2026-09-05T01:17:00.000Z

`PRD_FINALIZED.md` is written. One edit, in §2.5.

## Line counts
- `PRD.md`: 490 lines; `PRD_FINALIZED.md`: 490 lines. 1 line revised -> **0% line delta, 1/490 lines changed (0.2%)**.

## Changes
- **§2.5 (Common Resource Properties and the Logical Clock)** — *revise* — Split the sentence "All datetime values — inputs and outputs alike — are ISO 8601 UTC with three fractional digits." into an output rule plus an explicit input-acceptance rule: a caller-supplied datetime must be a complete instant (calendar date **plus** a time of day to the second, fractional seconds and a trailing `Z`/numeric UTC offset both optional), is normalized to the canonical three-fractional-digit UTC form before being stored/compared/echoed, and a date-only value (or any unparseable instant) is `ERR_INVALID_REQUEST` under §2.4. — `implementation/shape.py:79-87` (`Payload.iso`), `implementation/common.py:69-72` (`_ISO_RE`), `implementation/common.py:104-125` (`fmt_iso`/`normalize_iso`).

Rationale: the original sentence was simultaneously too strict and too silent relative to the impl. Read strictly ("three fractional digits" applies to inputs), it would make the impl's acceptance of `2026-08-10T17:00:00Z` a mismatch — yet that form is accepted everywhere and is what the fixtures use to drive the clock. Read loosely, §2.4's closed enumeration of malformed-payload conditions never mentions datetime format at all, so a fresh implementer could easily accept `"2027-06-30"` (Python's `fromisoformat` does) where this impl returns 400. That gap is exactly what produced the 98-test wipeout traced in `<step_7_diff>`, and it is the only PRD-silence the diff reveals.

## Pre-edit search log

**Edit 1 — §2.5 datetime input rule**
- **(a) Subject identified:** the accepted form of any caller-supplied datetime value, the error it raises when malformed, and the form in which it is subsequently stored/echoed.
- **(b) Impl paths enumerated** (grep for `\.iso(|parse_iso|normalize_iso|fmt_iso|to_iso8601|wall_now_iso|window_start|window_end` across all of `implementation/`, then read):
  - `shape.py:79-87` `Payload.iso` — the single input gate: non-string or unparseable -> `invalid(...)` = `ERR_INVALID_REQUEST`; otherwise returns `normalize_iso(value)`.
  - `common.py:69-101` `parse_iso` / `_ISO_RE` — requires `YYYY-MM-DD`, a `T`/`t`/space separator and `HH:MM:SS`; fractional part optional and any width; zone optional (`Z`/`z`/`±HH:MM`/`±HHMM`), absent zone treated as UTC, offsets converted to UTC; invalid calendar dates -> `None`.
  - `common.py:104-125` `fmt_iso` / `normalize_iso` — canonical `...T..:..:...mmmZ` output.
  - All five `payload.iso` callsites, confirming the rule is universal and not local to the Step 7 site: `routes/core.py:35` (installer creation `certification_expires_on`, required), `routes/core.py:76` (certification amendment `certification_expires_on`, optional), `routes/core.py:148` (`/_clock/set_current_utc` `to_iso8601`, and `store.set_clock` stores the normalized value), `routes/permits.py:111` (permit review `expires_on`, optional, `ISSUE`-required, then `clock_before` check).
  - `shape.py:232-238` `window()` — `window_start`/`window_end` also go through `Payload.iso`, covering `routes/tests.py:39` (commissioning tests) and `routes/byod.py:180` (dispatch events); the strict-ordering check runs on the parsed values.
  - `store.py:65-82`, `store.py:115-134` — no route stores a raw body datetime string; `view()` passes the already-normalized string through unchanged. Grepped the routes for any `payload.str_/raw/enum` used for a datetime field: none.
  - `rules.py:22-37,82-118`, `common.py:133-148` — every temporal comparison (`clock_before`, `clock_reached`, window conflict, `plus_days`) re-parses the stored normalized string, so normalization is comparison-safe.
  - `envelope.py:17,74` + `store.py:66,80` — emitted `api_request_timestamp`, `created_at`, `updated_at` all come from `fmt_iso`, so "all datetime values the server emits are ... three fractional digits" stays true.
- **(c) Wording adjustments made:** (i) narrowed the three-fractional-digit claim to values the server *emits*, because the impl accepts 0-or-more fractional digits on input — the unrevised universal claim would have contradicted `routes/core.py:148` as exercised by `fixtures.advance_clock("...T17:00:00Z")`; (ii) deliberately left the date/time **separator** and case-sensitivity unspecified (impl also accepts `t` and a space) rather than writing "a `T` separator", per the prefer-under-determined guidance; (iii) said "to the second" rather than "optionally to the second", since `_ISO_RE` makes `HH:MM:SS` mandatory; (iv) said "optionally carrying a trailing `Z` or a numeric UTC offset" rather than "must be UTC", since a zoneless value is accepted and offsets are converted; (v) phrased the rejection as "is a malformed request under §2.4" instead of adding a new clause to §2.4's enumeration, keeping the edit to one sentence and leaving §2.12 step-5 precedence (shape before state, which `routes/permits.py:109-120` follows) untouched.

I deliberately did **not** edit two adjacent things the diff does not trace to: the impl's acceptance of an already-lapsed `certification_expires_on` on amendment (`routes/core.py:76-83`, asserted by a pre-existing test_26 assertion Step 7 did not touch), and `created_at`/`updated_at` being stamped from wall time rather than the logical clock (`store.py:66,80`) — §2.5 already enumerates the logical-clock-stamped fields and excludes both.

**Orchestrator note on Step 9 execution shape:** the implementation is 3807 lines across 20 modules, which is too large for one subagent to scan exhaustively without truncating its own output. Step 9 will therefore run as **three sequential passes over the same `PRD_COMPLETED.md`**, partitioned by implementation module (pass 1 = infrastructure + core/loadcalc/permits routes and performs the `cp` from `PRD_FINALIZED.md`; pass 2 = calc/rules/cascades + systems/interconnection/tests routes; pass 3 = incentives/alerts/byod routes). Passes 2 and 3 must NOT re-copy the file, or they would discard the previous pass's work.

## Step 9: Complete PRD — 2026-09-05T01:47:00.000Z

Run as **three sequential module-partitioned passes over one shared `PRD_COMPLETED.md`**, because the 3807-line / 20-module implementation is too large for a single subagent to scan exhaustively without truncating. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edited in place and were explicitly forbidden from re-copying. Final total: **61 edits** (20 + 23 + 18) — 47 ambiguity-pins, 16 mismatch-revisions — landing on 60 changed lines with zero line-count growth (all in-paragraph inserts/revisions, no new sections).

### Pass 1 — infrastructure + core/loadcalc/permits (`app.py`, `common.py`, `store.py`, `envelope.py`, `errors.py`, `shape.py`, `security.py`, `routes/core.py`, `routes/loadcalc.py`, `routes/permits.py`)

PRD_FINALIZED.md 490 lines / 97,968 chars -> PRD_COMPLETED.md 490 lines / 105,377 chars (**+7,409 chars**). **17 ambiguity-pins, 5 mismatch-revisions** at 20 sites.

- §2.1 Ownership enforcement — insert — ambiguity — load calculation is the one kind not reached through the bank (Homeowner compares the calc's own `site_id`; installer owners are the `installer_id`s of every system naming it, so an unreferenced calc has no owner and the check is skipped); `Site`/`InstallerAccount` are never installer-owned; list endpoints are never ownership-scoped — `security.py:83-123`
- §2.3 — insert — ambiguity — out-of-range/non-integer `limit`/`offset` -> `ERR_INVALID_REQUEST` 400, empty string -> default, `offset` unbounded — `envelope.py:43-63`
- §2.3 — insert — ambiguity — `created_at` ties broken by insertion order — `store.py:93`
- §2.3 — insert — ambiguity — `total_count` is the pre-paging filtered size; `has_more` = `offset + len(page) < total_count` — `envelope.py:69-78`
- §2.4 — insert — ambiguity — filter values are matched literally and never validated against enums; unmatched -> empty page, not an error — `store.py:96-108`
- §2.4 — insert — ambiguity — absent/unparseable body treated as `{}`; non-object JSON body -> 400; numeric strings and booleans rejected for numbers; integral floats accepted for integers; whitespace-only string counts as empty; unknown path/method return `ERR_INVALID_REQUEST` under **404/405** not 400; trailing slash tolerated — `shape.py:12-19,91-155`, `app.py:39,54-60`
- §2.5 `created_at` bullet — **revise** — **mismatch** — `created_at`/`updated_at` come from real wall-clock time, not the logical clock (PRD's epoch example implied otherwise) — `store.py:66,80`
- §2.5 `updated_at` bullet — insert — ambiguity — equals `created_at` on a new row — `store.py:69-70`
- §2.5 `version` bullet — insert — ambiguity — starts at 1 — `store.py:71`
- §2.5 clock paragraph — insert — ambiguity — `to_iso8601` is required and the only accepted field; clock may move backwards; response is an empty `data` object — `core.py:146-150`
- §2.7 — insert — ambiguity — quantized figures are emitted as JSON numbers, so quantization fixes value not width (`13.50` -> `13.5`, `0.9000` -> `0.9`) — `store.py:115-122`
- §3.1 registration — insert — ambiguity — `certified_model_codes` and `certification_expires_on` must be present even at level `NONE` — `core.py:34-35`
- §3.1 status field — **revise** — **mismatch** — PRD said `SUSPENDED` "is never a client decision"; the amendment endpoint accepts either value — `core.py:77,84-85`
- §3.1 amendment — **revise** — **mismatch** — amendment may write `SUSPENDED`; all four fields optional and an empty amendment still bumps `version`; the empty-list-requires-`NONE` rule is *not* re-applied — `core.py:74-86`
- §3.2 payload — insert — ambiguity — all four VA inputs required and non-negative on every creation (including the measured method that ignores them); `site_id` resolved before the other fields are inspected — `loadcalc.py:40-48`
- §3.2 essential circuits — insert — ambiguity — `has_motor` omitted/null -> false; circuit stored as exactly the three fields (extras discarded); omitted list stored as `[]` not null — `shape.py:206-229`, `loadcalc.py:52`
- §3.2 review cycle — insert — ambiguity — consistency rules checked before the status check; the standard-method prohibition on `measured_peak_kw` is **not** re-checked on submit and a stored value survives a switch to the standard method; `reviewer_notes` untouched by resubmission — `loadcalc.py:50-53,118-127`
- §3.4 permit opening — **revise** — **mismatch** — creation imposes no build-state requirement (a `DESIGN_DRAFT` bank may be permitted); `jurisdiction_code` is a label/filter only, never matched to the reviewing operator — `permits.py:33-58`
- §3.4 permit submission — insert — ambiguity — the `DESIGN_LOCKED`/`INSTALLED` requirement is evaluated only after the permit's own status and only on `DRAFT -> SUBMITTED`; `COMMISSIONED`/`DESIGN_HOLD`/`SUPERSEDED` are rejected there; the corrections resubmission never re-examines the bank — `permits.py:88-96`
- §3.4 permit review — insert — ambiguity — the missing/lapsed `expires_on` objections are `ERR_INVALID_REQUEST` evaluated *before* the permit's status; omitted `inspection_findings` leaves the stored note untouched (unlike inspection-result); `expires_on` validated but unused on `REQUEST_CORRECTIONS` — `permits.py:111-136`
- §3.4 field inspections — insert — ambiguity — no other source state accepts an outcome (repeat `PASS` from `INSPECTION_PASSED`, repeat `FAIL` from `INSPECTION_FAILED`, and pre-issuance states all -> `ERR_PERMIT_STATE_INVALID`); status check precedes the expiry check — `permits.py:148-155`
- §4 endpoint table `POST /permits` — **revise** — **mismatch** — description said "for a design-locked system" — `permits.py:33-58`

Pass 1 cross-checked §3.2's load-sizing formulas against `calc.load_sizing` and believed they already matched, but deferred final say to pass 2 (which owns `calc.py`).

### Pass 2 — calculations/rules/cascades + systems/interconnection/tests (`calc.py`, `rules.py`, `cascades.py`, `routes/systems.py`, `routes/interconnection.py`, `routes/tests.py`)

105,377 -> 116,132 chars (**+10,755**). **15 ambiguity-pins, 8 mismatch-revisions** (23 edits).

- §2.10 — insert — ambiguity — each of the four ledger transfers is a *single* mutation of the program row (version +1 per transfer, no observable un-balanced intermediate) — `rules.py:148-169`
- §2.11 — revise — mismatch — `max_units`/`min_firmware`/gateway family are consulted **only** on the expansion path and by the firmware verdict; an original design accepts any `unit_count >= 1` and any well-formed firmware, and any model/inverter pairing — `routes/systems.py:81-90,297-306`, `calc.py:213`
- §2.12 step 14 — revise — mismatch — on the expansion path the step-10 capacity objection is deferred to after the unit ceiling — `routes/systems.py:297-308`
- §3.3 — insert — ambiguity — `commissioned_at`, `warranty_deadline_at`, `warranty_registered_at`, `warranty_coverage_years`, `serial_numbers` all null at creation — `routes/systems.py:108-114`
- §3.3 — revise — **mismatch** — lock-design re-checks certification -> load-calc -> capacity (PRD had listed calc -> capacity -> certification), and build state precedes all three — `routes/systems.py:150-155`
- §3.3 — insert — mismatch — mark-installed order: build state, permit existence, permit status, **permit expiry, then** grid status — so `ERR_PERMIT_EXPIRED` beats `ERR_SYSTEM_GRID_STATE_INVALID`, contra §2.12's generic order — `routes/systems.py:165-174`
- §3.4 — insert — ambiguity — cascade A hop 2 does not fire (and raises no `ERR_APPLICATION_NOT_FOUND`) when no `APPROVED_TO_INSTALL`/`PTO_GRANTED` application exists; earliest `created_at` wins; hop 3 conditional on the bank's grid status — `cascades.py:55-83`
- §3.4 — insert — ambiguity — cascade A suspends enrollments in ascending `created_at`, participations likewise; a PENDING participation of a settled event is left alone — `cascades.py:13-43`
- §3.5 — insert — ambiguity — filing places no requirement on either status dimension; uniqueness runs after export consistency — `routes/interconnection.py:36-51`
- §3.5 — revise — **mismatch** — submission leaves the bank row **untouched** when its grid status already reads `APPLICATION_SUBMITTED` (PRD had implied a write either way); build gate applies only on the DRAFT edge; `DENIED` gate on both; consistency checked pre-state; overrides written only after all checks pass — `routes/interconnection.py:94-129`
- §3.5 — insert — ambiguity — `approved_export_kw` is never compared to `requested_export_kw` (may exceed it) nor re-checked against `NON_EXPORT`; bank grid set unconditionally — `routes/interconnection.py:141-160`
- §3.5 — revise — mismatch — PTO order is build state -> segregation of duties -> permit inspection — `routes/interconnection.py:178-198`
- §3.6 — insert — ambiguity — booking places no requirement on either status dimension nor on the clock — `routes/tests.py:34-68`
- §3.6 — revise — **mismatch** — the 30-min buffer is a single separation requirement *between* the two windows, not a pad on each side (so >=30 min gap passes, not 60); every other test counts whatever its status; conflict check precedes duplicate check — `rules.py:80-107`, `routes/tests.py:41-51`
- §3.6 — insert — ambiguity — foreign measured fields rejected even when explicitly null; owned figure required & non-negative; **re-recording a RECORDED test answers `ERR_INVALID_REQUEST` (400)**, not a state code; recording is clock-unconstrained — `routes/tests.py:100-127`
- §3.6 — insert — ambiguity — commissioning permit gate: missing permit -> `ERR_PERMIT_NOT_FOUND`; null `expires_on` -> `ERR_PERMIT_EXPIRED` — `routes/systems.py:210-212`
- §3.6 — insert — ambiguity — cascade B tie-break by insertion order; sibling-set semantics mid-cascade; no budget re-test on re-pricing — `cascades.py:100-107`
- §3.6 — insert — ambiguity — cascade B hop 3 is interleaved per claim, not a second pass; a zero difference does not touch the program row — `cascades.py:114-118`
- §3.6 — insert — ambiguity — `coverage_years >= 1`; shape before build state; **registration is repeatable** while COMMISSIONED, overwriting and re-deciding status (and re-incrementing the late counter) — `routes/systems.py:236-262`
- §3.7 — insert — ambiguity — cascade D hops 2+3 share one installer mutation (version +1); threshold is a floor so every clawback past the second repeats hops 3–4 — `cascades.py:139-153`
- §3.8 — revise — mismatch — only the first two §3.3 prerequisites apply at expansion; capacity deferred to the fourth compatibility rule; version check precedes certification — `routes/systems.py:277-308`
- §3.8 — insert — ambiguity — cascade C ordering (ascending `created_at` at both levels); settled-event participations left alone — `cascades.py:125-128`
- §3.9 — insert — ambiguity — territory check counts events of **any** status, samples the new `window_start` plus each overlapping event's start inside the window, equality with 1500 kW passes, and tests a non-overlapping event on its own — `rules.py:110-141`

**§3.2 load-sizing formulas: MATCH — no change made.** Verified line by line against `calc.load_sizing` (`calc.py:47-92`) and the constants in `common.py:300-309`: 3 VA/sqft lighting; 3000 VA at full value with the remainder at 40%; HVAC as `max(heating, cooling)`; `/1000` with a single rounding step; measured method `x 1.25` ignoring all nameplate inputs; whole-home surge `x 1.75`; essential branch ranked by descending `load_kw` with submitted-array order as the tie-break, top-2 total plus 50% of the remainder clamped to the (already-rounded) `connected_load_kw`, motor candidates at `load_kw x 3.0` with `max` (0 when none), and surge = motor surge + 25% of the **already-rounded** `required_continuous_kw`. All exact.

Pass 2 also verified `calc.delivery_figures` and `calc.settlement_money` against §3.9's six settlement steps — arithmetic matches exactly, no edit — and confirmed §3.7's award steps 1–6 and §2.10's stacking prose were already consistent with `calc.py`.

### Pass 3 — incentives/alerts/byod (`routes/incentives.py`, `routes/alerts.py`, `routes/byod.py`)

116,132 -> 121,376 chars (**+5,244**). **15 ambiguity-pins, 3 mismatch-revisions** (18 edits).

- §2.10 — insert — ambiguity — a **zero-cent** encumbrance/release/disbursement/reversal is still performed as a mutation and still advances the program's `version`; sole exception is cascade B's zero-difference correction — `rules.py:160-178`, call sites `incentives.py:208,290,316,337,361`
- §3.7 (reserve) — revise — **mismatch** — build-dimension failure raises `ERR_SYSTEM_BUILD_STATE_INVALID` (not `ERR_SYSTEM_GRID_STATE_INVALID`), and it precedes the version check while the grid gate follows it — `incentives.py:126-142`
- §3.7 (reserve payload) — insert — ambiguity — `capacity_commitment_kw` must be strictly > 0 as a **shape** rule (`ERR_INVALID_REQUEST`, not `ERR_CAPACITY_COMMITMENT_INVALID`) — `incentives.py:121`
- §3.7 (export commitment) — insert — ambiguity — the `export_mode` read is the bank's live (non-`DENIED`, latest `created_at`) application; **no** live application also yields `ERR_EXPORT_COMMITMENT_REQUIRED`, not `ERR_APPLICATION_NOT_FOUND` — `incentives.py:36-45,156-164`
- §3.7 (reservation writes) — insert — ambiguity — claim opens `RESERVED` with `basis_kwh_final`, `final_amount_cents`, `approved_by_user_id`, `paid_by_user_id`, `paid_at`, `clawback_reason` all null — `incentives.py:189-207`
- §3.7 (submit) — insert — ambiguity — claim's own `RESERVED` state checked first, then the three bank conditions with codes `ERR_SYSTEM_BUILD_STATE_INVALID` / `ERR_SYSTEM_GRID_STATE_INVALID` / `ERR_WARRANTY_NOT_ACTIVE` — `incentives.py:240-258`
- §3.7 (decision) — insert — ambiguity — un-priced-claim approval objection is `ERR_CLAIM_STATE_INVALID`, after the `SUBMITTED` check and only on `APPROVE` — `incentives.py:274-278`
- §3.7 (void) — insert — ambiguity — `reason` is required and non-empty — `incentives.py:349`
- §3.7 (clawback) — insert — ambiguity — `clawback_reason` is required and non-empty — `incentives.py:325`
- §3.8 (alert creation) — insert — **mismatch** — bank is a body FK so no ownership check: **any** `CertifiedInstaller` may raise an alert against any bank, in any build/grid state — `alerts.py:34-43`
- §3.8 (file-claim) — insert — ambiguity — `claimed_component` required non-empty; omitted `resolution_notes` **leave the stored note untouched** (unlike review), empty string accepted — `alerts.py:98-110`
- §3.9 (enrollment) — insert — ambiguity — zero pledge / over-cap pledge / >50 floor are `ERR_PLEDGE_EXCEEDS_CAPACITY`, but negative or fractional inputs are `ERR_INVALID_REQUEST`; `reserve_soc_pct` is an integer — `byod.py:62-63,83-91`
- §3.9 (consent) — insert — ambiguity — grid objection is `ERR_SYSTEM_GRID_STATE_INVALID`, after the `PENDING_CONSENT` check, build dimension not re-examined — `byod.py:136-144`
- §3.9 (withdraw) — insert — ambiguity — `reason` accepted (empty string included) and discarded — `byod.py:157-158`
- §3.9 (participation) — insert — ambiguity — the eight delivery/money fields open null — `byod.py:255-271`
- §3.9 (participation) — insert — ambiguity — a `CANCELLED` participation still blocks re-call (`ERR_PARTICIPATION_DUPLICATE` spans all statuses) — `byod.py:244-252`
- §3.9 (report-delivery) — insert — ambiguity — fixed order participation-state -> event-`SCHEDULED` (`ERR_EVENT_STATE_INVALID`) -> window-closed (`ERR_PERFORMANCE_STATE_INVALID`); zero `delivered_kwh` accepted — `byod.py:306-320`
- §3.9 (settle) — insert — ambiguity — premature settlement is `ERR_EVENT_STATE_INVALID`; the `REPORTED` sweep is a complete pre-pass so a blocked settlement writes nothing — `byod.py:334-350`
- §3.9 step 6 — revise — **mismatch** — steps 3+6 share one enrollment mutation (version +1 per participation, written after the participation row); the event row is written **once** at the end with the summed total (version +1 for the whole settlement) — `byod.py:352-377`

### Orchestrator final verification

- `PRD.md` 490 lines / 97,461 chars; `PRD_FINALIZED.md` 490 lines / 97,968 chars; `PRD_COMPLETED.md` 490 lines / **121,376 chars** (+23,408 over PRD_FINALIZED, +23,915 over PRD.md).
- `PRD_COMPLETED.md` is **not** byte-identical to either `PRD_FINALIZED.md` or `PRD.md` (`cmp` confirms both), so the scan provably ran — 60 changed lines.
- Structure intact: 5 top-level sections (§1 L3, §2 L11, §3 L190, §4 L356, §5 L428), §4 endpoint table exactly **65** method rows, §5 error table exactly **57** `ERR_` rows, file ends on a complete §5 table row.
- `grep -in "harder than expert|SCAFFOLD|test_recipe|Design:"` over `PRD_COMPLETED.md`: clean — neither the difficulty directive nor any design-index or test-tag vocabulary leaked into the final artifact.
- Steps 8 and 9 touched no code, so the Step 7 sweep result (8/8 rounds at 101/101) remains the standing verification of `implementation/` against `test_suite/`.

**Pipeline complete.**
