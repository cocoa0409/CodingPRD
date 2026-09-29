# Worklog — task_2891_game_development_milestone_publisher_funding

## Step 1: Create task directory — 2026-09-05T12:27:58.292050206Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2891_game_development_milestone_publisher_funding and its workspace/ subdirectory. Index 2891 pre-assigned by the orchestrating caller; no scan of ./tasks/ performed.


## Step 2: Generate scaffold — 2026-09-05T14:09:46.145623757Z

Scaffold generation for task 2891 is complete and lint-clean.

**Verdict block (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2891_game_development_milestone_publisher_funding/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2891_game_development_milestone_publisher_funding/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2891_game_development_milestone_publisher_funding/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    48
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     53
  Calls scanned (§1.8+§1.9):  829

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2891_game_development_milestone_publisher_funding/`):
- `SCAFFOLD.yaml` — 3014 lines (§1.0–§1.7 only; no `scaffold_*_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1710 lines (single top key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3912 lines (single top key `scaffold_corner_design`)

`worklog.md` (6 lines) and `workspace/` untouched.

**Scaffold counts:** 12 entities, 48 endpoints, 8 state machines, 2 OCC concurrency rules (`POST /change-orders`, `POST /royalty-statements`, both `expected_agreement_version`), 11 calculations, 69 ordered validations, 67 errors, 4 roles (`segregation_of_duties`, flat topology, cyclic state machines, `immediate` consistency, integer cents / `round_half_up`).

**§1.8:** 9 difficulty rules × 2 instances = 18 (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).

**§1.9:** all nine claim-extraction-guide sections, 70 instances = 53 full recipes + 17 `excluded_because` stubs citing §1.8 — entities 12, state_machines 15 (5 stubs), calculations 13 (7), validations 9 (2), endpoints 5 (1), errors 6, rbac 4, cross_cutting_complexity_layers 5 (2), consistency_model 1. All 67 §1.6 error codes now have a trigger in one of the two design files (verified by script); the last gaps closed this session were the auth/RBAC preamble ladder (MISSING_AUTH_HEADERS → UNKNOWN_ROLE → ACTOR_NOT_FOUND → ROLE_NOT_PERMITTED → ROLE_FUNCTION_MISMATCH), NOT_AGREEMENT_PARTY, the ten path-scoped 404s, the milestone/build, engagement/invoice, change-order-cap, statement-period and cure-round code families, both OCC 412s and the 30%-posture threshold.

Two consistency fixes made to `SCAFFOLD.yaml` while designing §1.9:
- `MilestonePayment` authorize precondition changed to `acting PublisherUser.function IN {FINANCE, DUAL}` (it said `== FINANCE`, which contradicted the DUAL enum plus priority-5 rule that make ERR_SEGREGATION_OF_DUTIES reachable at all).
- Earlier: DRAFT→ACTIVE cascade step 2 reworded as vacuous-at-first-activation, `PublisherUser.function` enum extended with `DUAL`, and validation priority 5 relaxed accordingly.

One item for you to decide: `SCAFFOLD.yaml` line 2 of the `scenario:` key still carries the literal directive `Generate task harder than expert level!` (kept because the scenario was to be stored verbatim). Per the known pipeline hazard this line propagates into PRD.md, so strip that single line before Step 3 if you want it gone; the rest of the scenario text is the domain description and should stay.

**Orchestrator action after Step 2:** stripped the `Generate task harder than expert level!` directive line (plus its blank line) from the `scenario:` block of SCAFFOLD.yaml so the difficulty directive cannot leak into PRD.md. SCAFFOLD.yaml is now 3012 lines; `grep -c "harder than expert"` returns 0 across all three scaffold files.

## Step 3: Copy shared files — 2026-09-05T14:09:50.675134940Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md (bash only, no subagent).

## Step 4: Generate PRD — 2026-09-05T14:28:31.000Z

PRD generation is complete.

## Output
`workspace/PRD.md` — **482 lines, 14,435 words, 104,891 bytes**. Only that file was created; `worklog.md`, `SCAFFOLD*.yaml` and `INSTRUCTION.md` were not touched. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` nor any sibling task directory was opened.

## Top-level sections (from `grep -n '^#'`)
- `# Game Milestone Publisher Funding API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 RBAC · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and the Logical Clock · 2.5 Money, Basis Points and Percentages · 2.6 The Agreement Funding Ledger · 2.7 Agreement-Version Freshness · 2.8 Cascade Discipline · 2.9 Reverse-Lookup Reads and Path Resolution Order · 2.10 Rule Precedence · 2.11 Segregation of Duties (11 subsections, in the 8–12 band)
- `## 3. Business Logic & Workflows` — 3.1 Parties, Operators and Deal Formation · 3.2 Milestones, Dependencies and Activation · 3.3 Freezing and Unfreezing · 3.4 Build Delivery and the Acceptance Gate · 3.5 The Publisher Verdict · 3.6 Authorizing Milestone Payments · 3.7 Scope Change Management · 3.8 Outsourcing, Vendor Cooldown and Invoices · 3.9 Revenue, Recoupment, Termination and Post-Launch (9 subsections, in the 5–9 band)
- `## 4. Endpoint Definitions` — status-code paragraph + 4-column table
- `## 5. Error Code Catalogue` — 2-column table

## Coverage
- **Entities:** all 12 (Studio, Publisher, PublisherUser, DevelopmentAgreement, Milestone, MilestoneBuild, PublisherReview, MilestonePayment, ChangeOrder, ContractorEngagement, ContractorInvoice, RoyaltyStatement).
- **Endpoints:** all 48 rows verified programmatically against the scaffold — method+path sets match exactly (0 missing, 0 extra), and the Authorized Role(s) column matches every endpoint's `roles` list (0 mismatches). Paths use the scaffold's literal `{id}` segment (29 parameterised paths, matching the scaffold's 29).
- **State machines:** all 8, all 44 transitions with preconditions and side effects, including the system-initiated ones (suspension/reinstatement/termination/cure-sweep cascades, `SUPERSEDED` supersession of drafts and change orders, `TERMINATED_EARLY`, `VOIDED`, the `ACTIVE → COMPLETED` auto-transition).
- **Calculations:** all 11 (build_gate_evaluation, royalty_settlement PROVISIONAL/FINAL, payment_disbursement, contractor_budget_utilization COMMITTED/INCURRED, agreement_funding_ledger, ship_date_schedule, cure_window, ip_reversion_scope, live_ops_draw_allowance, reviewer_window_occupancy, vendor_cooldown_occupancy) with every constant, threshold and rounding position stated — including the pinned contrast between the provisional per-line rounding and the final single cumulative rounding.
- **Validations:** all 69 rendered as an explicit total order in §2.10, with the four conflict-pair notes.
- **Errors:** all 67 IDs with HTTP statuses (67 table rows).

## Hard Contract reports
- **Field-Name Coverage: PASS.** Required set computed twice independently (once pre-cached, once re-derived from `entities[].fields[].name` + `endpoints[].input`): 115 unique names both times, **0 missing** from backticked tokens in the PRD. Nested `revenue_lines` member names (`platform_code`, `gross_cents`, `returns_cents`) are also backticked.
- **Rule Coverage: PASS.** All 67 error IDs present; all 69 validation error IDs present inside the §2.10 numbered list (69 numbered items); all state-machine states present; all calculation numeric constants present (the three `readiness_score` weights were initially spelled in words and were rewritten as 0.45 / 0.35 / 0.20); no pseudocode residue (`>=`, `==`, `min(`, `round_half_up(` etc. all absent); no fuzzy filler (`etc.`, `as appropriate`, `reasonable`, `approximately` all absent).
- **§3 Path Purity: PASS.** 833 backtick tokens (240 unique) scanned in §3: **0** begin with `/`, **0** are a bare HTTP method, **0** combine method+path; no bare unbackticked path-like text either.
- §2.2 confirmed **byte-identical** to `skills/prd-bench-doc-generator/section-2.2-response-structure.md`.

## Truncation guard
The file ends at a complete section boundary — the final row of the §5 error table, with no audit footer. Last 3 lines verbatim:

```
| `ERR_REVIEWER_WINDOW_CONFLICT` | 409 |
| `ERR_VENDOR_COOLDOWN_CONFLICT` | 409 |
| `ERR_PERIOD_OUT_OF_ORDER` | 422 |
```

Two scaffold ambiguities were resolved explicitly rather than left vague: change-order approval (rule 37 admits `UNDER_REVIEW` targets but the approval transitions do not — an approval aimed at an `UNDER_REVIEW` target is mapped to `ERR_MILESTONE_NOT_AMENDABLE`, declines stay available for all four states), and build submission against a still-`DEFINED` milestone (necessarily awaiting a predecessor, so reported as `ERR_DEPENDENCY_NOT_ACCEPTED`).

**Orchestrator truncation re-verification:** independently confirmed — 482 lines, sections 1/2/3/4/5 all present, tail is three complete error-table rows ending at `ERR_PERIOD_OUT_OF_ORDER`, and `grep -ci "harder than expert" PRD.md` returns 0 (no difficulty-directive leak).

## Step 6: Generate implementation — 2026-09-05T14:58:57.000Z

Implementation complete. Summary of the work:

## Files written (all under `workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | `set -euo pipefail`, `cd $(dirname $0)`, **guarded** pip install (only when flask is missing, to avoid boot contention across concurrent per-test reboots), `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=3.0.0` |
| `app.py` | 57 | factory, `strict_slashes=False`, ApiError/404/405/catch-all handlers, `0.0.0.0:$PORT` (default 10000), `threaded=True`, no reloader |
| `money.py` | 63 | `Fraction` arithmetic, `round_half_up`, `round_half_up_dp`, `apply_bps` |
| `errors.py` | 91 | all 67 error ids with their HTTP statuses |
| `store.py` | 162 | in-memory dicts only, logical clock pinned to `2026-08-01T00:00:00Z`, instant/date formatting, `stamp_new`/`touch`/`ordered` |
| `envelope.py` | 73 | `meta`/`response_type`/`data`, `req_`+20 uppercase alnum, pagination meta |
| `validation.py` | 197 | rule-6 engine, `parse_float=Decimal`, `paging()` |
| `guards.py` | 235 | rules 1–20: headers, role, actor, function licence, party, all `find_*` and `agreement_of_*` resolvers, `visible()` |
| `ledger.py` | 236 | derived-field recompute, posture, suspension/termination cascades, ship-date recompute, rights settlement, completion |
| `calc.py` | 282 | all 11 calculations |
| `serializers.py` | 234 | per-entity key tuples (Review deliberately has no `updated_at`/`version`) |
| `listing.py` | 20 | filter + pagination helper |
| `routes/__init__.py` | 18 | blueprint registration |
| `routes/registry.py` | 133 | 8 endpoints |
| `routes/agreements.py` | 350 | 10 endpoints |
| `routes/milestones.py` | 261 | 7 endpoints |
| `routes/reviews.py` | 279 | 6 endpoints |
| `routes/changeorders.py` | 224 | 4 endpoints |
| `routes/contractors.py` | 273 | 9 endpoints |
| `routes/royalties.py` | 181 | 4 endpoints |

3380 lines total. No `__pycache__` left behind; no file I/O, no SQLite, no seeding (verified: a fresh boot answers every list endpoint with `total_count: 0`).

## Endpoints: 48 of 48
Verified by dumping `app.url_map` — exactly the 48 paths in the PRD's §1.7 table, no extras.

## Validation precedence
Every route calls the same three-stage prologue in the §2.10 order: `begin(roles)` (rules 1–5), `body(FIELDS)` (rule 6, including conditionally-required fields), then path/body FK resolution (7–19), party (20), OCC (21), state (22–44), authorization-specific (45), fiscal/computed (46–69). The PRD's deliberate inversions are implemented and commented in place: gate 46 above 47/48/49/51; reviewer-overlap 53 above window-wellformedness 54; engagement-invoiceable 38 above invoice-submitted 40 (and on a *decision* rule 38 binds approvals only — reject is always available); uplift-cap 57 → slip 58 → cut-exceeds-funding 67; statement 42 → 43 → 64; outsourcing state 32 above budget 60; reinstate 24 before 68. The three nested list routes (`/milestones/{id}/builds`, `/contractor-engagements/{id}/invoices`, `/development-agreements/{id}/royalty-statements`) call `paging()` before the path lookup so a bad `limit` is a 400, not a 404.

## Calculations
Each formula lives in `calc.py`/`ledger.py` as one function with the PRD's rounding points pinned: payment disbursement runs its four steps with the single rounding in step 3 (tier read off the step-one gross, cure penalty added to the bps before rounding); the provisional royalty rounds per revenue line, the final one rounds once on the cumulative base and uses `advance_disbursed_cents` rather than the unrecouped balance; `accepted_milestone_ratio` is the only 4-dp quantity and is recomputed only at termination/completion. Derived ledger fields are never incremented in place — `recompute_ledger()` rebuilds them from the rows after every mutation.

## Smoke test (port 51891/52891, killed by exact PID; no pkill used)
Boots in ~2s. Exercised end-to-end: registry → agreement (full initialised ledger, defaults 2000/3000 bps) → milestone → activate (v3, `IN_DEVELOPMENT`) → engagement → vendor cooldown conflict → invoice → duplicate number → approval at exactly the 125% tolerance and rejection above it → reject-without-reason → build gate miss and pass (`readiness_score` 74.75) → ACCEPTED review → payment created → `ERR_SEGREGATION_OF_DUTIES` for the accepting reviewer → authorization by a second finance operator (gross/holdback/net) → posture flip to `RESTRICTED` → royalty statement (distributable 3,500,000, recoup 1,000,000, provisional 500,000) → finalize (`RECOUPED`, `royalties_paid_to_date` 500,000) → `ERR_PERIOD_OUT_OF_ORDER`, `ERR_PERIOD_ALREADY_FINALIZED`, `ERR_STALE_AGREEMENT_VERSION`, `ERR_STATEMENT_NOT_DRAFT` → clock set (PlatformAdmin only) → suspend/reinstate/terminate cascade with rights settlement → change-order uplift cap at exactly 2500 bps, supersession, ship-date slip. All responses matched the PRD's expected values and error ids.

Two judgment calls worth flagging: optional free-text inputs the PRD declares but the SCAFFOLD entity lists omit (`memo` on authorize, `release_notes`, `decision_note`, `description`) are echoed on the row; and `cure_days` defaults to 14 on every verdict per the SCAFFOLD's declared default, while `cure_deadline_at` stays null unless the verdict is CONDITIONAL.

## Step 5: Generate unit tests — 2026-09-05T15:38:14.000Z

Test infrastructure and test suite are complete.

## Files written (all at the TASK ROOT)

`test_helpers/` — 1817 lines
`__init__.py` 1, `api_client.py` 296, `api_errors.py` 161, `assertions.py` 241, `constants.py` 109, `factories.py` 296, `fixtures.py` 380, `test_users.py` 77, `types.py` 256

`test_suite/` — 5397 lines: `conftest.py` 58, then test_01 258, test_02 169, test_03 263, test_04 220, test_05 139, test_06 202, test_07 112, test_08 191, test_09 175, test_10 157, test_11 224, test_12 220, test_13 244, test_14 196, test_15 333, test_16 409, test_17 353, test_18 196, test_19 240, test_20 266, test_21 162, test_22 180, test_23 223, test_24 207.

Files added this session: `test_22_party_scoping_and_segregation.py` (segregation-of-duties scoped per milestone; symmetric party isolation), `test_23_optimistic_concurrency.py` (both `expected_agreement_version` writes), `test_24_posture_threshold_and_immediate_consistency.py` (30%-of-pool inclusive flip; acceptance cascade final on the first read).

## Coverage

- **97 tests**, all tagged with exactly one `Design:` line.
- **Queue A (Difficulty §1.8): 18 non-stub instances, 18 translated, 0 skipped.** No stubs exist in that index. 44 tests carry queue-A tags — richer instances were split into 2–3 focused tests each (the tag is repeated across the tests derived from the same instance).
- **Queue B (Corner §1.9): 70 instances, 17 stubs (`excluded_because`), 53 non-stub, 53 translated, 0 skipped** — one test per instance across `entities`, `endpoints`, `errors`, `rbac`, `validations`, `state_machines`, `calculations`, `cross_cutting_complexity_layers`, `consistency_model`.
- Machine-verified 1:1 mapping: 71 non-stub instance names ↔ 71 distinct tags, zero dangling and zero uncovered.

## Audits performed

- **PRD-citation pass**: every double-quoted fragment in every module and test docstring grepped (whitespace-normalised) against `workspace/PRD.md`. Found and fixed 3 near-quotes — a paraphrased reinstatement clause (test_08), a capitalised cooldown clause (test_09), and an invented summary of §2.10 rule 10 (test_11, replaced with the real rule text).
- **Scaffold-citation pass**: no reference to SCAFFOLD/design files anywhere outside the `Design:` tags.
- **AST pass**: zero unused imports in all 25 test files; all files `py_compile` clean; no duplicate/untagged/dual-tagged docstrings.
- **Fixture-correctness sweep**: no money-as-string, no date-only value in an `*_at` field, no whitespace-only auth header (blank tests use `""`), no double-unwrap of the success envelope (the one raw `["data"]` is on `response.json()` for an error-envelope `message` check), distinct `X-User-ID` per owner, instants canonicalised in `api_client`.
- One design assertion was deliberately **not** emitted: in `corner_non_party_actors_cannot_read_or_write_another_agreement` the index asserts `GET /development-agreements` returns an empty list for a foreign developer, but the PRD only says agreements "can be listed and filtered by `studio_id`, by `publisher_id`, or by `status`" and scopes `ERR_NOT_AGREEMENT_PARTY` to "every agreement-scoped read and mutation" — automatic party filtering of the collection is not uniquely derivable, so that one sub-assertion is omitted while the instance's grounded outcomes (three 403s, `latest_build_number` still 0, PlatformAdmin exemption, party 201) are all asserted.

## Location confirmation

`ls -la` confirms `test_helpers/` and `test_suite/` sit directly under the task root alongside `SCAFFOLD*.yaml`, `worklog.md` and `workspace/`. Nothing was written under `workspace/` (only the concurrently-generated `workspace/implementation/` exists there, untouched); `worklog.md`, `PRD.md` and the SCAFFOLD files were not modified; `__pycache__` from the compile check was removed; scratch stayed in `/tmp/task_2891_tests/`. No server was started, so no process was killed.

## Step 7: Run tests and iterate — 2026-09-05T15:59:28.000Z

Clean 8-round sweep achieved. Exactly 3 test_suite files touched; `test_helpers/` and `implementation/` untouched; `worklog.md` never read or written.

## Summary

**Iterations run.**
2 full 8-round parallel sweeps. Iteration 1: 92/97 passing, 5 failures reproducing identically in all 8 rounds (deterministic, not load noise — every round 177s, same 5 names). Iteration 2 after fixes: **97/97 passing in all 8 rounds, 0 failures, 0 errors, 0 skips.**

**Tests deleted (with PRD-silence category).**
None deleted. All 5 failures were resolved under STEP 1c partial-coverage handling — each failing test carried one uncovered assertion inside an otherwise well-covered test, so the uncovered assertion was removed/corrected and every covered assertion retained at full strength.

**Fixes applied to `test_helpers/`.**
None. The failures were not fixture bugs — no shared setup-error cluster appeared.

**Fixes applied to `implementation/`.**
None. In both clusters the implementation was the PRD-faithful reader; the tests asserted values PRD does not uniquely determine. No PRD-required check was weakened and no code was touched (all impl mtimes unchanged).

**Test-suite corrections (4 tests, cluster A — agreement `version` absolutes).**
- `test_suite/test_12_entity_identity_and_integrity.py::test_the_agreement_version_increments_once_per_mutation`
- `test_suite/test_13_agreement_lifecycle_transitions.py::test_activation_promotes_only_the_dependency_free_milestone`, `::test_activation_needs_a_milestone_before_it_needs_exact_funding`, `::test_a_trigger_the_current_state_does_not_admit_is_refused`

All four hardcoded absolute `version` integers measured across a **milestone creation**, silently assuming milestone creation does not bump the agreement's version. PRD does not uniquely determine this: §3.2 says only "Creation immediately recomputes the agreement's `committed_cents` and `available_funding_cents`" and is silent on `version`, while §2.8 states "Any cascade that changes a field on the `DevelopmentAgreement` refreshes that agreement's `updated_at` and increments its `version` by one" — which positively supports the implementation's bump, since the test itself asserts `committed_cents` changed. Two readings are articulable, so the absolute value fails unique derivability. Converted to **relative deltas** against a version read immediately before each mutation, which is *stronger* on the rule the docstrings actually cite (§2.4 "increments by one on each mutation", §2.8 "exactly once per request", and "nothing is written at all" for the two refused-trigger tests) and matches how test_23/test_24 already do it. Genuinely-determined absolutes were kept as-is (creation response `version == 1`; the `hollow` agreement with no milestones).

**Test-suite correction (1 test, cluster B — `accepted_milestone_ratio` value).**
- `test_suite/test_17_endpoint_surfaces.py::test_corner_recoupment_summary_projects_the_authorized_payment_ledger`

Asserted `accepted_milestone_ratio == 1.0` on a `setup_single_alpha` agreement (one ALPHA milestone accepted). PRD §3.9 defines the ratio only inside "Rights settlement is a single threshold calculation, evaluated both at termination and at completion" — and completion requires an accepted **GOLD** milestone, so neither write point fired; §3.1 initialises the field "at 0.0" and §2.6's ledger family excludes it. Decisively, the test's own expectations are self-contradictory under the live-derived reading: it simultaneously asserts `ip_reversion_state: "NONE"`, yet §3.9 couples the ratio and the rights fields into one calculation, so a live 1.0 ratio would have to yield `RETAINED_BY_PUBLISHER`. Replaced the value assertion with a presence + numeric-type check, preserving the §3.9 verbatim payload-field coverage (the field list is the test's stated purpose) and dropping only the undetermined value. Removed the now-dead `assert_ratio_equals` import. The ratio's PRD-named write points remain fully covered by passing tests at termination (test_06, test_14, test_15) and at completion (test_14 asserts 1.0000 on the GOLD path).

**Orchestrator verification of the sweep artifacts:** independently re-read all 8 `workspace/implementation/results.$i.json` (mtime 15:51, same sweep). Every round reports `total: 97, passed: 97, failed: 0, errors: 0, skipped: 0`. `workspace/sweep.log` contains `SWEEP_DONE`. The clean sweep is confirmed, not merely claimed.

## Step 8: Finalize PRD — 2026-09-05T16:07:09.000Z

Done. Both Step 7 clusters traced to real PRD-silence; two substantive edits plus one one-word consistency tweak.

## Line counts
- `PRD.md`: 482 lines / 104,891 bytes
- `PRD_FINALIZED.md`: 482 lines / 105,809 bytes — line count delta 0% (all edits are inline inside existing long paragraph lines); 3 source lines changed of 482 (0.62%), +918 bytes (+0.88%).

## Changes
- **§3.2 (milestone definition paragraph)** — *revise* — appended to "Creation immediately recomputes the agreement's `committed_cents` and `available_funding_cents`" that this also refreshes the agreement's `updated_at` and increments the agreement's `version` by one per §2.8, so a `version` read before a milestone creation is stale afterwards — `implementation/routes/milestones.py:118-119` (`recompute_ledger(agreement); touch(agreement)`), `implementation/store.py:touch`.
- **§3.9 (recoupment-summary sentence)** — *insert* — after the 12-field payload list, stated that the read is a projection of stored state, nothing recomputed at read time, and that `accepted_milestone_ratio`, `ip_reversion_state`, `sequel_rights_holder` read back whatever the rights settlement last wrote — still `0.0`/`NONE`/`PUBLISHER` on an agreement that has neither terminated nor completed, however many milestones are accepted — `implementation/routes/agreements.py:134-158`, `implementation/ledger.py:190-213`.
- **§4 endpoint table, `GET /development-agreements/{id}/recoupment-summary`** — *revise* — "Computes the agreement's…" → "Reports the agreement's stored…", so the table does not contradict the new §3.9 sentence — `implementation/routes/agreements.py:134-158`.

## Per-edit pre-edit search log

**Edit 1 — subject: what bumps `DevelopmentAgreement.version` (specifically on milestone creation).**
(b) Enumerated: `grep` of every `touch(...)` callsite in `implementation/` (46 hits) and cross-checked each agreement-level touch against the PRD sentence that already covers it — `routes/agreements.py:184` activate, `:200` suspend, `:243`, `:293` terminate, `:327`, `:349` live-ops (§3.2/§3.3/§3.9 all say "version increments"), `routes/reviews.py:150` verdict, `:278` payment authorization (§3.5/§3.6), `routes/changeorders.py:119`/`:223` (§3.7), `routes/royalties.py:116`/`:180` (§3.9). Read `store.py:touch`/`stamp_new`, `routes/milestones.py` in full (both `create_milestone` and `submit_build`), `ledger.py:recompute_ledger` (does not touch the agreement row itself), and `routes/contractors.py` (no agreement touch anywhere). `routes/milestones.py:119` is the sole agreement `touch` with no PRD sentence — exactly the Step 7 site.
(c) Adjustment: my first draft also asserted "Submitting a build does not touch the agreement's `version`." That is true of `submit_build` (touches builds + milestone only) but it is an off-site negative claim belonging to §3.4, so I removed it to stay inside the Step 7 scope. Wording kept scoped to "Creation" rather than any general "milestone writes bump the agreement" claim, because build submission and milestone reads do not.

**Edit 2 — subject: `accepted_milestone_ratio` (and the rights fields) as served by the recoupment summary.**
(b) Enumerated: `grep -rn "accepted_milestone_ratio"` and `grep -rn "ip_reversion_state|sequel_rights_holder"` over all of `implementation/` — initialisation at `routes/agreements.py:101-103`, the only writes at `ledger.py:200-212` (`settle_rights`), its only two callers (`routes/agreements.py:292` terminate, `ledger.py:235` `evaluate_completion`, itself called from `routes/reviews.py:197`), `ledger.py:190-198` (`accepted_milestone_ratio()` helper — called only from `settle_rights`), `ledger.py:recompute_ledger` (confirmed it never writes the ratio or the rights fields), `serializers.py:43-45` + `_value`/`pick` (the full agreement read serves the same stored value), `routes/agreements.py:134-158` (summary builds its payload straight from `agreement[key]`, no recompute), and `money.py:to_number` (Fraction(0) → JSON `0.0`, so the literal `0.0` in my sentence is exact and matches §3.1's existing wording).
(c) Adjustment: scoped the claim to "That read" instead of writing a global "the ratio is never derived live" rule, since `settle_rights` does derive it live at its two write points; and I verified the ratio/rights trio genuinely have no other writer before naming all three. Follow-on tweak to the §4 table row ("Computes" → "Reports the agreement's stored") was made specifically to avoid the new sentence contradicting existing prose.

No `implementation/`, `test_suite/`, `test_helpers/`, `worklog.md`, or `PRD.md` files were modified.

## Step 9: Complete PRD — 2026-09-05T17:02:33.000Z

Run as **three sequential passes partitioned by implementation module** over one shared `workspace/PRD_COMPLETED.md` (a single-shot full scan is known to leave the file byte-identical). Pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edited in place. Final file: 482 lines / 120,500 bytes vs `PRD_FINALIZED.md` 482 lines / 105,693 bytes — 45 lines differing, +14,807 bytes. Not byte-identical (verified by `cmp`). Total **52 edits: 33 ambiguity-pins, 15 mismatch-revisions** (pass-level counts below).

### Pass 1 — core layer (app, envelope, errors, money, store, validation, guards, listing, serializers)

**File creation confirmed:** `PRD_COMPLETED.md` created with `cp` from `PRD_FINALIZED.md` (which existed; `PRD.md` was not used). Before edits: 482 lines / 105,693 bytes → after: 482 lines / 113,170 bytes (14 in-place line revisions; no new sections). **Counts: 14 ambiguity-pins, 2 mismatch-revisions.**

- §2.1 (RBAC preamble) — insert — ambiguity — `X-User-ID` is trimmed before lookup while `X-User-Role` is compared exactly as sent, so a padded role falls to `ERR_UNKNOWN_ROLE` — guards.py:65-72
- §2.1 (party check) — insert — ambiguity — the party check has nothing to test where no agreement is reached: any authorized role may read any Studio/Publisher/PublisherUser — guards.py:216-217, routes/registry.py:65,83,108
- §2.2 (`api_request_id`) — insert — ambiguity — `req_` plus exactly 20 chars from `A`–`Z`/`0`–`9`; freshly minted per response including errors — envelope.py:13,23-24,27-28
- §2.2 (`api_request_timestamp`) — insert — ambiguity — read from the logical clock, not host time, so calls without a clock move share a timestamp — envelope.py:28, store.py:72-73
- §2.2 (`data`) — insert — ambiguity — every documented field is always present, `null` when unset rather than omitted; nothing outside the set is exposed — serializers.py:185-186
- §2.3 (pagination params) — insert — ambiguity — out-of-range/non-numeric/negative values are `ERR_INVALID_REQUEST` 400; empty string = omitted; `offset` past the end returns an empty array; ties on `created_at` order by write sequence — validation.py:177-197, store.py:160-162
- §2.3 (filters) — insert — ambiguity — filters compare the raw query value against the string form of the row field; undeclared params ignored; entitlement is a silent exclusion (never `ERR_NOT_AGREEMENT_PARTY`), applied before `total_count`; the publisher-operator listing is not agreement-scoped — listing.py:12-20, guards.py:231-235, envelope.py:55-64, routes/registry.py:114-122
- §2.4 (identity) — insert — ambiguity — canonical 36-char hyphenated lowercase UUID; a client-sent `id` is a silently ignored key — store.py:47-49
- §2.4 (instants) — insert — ambiguity — inbound instants are parsed liberally (optional/any-width fraction, `Z` or `±HH:MM` normalised to UTC, case-insensitive `T`/`Z`, trimmed) though rendered at exactly 3 digits — store.py:60-110
- §2.4 (dates) — insert — ambiguity — a client date must be exactly `YYYY-MM-DD` with no time part; an instant where a date is expected is structural — store.py:81,113-131
- §2.5 (rounding) — insert — ambiguity — half up means half away from zero; integer-cent fields serialise as bare JSON integers — money.py:31-40,57-63
- §2.5 (percentages) — insert — ambiguity — body decimals are read as exact decimals, not binary floats; pct/ratio fields serialise as JSON numbers (`87.5`, `100.0`, `0.0`); integers accepted as input; only `readiness_score` and `accepted_milestone_ratio` are quantised — validation.py:49,83-92, money.py:17-28,57-63, serializers.py:175-182
- §2.10 (structural validation) — insert — ambiguity — array minimums and wrong-typed array entries; unparseable/non-object body; absent or empty body read as `{}`; no cross-type coercion and booleans never satisfy int/number; explicit `null` == omitted; length measured raw while non-blank tested after trimming — validation.py:37-54,57-120,148-159
- §2.10 (ignored fields) — revise — mismatch — widened from "fields the server computes or manages" to *any* key the endpoint does not declare — validation.py:148-159
- §4 (intro) — insert — ambiguity — trailing slash is not significant — app.py:19
- §5 (intro) — revise — mismatch — the 400 in the table is for a matched endpoint; `ERR_INVALID_REQUEST` is reused with HTTP 404 for an unmatched path and 405 for a disallowed method, in the ordinary error envelope — app.py:26-43

No route module, `ledger.py` or `calc.py` behavior was audited or edited; the error-id → status table was verified programmatically as an exact 67-for-67 match with `errors.py` and left unchanged.

### Pass 2 — registry / agreements / milestones routes + ledger.py

Before: 482 lines / 113,170 bytes → after: 482 lines / 116,337 bytes. All pass-1 edit markers verified still present. **Counts: 10 ambiguity-pins, 7 mismatch-revisions.**

- §2.6 (Funding Ledger) — revise — mismatch — recomputation-trigger list was incomplete; added running a cure sweep and finalizing a royalty statement — `routes/agreements.py:319,326`, `routes/royalties.py:173`
- §2.9 (Path Resolution Order) — revise — mismatch — PRD claimed the path identifier resolves "before it examines the request body"; every route calls `body()`/`paging()` before `find_*`, so rules 1–6 precede path resolution (rules 7–18) — `routes/agreements.py:191,207,250,334`, `routes/milestones.py:252`
- §2.10 rule 6 — insert — ambiguity — an endpoint declaring no body fields never reads the body, so even an unparseable body is ignored there — `routes/agreements.py:160-166,297-303`
- §2.4 (Logical Clock) — insert — ambiguity — the clock may be set backwards; any valid instant is accepted — `routes/registry.py:132`
- §3.1 (Deal Formation) — insert — ambiguity — agreement creation is party-checked after both FKs resolve: a `PublisherFinance` drafter may only name its own `publisher_id`; `PlatformAdmin` exempt. Also pinned that the ship-date rejection is structural and so precedes FK resolution — `routes/agreements.py:67,73-108`
- §3.2 (Milestones) — insert — ambiguity — only `RESTRICTED` bars fresh scope; a `FROZEN`/`SUSPENDED` agreement still accepts a milestone if funding fits — `routes/milestones.py:77-95`
- §3.2 (Milestones) — revise — ambiguity — milestone filter list gained `gate_profile` — `routes/milestones.py:138-141`
- §4 `GET /milestones` — revise — ambiguity — endpoint row gained `depends_on_milestone_id` filter — `routes/milestones.py:138-141`
- §3.4 (Build Delivery) — revise — mismatch — "a `DEFINED` milestone in an active agreement is *by construction* one whose predecessor has not been accepted" is false: a milestone created post-activation into headroom freed by an approved feature cut is born `DEFINED` with no predecessor and is never promoted — `routes/milestones.py:61,97-120,184-187`
- §3.4 (Build Delivery) — insert — ambiguity — `addressed_condition_indexes` entries are not range-checked at delivery and are stored exactly as sent on any delivery — `routes/milestones.py:57,160-162,210`
- §3.4 (Build Delivery) — revise — ambiguity — the gate note said only "before the cure window"; it in fact outranks the dependency, numbering, condition-coverage and cure-window rules alike — `routes/milestones.py:174-200`
- §3.4 (Build Delivery) — revise — mismatch — transition list omitted `DEFINED → UNDER_REVIEW` — `routes/milestones.py:229`
- §3.3 (Freezing) — insert — ambiguity — the optional `reason` is length-unbounded, validated as a string, and never persisted or echoed; same for reinstate/terminate reasons and a live-ops `memo` — `routes/agreements.py:52,56-57,191,250`
- §3.9 (Termination) — revise — mismatch — termination is not restricted to `ACTIVE`/`SUSPENDED`; the only bar is the terminal rule, so `DRAFT` qualifies too — `routes/agreements.py:254`
- §4 `.../terminate` — revise — mismatch — row narrowed termination to `ACTIVE` or `SUSPENDED` — `routes/agreements.py:254`
- §4 `.../cure-sweep` — revise — mismatch — row said the sweep *terminates* engagements and *withholds* payments; it suspends the agreement, holds `PENDING_AUTHORIZATION` payments and suspends `ACTIVE` engagements — `routes/agreements.py:321-326`, `ledger.py:139-148`
- §3.9 (Live-ops) — insert — ambiguity — the draw creates no resource and answers 200 with the agreement; `amount_cents` declares no bound, so zero/negative is not a structural error and a negative draw reduces `live_ops_drawn_cents` — `routes/agreements.py:54-57,331-350`

Verified-already-pinned (no change needed): `recompute_ledger`'s nine derived fields and posture precedence, `restrict_threshold_cents`, `recompute_ship_date` (from-scratch, `decided_at`→`created_at`→insertion tiebreak), `accepted_milestone_ratio`, `settle_rights` thresholds, `evaluate_completion` gates, `unlock_dependents`/`promote_engagements`/`apply_suspension_consequences`, activation's 22→26→27 ordering and two-step cascade, reinstatement's branch order, termination's four steps, cure-sweep's strict-expiry test, milestone creation's 25→28→29→30→59 ordering and full row defaults, build submission's 23→31→46→47→48→49→51 ordering, all payload field sets, and the `recoupment-summary` projection.

### Pass 3 — reviews / changeorders / contractors / royalties routes + calc.py

Before: 482 lines / 116,337 bytes → after: 482 lines / 120,500 bytes. 45 lines differ from `PRD_FINALIZED.md`; 30 from passes 1+2 (each verified individually present), 15 from pass 3. **Counts: 13 ambiguity-pins, 6 mismatch-revisions.**

- §3.5 — insert — ambiguity — non-`CONDITIONAL` reviews read back `conditions` as `[]` and still record `cure_days` (submitted value, else the same default of 14), so it is never null — routes/reviews.py:73-75,119
- §3.6 — insert — ambiguity — authorization performs no independent check of the milestone's own `status`; no error code exists for one — routes/reviews.py:246-259
- §3.7 — revise — ambiguity — supersession sweep is scoped to the same `agreement_id`; `target_milestone_id` is resolved by id alone and need not belong to the named agreement; party entitlement is judged on the named agreement — routes/changeorders.py:82-84,111-117
- §3.7 — revise — ambiguity — `decision` is the two-value enum `APPROVE`/`DECLINE` (literals were nowhere in the PRD) — routes/changeorders.py:52
- §3.7 Branch A — insert — ambiguity — `content_threshold_relief_pct` sent on an uplift is stored but never applied — routes/changeorders.py:202-209
- §3.7 Branch B — insert — ambiguity — `uplift_cents` may go negative, as far as −`funded_amount_cents` — routes/changeorders.py:190-213
- §3.7 — revise — **mismatch** — listing also narrows by order type — routes/changeorders.py:136-147
- §4 `GET /change-orders` — revise — **mismatch** — row rewritten (see below) — routes/changeorders.py:140,143-145
- §4 `GET /contractor-engagements` — revise — **mismatch** — added the missing `studio_id` filter — routes/contractors.py:125
- §4 `GET /contractor-engagements/{id}/invoices` — revise — ambiguity — added the `status` filter the row omitted — routes/contractors.py:222
- §3.8 — revise — **mismatch** — engagement birth states: dropped `UNDER_REVIEW` (rule 32 makes it unreachable), noted only two birth states arise — routes/contractors.py:59,102
- §3.8 — revise — ambiguity — `decision` is `APPROVE`/`REJECT` here, not the change order's `DECLINE` — routes/contractors.py:53
- §3.8 — insert — ambiguity — none of the six engagement/invoice writes touches an agreement field, so agreement `updated_at`/`version` are untouched, and the milestone is not re-stamped either — routes/contractors.py:62-273
- §3.9 — revise — ambiguity — `platform_code` must be non-blank; line-level breaches are rule-6 `ERR_INVALID_REQUEST`; **normalisation** (see below) — routes/royalties.py:37-61
- §3.9 — insert — ambiguity — a new statement is born `DRAFT` with `finalized_at` and `final_royalty_payable_cents` null — routes/royalties.py:96-105
- §3.9 — revise — **mismatch** — finalization also enforces `ERR_PERIOD_ALREADY_FINALIZED`, gates ordered 42 → 43 → 64 — routes/royalties.py:152-159
- §3.9 — revise — ambiguity — finalized-set ordering gains a third tiebreak (server write order) and is tied to "most recently finalized" in the regression check — routes/royalties.py:65-68, calc.py:264-265
- §3.9 — revise — ambiguity — `final_royalty_payable_cents` is not floored at zero; a negative value claws back `royalties_paid_to_date_cents` — calc.py:277-278, routes/royalties.py:169
- §2.10 rule 43 — revise — **mismatch** — endpoint list widened to "statement creation **and on finalization**" (line 210 already presupposed this) — routes/royalties.py:154-157

**`GET /change-orders` `kind` filter** — pass 2's read was inaccurate: the route *does* implement `kind`, at routes/changeorders.py:143-145, as an alias that exact-matches `order_type`; `order_type` itself is also a filter, via `matches` at line 140. So the reconciliation went the other way rather than deleting the row's filter: §3.7 and the §4 row now state that order type is narrowable under either `order_type` or the alias `kind`, that both compare against the row's `order_type` per §2.3, that they are independent additive filters (supplying both requires both to match), and that either supplied empty is treated as absent.

**`revenue_lines` normalisation** — pinned in §3.9's input paragraph: each accepted line is normalised to exactly `platform_code`, `gross_cents`, `returns_cents`, kept in submitted order, with any further submitted key dropped rather than stored, so a statement always reads its `revenue_lines` back in submitted order with that exact shape (routes/royalties.py:37-61).

**calc.py** needed almost nothing: §3.4 already pinned the gate profiles, both threshold adjustments and their fixed order, the inclusive comparisons and the readiness weights/rounding; §3.5 the cure-day-times-86400 deadline and the strict half-open reviewer window; §3.6 all four disbursement steps with the single rounding; §3.8 the padded closed cooldown intervals and both budget bases; §3.9 both settlement variants' rounding placement and the twelve-line cap. Its only unpinned outputs were the negative final payable and the sort tiebreak, both listed above.

### Orchestrator verification

`cmp` confirms `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (90 diff lines, 45 changed source lines). The file still ends at a real section boundary — the last three rows of the §5 error table, closing on `ERR_PERIOD_OUT_OF_ORDER` — and all 27 `##`-level headings survive. No implementation, test_suite, or test_helpers file was modified by any Step 9 pass, so the clean 8-round sweep recorded in Step 7 (8/8 rounds, 97/97 passing, results.$i.json mtime 15:51) remains valid. Only one `worklog.md` exists in the task tree (no cwd-drift strays under workspace/).

**Pipeline complete.**
