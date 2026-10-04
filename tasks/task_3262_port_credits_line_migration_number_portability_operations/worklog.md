# Worklog — task_3262_port_credits_line_migration_number_portability_operations

## Step 1: Create task directory — 2026-09-30T00:00:00.000Z

Task directory `./tasks/task_3262_port_credits_line_migration_number_portability_operations/` was pre-allocated by the caller and already contained an empty `workspace/`. No new index computed, no other `task_*` directory created (per caller instruction).

## Step 2: Generate scaffold — 2026-09-30T15:30:00.000Z

First attempt aborted with `API Error: Claude's response exceeded the 32000 output token maximum` before writing anything to disk. Relaunched with an explicit output-budget rule (one small file or one small section per message, never two tool calls in one message, `wc -l` verification between appends). Second attempt completed successfully.

Subagent summary, verbatim:

> All three artifacts are complete and the scaffold linter reports a clean verdict.
>
> ## Files written
>
> | Path | Lines |
> |---|---|
> | `SCAFFOLD.yaml` | 1512 |
> | `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1078 |
> | `SCAFFOLD_CORNER_DESIGN.yaml` | 881 |
>
> ## Shape
>
> - **Endpoints: 40** (at the declared ceiling), **entities: 12**, calculations 6, state machines 7, validations 28, error codes 33, roles 5, concurrency rules 2.
> - **§1.8: 9 rules / 19 instances** (≥2 each: dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2).
> - **§1.9: 9 sections / 26 instances** (22 with recipes, 4 `excluded_because:` stubs citing §1.8 instance names).
>
> ## Lint verdict (scaffold_lint.py, pasted verbatim)
>
> ```
> SCAFFOLD §1.8/§1.9 -> §1.5 lint report
> Coverage
>   §1.5 endpoints declared:    40
>   §1.1 entities declared:     12
>   §1.8 instances scanned:     19
>   §1.9 instances scanned:     22
>   Calls scanned (§1.8+§1.9):  324
>
> VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5
> and all §1.1 FKs have reverse-reachability in §1.5.
> ```
>
> ## Design adjudications
>
> - **Archetype**: workflow_orchestration + compliance_audit, layers optimistic_concurrency / cascading_side_effects / dual_variant_calculation / scheduled_deferred_actions / pagination_with_filtering; `flat` topology, `compound` state shape, `peer_roles`.
> - **OCC**: both concurrency rules use `SubscriberLine.version` (the parent the write endpoint actually bumps). `POST /portability/port-requests` takes `expected_subscriber_line_version` because the product lets a new request supersede the line's prior one — a true CREATE-with-supersede race, not a state precondition.
> - **Endpoint budget**: to hold 40 endpoints while keeping every FK reverse-reachable, I merged `PortRejectionEvent` into an embedded `PortRequest.rejections` log, dropped the standalone number-reclamation action (its rule survives as the promotion claw-back), and consolidated several flat reads into sub-resource list reads. Two FKs whose entities the lint could not verify (they are all-`input` entities with no `source: system` field, which the lint's derived-field precondition rejects) were given the literal `FK -> X.id` prefix on fields that could not be reworded, so the lint's (f) check exercises them.
> - **Reachable-but-stubbed**: `MigrationRequest.CANCELLED`, `PromoCreditSchedule.CANCELLED`, and the line-addition `PROVISIONED` step were removed where no declared endpoint could produce them; migration cutover is deliberately two-phase (eligibility sets `requested_cutover_at`, the clock advance drives `CUTOVER_SCHEDULED → CUTOVER_COMPLETE`).
> - **Constants pinned for PRD/test traceability**: promo `BASE_CREDIT_CENTS 20000` / `MONTHLY_BASE_CENTS 1000`; grade values FLAWLESS 60000 / GOOD 42000 / FAIR 24000 / POOR 8000 / BROKEN 0; family tier threshold 5 lines; line ceiling 10; installments floored with the whole remainder on the first installment; proration tier rates 5000/4000/3000/2500 with `CARRY_WEIGHT 0.50`. All §1.8/§1.9 numeric asserts were computed by hand from those constants.
>
> Two caveats worth flagging for the downstream generators: the two `FK ->`-prefixed fields on all-`input` entities are the only place the scaffold asks a reader to accept a provenance reading of the entity table (the lint's derived-field gate has no other path to "clean"), and the ops-run reclamation rule (`ASSIGNED → RECLAIMED`) is declared only as an endpoint side effect rather than as a `SubscriberLine` transition, since `SubscriberLine` carries no state machine of its own.

Orchestrator verification on disk (independent of the subagent report): `wc -l` = 1512 / 1078 / 881; all three parse as valid YAML; top-level keys are as specified (SCAFFOLD.yaml carries `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, errors, roles, endpoints` — no `scaffold_difficulty_design` or `scaffold_corner_design` key; the two design files carry exactly their single required top-level key each). Confirmed entities=12, endpoints=40, state_machines=7, errors=33, roles=5, difficulty instances=19, corner instances=26. No truncation sentinels (`TODO`/`PLACEHOLDER`/`UNFINISHED`/`EOF_SENTINEL`) in any file; each file's tail is intact YAML.

**Risk flag for Step 6**: the endpoint count sits exactly at the 40 ceiling. Prior experience is that >40 endpoints causes the implementation generator to emit a rambling report instead of writing files, so Step 6's on-disk output must be verified file-by-file rather than trusted from its summary.

## Step 3: Copy INSTRUCTION.md — 2026-09-30T16:38:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` (1424 bytes) to `./tasks/task_3262_port_credits_line_migration_number_portability_operations/workspace/INSTRUCTION.md`. Verified present. The build contract is: `bash start.sh` from `./implementation/`, listening on `$PORT` (default 10000), bound to `0.0.0.0`, foreground, responding within 60s.

## Step 4: Generate PRD — 2026-09-30T17:05:00.000Z

Subagent summary, verbatim:

> The PRD is complete. Final verification confirms all hard contracts pass.
>
> ## Summary
>
> **Output:** `workspace/PRD.md` — 337 lines, ~74 KB.
>
> **Section list**
> - **§1 Introduction** — three-paragraph framing (revenue leak → the three commercial programs → number-inventory discipline), mounted under `/portability`.
> - **§2 Global Specifications** — 2.1 RBAC (all 5 roles named, each `identity:` translated: four `opaque`, `Customer` = `entity_backed:Account`), 2.2 verbatim fixed envelope block (byte-identical to `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Logical Clock & Deterministic Scheduling, 2.5 Common Resource Properties (incl. `RejectionCodeCatalog`'s `common_fields: false`), 2.6 Monetary Precision, 2.7 OCC, 2.8 Nested Retrieval, 2.9 Validation Precedence.
> - **§3 Business Logic** — 11 subsections, freely grouped by workflow: bringing a number in; carrier rejections & resubmission; prepaid-to-postpaid migration; switch-credit projection/vesting/clawback; device financing & trade-in grading; underwriting a line addition; the line itself (service/number/tenure); cutover cascade; number reservations; port-out protection; role visibility.
> - **§4 Endpoint Definitions** — 4-column table, 43 rows (all 40 scaffold endpoints plus the 3 GETs listed only under `roles[].shared_operations`, which carry explicit role lists in the scaffold and would otherwise have been unreachable).
> - **§5 Error Code Catalogue** — 2-column table, 33 rows.
>
> **Hard Contract reports**
> ```
> Field coverage check:
> - entities[].fields: 100 required (114 declarations, 14 shared FK/FK-mirror names), 100 present, 0 missing
> - endpoints[].request_body/input: 53 required, 53 present, 0 missing
> - endpoints[].query_params: 0 required, 0 present, 0 missing   (filters limit/offset/subscriber_line_id/case_state are declared instead in the GET /port-protection-cases input list, and all appear in §2.3/§3.11)
> - endpoints[].path_params: 0 required
> Status: PASS
>
> Rule coverage check:
> - validations[] with priority: 28 checked, 28 expressed in prose (§2.9 states the ordering; each condition sits with its workflow; all 33 error_ids appear in §2/§3), 0 missing
> - concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_subscriber_line_version + ERR_STALE_SUBSCRIBER_LINE_VERSION/412 all named), 0 missing
> - state_machines[].transitions: 25 checked, 25 fully expressed (from/to pairs, preconditions, side_effects incl. every hop), 0 missing
> - calculations[]: 6 checked, 6 fully expressed (constants, pinned evaluation/rounding order, variants, input sets), 0 missing
> - validations[] conditions: 28 checked, 28 matchable to error_id in prose, 0 missing
> - endpoints[].side_effects / applies_to: 4 (append-only log, etc.) + 28 applies_to scopes checked, all expressed, 0 missing
> - entities[].fields[] structured content: 114 declarations checked, defaults ("defaults to 12", "defaults to 45 days", "defaults to 500", clock defaults, "stored as null"), sources and initial values stated, 0 missing
> - sibling-branch symmetry: 5 groups checked (port PENDING/REJECTED cancel, migration BLOCKED/APPROVED, protection ACTIVATE/DENY/CLEAR, line-addition APPROVE/DECLINE, promo clawback active/vested), equal prose density, 0 asymmetric
> Status: PASS
>
> Path purity check (§3 only):
> - backtick tokens scanned: 698
> - tokens starting with `/`: 0
> - bare HTTP-method tokens: 0
> - method+path combined tokens: 0
> Status: PASS
> ```
>
> **Scaffold items that were ambiguous and how I adjudicated them**
> 1. **`POST /promo-credit-schedules` OCC vs `ERR_PROMO_WINDOW_OVERLAP`.** Both are 409; the scaffold gives no cross-rule precedence. I stated the OCC rule (priority 26, `ERR_STALE_SUBSCRIBER_LINE_VERSION`, HTTP 412) as the version guard and the window check as the business-temporal check, without asserting an order between them.
> 2. **Resubmission is both gated on `UNPROTECTED` (validation 8) and has a side effect that fires "when `port_protection_status` is `PROTECTED`".** Contradictory on its face. I rendered both statements verbatim from the scaffold rather than adjudicating which branch a real request hits.
> 3. **Three GET endpoints exist only under `roles[].shared_operations`** with no `endpoints[]` row: `GET /portability/port-requests/{id}`, `GET /portability/promo-credit-schedules/{id}`, `GET /portability/trade-in-assessments`. Omitting them would make those role grants dead; I added them to §4 with the roles the scaffold lists.
> 4. **`RejectionCodeCatalog` and section numbering.** It is the one `common_fields: false` entity (id + created_at only) — stated explicitly in §2.5. Also carried §1 intro and §2.1 verbatim from the spec then continued numbering straight (no §2.10+ filler).
>
> No forbidden files were read (no `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, no `SCAFFOLD_CORNER_DESIGN.yaml`, no sibling task directories), and all writes were incremental one-tool-call messages.

Orchestrator verification on disk: `PRD.md` = 336 lines / 73 978 bytes (subagent reported 337 — off-by-one, immaterial); headings run §1 → §2.1–2.9 → §3.1–3.11 → §4 → §5, all present.

**Orchestrator investigation of flagged item 2 (resubmission / port-protection contradiction).** I traced this to its source rather than accepting it. The contradiction is **inherited from the scaffold, not introduced by the PRD**:
- `validations[priority=8]` gates `POST /portability/port-requests/{id}/resubmit` on `port_protection_status == UNPROTECTED` (`ERR_PORT_PROTECTION_ACTIVE`, 403).
- Yet `endpoints["POST /portability/port-requests/{id}/resubmit"].side_effects` declares "sets the attached line's ACTIVE PortProtectionCase.case_state to CLEARED and SubscriberLine.port_protection_status to UNPROTECTED" — a side effect that can only be reachable when protection is ACTIVE, which priority 8 forbids.

PRD.md:123-125 renders both halves faithfully, so PRD and scaffold *agree* — this is a scaffold-internal bug, reported here rather than silently resolved (Key Principle 1). I then checked whether it is load-bearing for the test suite by reading every design-index instance that drives `/resubmit`:
- `Difficulty/priority_pair_validation_conflict/protection_beats_resubmission_cooldown` — line is `PROTECTED`, request in `REJECTED`, expects `ERR_PORT_PROTECTION_ACTIVE`. Hits the gate; the CLEAR branch is never reached. **Clean.**
- `Difficulty/priority_pair_validation_conflict/transfer_pin_beats_resubmission_cooldown` — line explicitly unprotected; hits the PIN gate. **Clean.**
- `Corner/endpoints/port_protection_clear_reopens_resubmitted_request` — resubmits while unprotected, then creates + activates a protection case, then triggers `CLEAR`. The assertion is on the CLEAR resolution (`case_state == CLEARED`, `port_protection_status == UNPROTECTED`), not on resubmit. **Clean.**

Conclusion: the contradiction is **latent, not blocking** — no generated test reaches the contradictory branch, so Step 7 should not stall on it. I deliberately did not patch the PRD, because doing so would make it diverge from the scaffold the tests were generated against. Carried forward as a known latent ambiguity for Steps 7/8/9 to resolve only if it actually surfaces as a failure.

Flagged item 3 (three extra GETs) is permitted by the doc-generator spec, which allows supplementing endpoints that appear in `roles[].shared_operations`; without them those role grants would be dead. Accepted.

## Step 5: Generate unit tests — 2026-09-30T17:14:00.000Z

Subagent summary, verbatim:

> Test infrastructure and suite are complete and verified on disk.
>
> ## What was written
>
> **Stage 1 — `test_helpers/` (1699 lines)**
> - `types.py` (361) — 15 status enums + 12 entity TypedDicts. `RejectionCodeCatalog` has `common_fields: false`, so its TypedDict correctly omits `updated_at` and `version`.
> - `api_client.py` (258) — 43 endpoint methods, all paths prefixed `/portability`.
> - `api_errors.py` (79) — 33 error IDs, status map registered via `set_error_http_status_map`.
> - `assertions.py` (221) — per-entity assertions plus domain invariants (ledger conservation, rejection-count/log agreement, `parent_*_id` mirroring, floored installment, non-negative proration).
> - `constants.py` (67), `factories.py` (132), `test_users.py` (26), `fixtures.py` (526), `__init__.py` (29).
>
> **Stage 2 — `test_suite/` (2573 lines)**
> - `conftest.py` plus 9 test files, numbered simple → complex. **101 tests collected**, zero collection errors.
>
> ## Coverage
>
> | Queue | Instances | Tests |
> |---|---|---|
> | A — Difficulty | 19 non-stub instances | **52** (every instance ≥2; range 2–4; zero shortfalls) |
> | B — Corner | 22 non-stub instances | **49** (every instance ≥1; range 1–3; zero missing) |
>
> All 41 unique `Design:` tags resolve to real yaml `name:` values; no unknown tags; no dual-tagged or untagged tests. The 4 `excluded_because:` stubs correctly carry no test and all four `difficulty_instance` cross-references resolve.
>
> ## Instances skipped
>
> **None.** Every non-stub instance passed the PRD-first two-condition filter — the PRD renders all 28 validations, all 25 transitions, all 6 calculations and all 6 OCC/scheduled behaviours in prose with literal values, so no instance failed coverage or unique derivability.
>
> Two near-misses I deliberately handled without skipping:
> - `Corner/rbac/customer_cannot_submit_a_port_request` — the scaffold's distinguishing aspect ("the CustomerService call on the same request succeeds") is not uniquely derivable, since after a successful PENDING submit the Customer call is then indistinguishable from a `ERR_INVALID_STATE` 409. I asserted only the uniquely-determined part (403 `ERR_UNAUTHORIZED` on a PENDING request). Scaffold claims that don't imply 409 are legitimate under PRD §2.9 priority 2 > priority 7.
> - OCC boundary tests assert errors rather than exact `version` deltas. §2.5 says `version` increments "on every modification … derived fields being recomputed counts as a modification", leaving the delta non-unique across a multi-hop cascade — the original scaffold's `version == 3` would not be uniquely derivable.
>
> ## Fixture-design adjudications
>
> - **No invented setup endpoints.** Every setup call is a PRD §4 row. I dropped the scaffold recipe's `GET /subscriber-lines/{id}/port-requests` as a *capture* mechanism and instead read back via `get_port_request`/`get_line`, which return the same fields without depending on list-shape assumptions. (When the scaffold recipe did use that GET — the routing correction instance — I used the single-resource read and asserted the same values.)
> - **Commit setup corrected against PRD.** Three recipe setups committed a reservation onto a line the recipe had *activated*, i.e. `number_status` ASSIGNED. PRD §3.9 requires the named line's `number_status` be `UNASSIGNED`; I used a not-yet-activated line instead, or converted the assertion into a list-read of `reservation_state`.
> - **Contradictory resubmit branch avoided as instructed.** No test resubmits a PROTECTED line expecting success; `protection_beats_resubmission_cooldown` asserts only the 403 path.
> - **Cited-and-strong** assertions were kept even where the recipe didn't list them (e.g. protection-blocked migration suspends the account, `mdn` releas-as-`RECLAIMED` after ops run), each backed by a verbatim PRD sentence.
>
> ## Verification performed
>
> - `pyflakes` clean on all 20 files (only the expected `__init__.py` re-export warnings).
> - **Verbatim citation sweep**: 120 quoted spans across all 101 docstrings, 0 failures against a whitespace-normalised `grep` of `PRD.md`. Three citations that passed grep but were not rule-bearing for their assertion were replaced.
> - Zero `pytest.mark.skip` / `skipif` / `xfail`; zero mentions of "scaffold" or scaffold section numbers in generated code; every `Design:` tag is the last line of its docstring.
>
> No server was started and no processes were killed, per the process-safety constraint — the suite assumes `API_BASE_URL` is already live, as the runner provides.

Orchestrator verification on disk: `test_helpers/` holds all 9 required modules (__init__, types, api_client, api_errors, assertions, factories, constants, test_users, fixtures) at 1699 lines; `test_suite/` holds conftest.py + 9 test files at 2573 lines; combined 4272 lines. Test-function count = 101 (matches the reported collection count); unique `Design:` tags = 41 (matches 19 difficulty + 22 corner instances). No `__pycache__`-only directories or missing files.

Notable: the subagent independently reached and avoided the same latent resubmit contradiction I flagged in Step 4, and proactively corrected three scaffold recipes whose setup violated PRD §3.9 (`UNASSIGNED` precondition for number reservation) — exactly the fixture-vs-PRD class of bug the pipeline expects to surface in Step 7.

## Step 6: Generate implementation — in progress

Launched alone in its own message, per caller override. ISOLATION RULE restated in the prompt to replace the physical isolation that the skill's concurrent Step 5+6 launch would have provided.

## Step 6: Generate implementation — 2026-09-30T17:36:00.000Z

Second-attempt risk (the 40-endpoint ceiling where prior experience shows impl-gen degrades into a narrative report) did **not** materialize: the subagent wrote 22 small files, largest 367 lines.

Subagent summary, verbatim:

> Implementation complete and verified.
>
> ## Summary
>
> Built a complete Python + Flask implementation of the portability operations API at `workspace/implementation/`, written incrementally one file per message (largest file 367 lines, well under the 400-line cap).
>
> ### File list (`find implementation -type f | sort`)
> ```
> app.py  calculations.py  clock.py  errors.py  lookups.py  middleware.py
> models.py  requirements.txt  response.py
> routes_additions.py  routes_devices.py  routes_lines.py  routes_migration.py
> routes_port.py  routes_promo.py  routes_protection.py  routes_reservations.py
> routes_system.py  scheduling.py  services.py  start.sh  storage.py
> ```
> 22 files. Line counts (`wc -l`): models 367, routes_port 271, scheduling 225, routes_devices 203, calculations 187, routes_promo 177, routes_lines 175, routes_migration 149, routes_additions 134, routes_reservations 125, middleware 121, routes_protection 120, routes_system 104, clock 91, response 89, storage 83, lookups 76, app 64, errors 62, services 33, start.sh 11 — **2867 total**. `compileall` passes on every module.
>
> ### Launcher
> `start.sh` exists, is **executable** (`-rwxrwxr-x`), guards the pip install behind `python3 -c "import flask"`, and `exec`s `app.py` in the foreground. `app.py` binds `0.0.0.0` on `int(os.environ.get("PORT","10000"))` with `threaded=True`.
>
> ### Endpoint count: 43
> All 40 scaffold endpoints plus the 3 that exist only in PRD §4's table (`GET /port-requests/{id}`, `GET /trade-in-assessments`, `GET /subscriber-lines/{id}/device-installment-plans`). Both the scaffold and PRD agree on treating these as endpoints of this API, so both surfaces are implemented.
>
> ### Verification
> - Booting via `bash start.sh` serves immediately on `$PORT`.
> - A 200-assertion end-to-end workflow script (all 10 workflows: port-in submit/reject/resubmit/accept/cutover/cancel, migration eligibility+cutover, promo projection/vesting/clawback, device plans + trade-in grading, reservations commit/expiry, line-addition underwriting with all gate orderings, protection lifecycle, clock and ops-run) passes with **0 failures**.
> - Isolation confirmed directly: create an account, kill the process, re-invoke `start.sh` on the same port — the account then returns `ERR_ACCOUNT_NOT_FOUND`, and `SystemConfig` resets to its clock defaults. No SQLite, no file dumps, no `/tmp` cache; grep for persistence/seeding primitives in the boot path returns nothing.
>
> ### Notable spec decisions (PRD wins where it conflicts with SCAFFOLD)
> - **Line-addition review gate order** implemented per PRD §3.6 narrative — BLOCKED → line ceiling → deposit — which contradicts the scaffold's `validations[].priority` numbering (20/21/22). The PRD's explicit "masked/surfaces as/checked before" prose governs, matching §2.9.
> - **Port submit/resubmit ordering** follows PRD §3.1/§3.2 exactly: request state, then port-protection, then transfer credentials, then resubmission-eligibility/cooldown, then duplicate-MDN.
> - `updated_at` / `version` bump only when a derived value actually changes, so idempotent recomputations don't spuriously bump the line version a `Customer` monotonically advances.
> - Clock-driven side effects not itemised in the scaffold's endpoint table (installment upgrade eligibility, promo `cycles_elapsed` refresh) are wired into the clock/sweep passes.
>
> ### Two bugs found and fixed by the end-to-end test
> 1. Port and migration cutover sweeps were stamping `cutover_completed_at` and mutating the line but never setting `request_state`/`migration_state` to their terminal values — both requests hung in `ACCEPTED_PENDING_CUTOVER`/`CUTOVER_SCHEDULED` forever.
> 2. The three line-writing creates incremented `SubscriberLine.version` twice (once explicitly, once inside the list mutator), which silently breaks every subsequent `expected_subscriber_line_version` on the line.
>
> Process safety: every server I started was killed by its exact PID captured from the listening socket; a PID scan before finishing confirms no leftover listeners from this task.

Orchestrator verification on disk (independent):
- `find` returns exactly the 22 claimed files; `wc -l` totals 2867; `start.sh` is `-rwxrwxr-x`. Summary matches disk.
- **ISOLATION RULE held**: `grep` across all `.py`/`.sh`/`.txt` for `test_helper|test_suite|difficulty_design|corner_design|scaffold_difficulty|scaffold_corner|conftest|Design: Difficulty|Design: Corner` returns nothing. No forbidden artifact was read.
- **No persistence, no seeding**: the only hit for `sqlite|json.dump|pickle|/tmp/|seed|preload` is a `storage.py:4` comment stating the opposite ("Nothing is seeded, preloaded or persisted"). No hardcoded MDN literals (`415555####`) anywhere.
- **Independent smoke test** (my own PID, port 48717, killed by exact PID): `bash start.sh` boots in ~1.5 s; `POST /portability/accounts` returns 201 with `credit_class: CLASS_B`, `deposit_required_cents: 10000`, `version: 1`, default logical clock `2026-09-01T00:00:00.000Z`; response envelope is the required `{data, meta{api_request_id, api_request_timestamp}, response_type}` shape. `GET /portability/accounts` returns 405 — expected, no account-list endpoint is declared.
- **Spot-checked a pinned §1.8 constant**: `calculations.py:59-67` — `promo_provisional_total` = `BASE_CREDIT_CENTS + MONTHLY_BASE_CENTS * min(installment_months, retention_requirement_cycles)` and `promo_vested_total` = `MONTHLY_BASE_CENTS * cycles_elapsed`. For the `dual_variant_calc` instance (12/12/1000) that yields 20000 + 1000×12 = **32 000** provisional vs 1000×0 = **0** vested, matching the design index exactly. The dual-variant requirement is genuinely implemented, not collapsed to one number.

**Flagged for Step 7**: the subagent reports implementing the line-addition review gate order per PRD §3.6 narrative, which it says *contradicts* the scaffold's `validations[].priority` numbering 20/21/22. Per Key Principle 1, PRD wins, so this is the correct choice — but a difficulty instance built on that priority ordering may now fail. If Step 7 sees it, the resolution is that the test asserted a scaffold-only ordering, not a PRD one.

## Step 7: Run tests and iterate — in progress

Launched as ONE long-lived fix subagent owning the whole run-diagnose-fix-rerun loop.

## Step 7: Run tests and iterate — 2026-09-30T18:31:00.000Z

Subagent summary, verbatim:

> Clean 8-round sweep: **101/101 passing in every round**. No leftover servers.
>
> ## Summary
>
> **Iterations run:** 3 (failures 46 → 22 → 0). Every iteration was a full 8-round parallel stability sweep; the final sweep passed 101/101 in all 8 rounds.
>
> ### Tests deleted
> **None.** Every failing test traced to a rule with a verbatim PRD sentence, so the PRD-First deletion criterion was never met.
>
> ### Fixes applied to `test_helpers/fixtures.py`
> The dominant root cause was one upstream fixture bug that masqueraded as 30+ independent failures (the triage hint applied exactly):
>
> - `setup_pending_port_request`, `setup_ported_line`, `setup_protected_line_with_rejected_request` — activated the line before submitting a port request, making `number_status` `ASSIGNED`. PRD §3.1 requires the target line be `UNASSIGNED` or `RESERVED` at submission, so the PRD-faithful server correctly refused the submit. Changed to `create_bare_line` (the §3.8 cutover cascade sets `service_status` ACTIVE on its own). This unblocked ~28 tests across suites 03/04/07/08.
> - `setup_pending_port_request` — added the `2026-09-02` clock advance every PRD §3.1 recipe performs, so `last_rejection_at` and the cooling-off arithmetic are measured from the recipe's stated instant (fixed `resubmission_inside_cooldown_is_refused`).
> - `get_port_request` / `get_promo_schedule` read-backs — restored to the operator identity; PRD §3.11 explicitly makes these individually readable by "the roles involved in their workflow".
> - `create_active_promo_schedule` — now advances the clock to the schedule's `window_start` before activating, since the activate gate requires being at or after `window_start`.
> - `setup_migration_with_anchor_lines` — migrating line left out of service so it does not inflate `active_line_count`, which PRD §3.3 reads "before this migration's line is counted".
>
> ### Fixes applied to `test_suite/`
> - `test_03`/`test_04`/`test_08` inline setups — same bare-line correction and `create_bare_line` import added to test_08.
> - `test_03` `create_clawback_pair` — schedule brought to ACTIVE before the reversal (PRD §3.4: reversal is permitted "while it is `ACTIVE`, and only then").
> - `test_03` `test_eligibility_check_requires_a_prepaid_line` — upgraded from a weak `!= DRAFT` assertion to the exact PRD §2.9/§3.3 outcome (409 `ERR_INVALID_STATE`, request stays `DRAFT`); the old form could never fail for the right reason.
> - `test_06` `test_the_closed_window_leaves_the_hold_outstanding` — corrected a scaffold-only assertion (`number_status == ASSIGNED`) that contradicted the test's own name and the scaffold's own assert block; now asserts the hold outstanding (`UNASSIGNED` + reservation `EXPIRED`), per PRD §3.9.
> - `test_02`/`test_08` — `get_account(...)["active_line_count"]` freshness and millisecond-format timestamp literal.
>
> ### Fixes applied to `implementation/`
> - `routes_migration.py` — added `schedule_if_due()`: PRD §3.3 makes APPROVED → CUTOVER_SCHEDULED automatic "once `requested_cutover_at` is set to an instant at or after the current logical clock instant", so the step runs in the same operation that produced the approval.
> - `scheduling.py` `promo_progress()` — the vested total now tracks `cycles_elapsed` on every clock advance, not only at vesting; PRD §3.4 defines it as "1 000 cents multiplied by `cycles_elapsed`" and states vesting does not retroactively convert it.
> - `routes_reservations.py` — the closed-window check now precedes the generic HELD-state gate, so an expired hold reports `ERR_RESERVATION_WINDOW_CLOSED` instead of `ERR_INVALID_STATE`.
> - `routes_port.py` — `_check_transfer_credentials` now runs before the line's number-status check (PRD §2.9 orders the transfer-credential check ahead of the business constraints on submit) and compares the presented PIN/account number against the request's stored credentials (PRD §3.2: resubmission "takes the same `transfer_pin` and `account_number_at_losing_carrier` the submission took"); this fixed `test_pin_that_disagrees_with_the_draft_is_refused` (409 → 422).
> - `routes_port.py` — single port-request read roles aligned with PRD §3.11.
> - `routes_promo.py` — single schedule read roles aligned with PRD §3.11; OCC stale-version check moved ahead of the window-overlap test so a stale create surfaces as 412.
> - `routes_system.py` — `ops_run` records `last_ops_run_at` in the API's canonical three-fractional-digit form.
>
> ### Notes for the doc-generator
> - **PRD §3.11 visibility prose vs §4 endpoint table disagree on single-resource read roles.** §3.11 says "promotional schedules ... [are] individually readable by the roles involved in their workflow" (i.e. including CustomerService/PlatformAdmin), but §4's table lists only `Customer`; §3.11 says a port request "may be read by a platform operator, a care agent, a credit analyst or a customer", but §4 lists only `Customer`. The §4 rows look like table-generation loss. I followed §3.11 prose (PRD-First) and the implementation now admits the workflow roles.
> - **The known latent resubmit contradiction was not touched** — no test exercised it, per the orchestrator's instruction.
> - `test_06`'s `the_closed_window_leaves_the_hold_outstanding` had been regenerated from a scaffold-only expectation that directly contradicted both its own test name and the design instance's own assert block — worth a look in unit-test-generator.

Orchestrator verification (independent):
- All 8 `results.{1..8}.json` present (18:31, ~35.6 KB each) and each parses to `passed=101 total=101 failed=0`. The 8 rounds are genuinely distinct files (varying sizes), not copies.
- **mtime audit clean**: `find workspace/implementation test_helpers test_suite -name '*.py' -newermt '2026-09-30 18:31:00'` returns nothing — no source write landed after the sweep began, so the sweep was not invalidated by post-sweep edits (the failure mode that broke a previous pipeline on this host). Newest source file is 18:27, four minutes before the sweep.

**This step produced `implementation/` fixes, so Step 8 is NOT skipped** (skip requires 0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes; here we have 0 deletions but 8 implementation fixes, 6 test_helpers fixes, ~7 test_suite fixes).

Three items for Step 8 to consider as PRD-silence/mismatch sites:
1. The PRD §3.11-visibility-prose vs §4-endpoint-table role disagreement (impl followed §3.11) — a genuine PRD-internal mismatch, not merely silence.
2. `ERR_RESERVATION_WINDOW_CLOSED` vs `ERR_INVALID_STATE` precedence on an expired hold.
3. Transfer-credential check ordering ahead of the number-status gate on submit/resubmit.

## Step 8: Finalize PRD — 2026-09-30T18:50:00.000Z

Subagent summary, verbatim:

> All seven edits are in place with the file line count unchanged. Final verification confirms 336 → 336 lines (0% delta), seven changed lines.
>
> ## Summary
>
> **Output:** `workspace/PRD_FINALIZED.md`
> **Line counts:** PRD.md 336 → PRD_FINALIZED.md 336 (0% delta; 7 single-line in-place revisions, no sections added).
>
> ### Changes (one bullet per edit)
>
> - **§3.1 Submission** — revise — the transfer-credential rule now states the pin/account-number are checked for exactly-four-digits **and** must reproduce the credentials **stored on the request** (not merely agree with each other). — `implementation/routes_port.py:23` (`_check_transfer_credentials`)
> - **§3.2 Resubmission** — revise — same correction to the resubmission-credential sentence. — `implementation/routes_port.py:23`, `:198`
> - **§3.3 Migration scheduling** — insert — adds that the automatic `APPROVED → CUTOVER_SCHEDULED` step runs **in the same operation that produced the approval** (the check-eligibility call, and after a later `changed_at` write), not only on a subsequent clock advance; and that on a clock advance it runs before the completion step. — `implementation/routes_migration.py:42` (`schedule_if_due`), `:157`, `scheduling.py:99`
> - **§3.4 Promo vested total** — insert — adds that `cycles_elapsed`/`vested_total_cents` are **refreshed on every clock advance** for a schedule still `PROVISIONAL`/`ACTIVE`; `VESTED`/`CLAWED_BACK` are not refreshed, and a clawback zeroes the vested total. — `implementation/scheduling.py:157` (`promo_progress`)
> - **§3.9 Reservation commit** — insert — states the **open-window test precedes the `HELD` state gate**, so a past-`reserved_until` hold reports `ERR_RESERVATION_WINDOW_CLOSED` rather than `ERR_INVALID_STATE`, while a non-`HELD` hold inside an open window still reports `ERR_INVALID_STATE`. — `implementation/routes_reservations.py:104`
> - **§4 endpoint table, `GET /portability/port-requests/{id}`** — revise — role list `Customer` → `PlatformAdmin, CustomerService, CreditAnalyst, Customer`. — `implementation/routes_port.py:102`
> - **§4 endpoint table, `GET /portability/promo-credit-schedules/{id}`** — revise — role list `Customer` → `PlatformAdmin, CustomerService, Customer`. — `implementation/routes_promo.py:101`
>
> ### Per-edit pre-edit search log
>
> **E1 — §3.4 vested refresh.** (a) Subject: refresh of `cycles_elapsed`/`vested_total_cents` during a clock advance. (b) Enumerated/read: `scheduling.promo_progress` (refresh loop keyed to `PROVISIONAL`/`ACTIVE`; separate vesting loop; `VESTED`/`CLAWED_BACK` skipped), `routes_promo.create_schedule` (sets `cycles_elapsed` at create), `activate_schedule` (no refresh), `claw_back` (vested→0), `calculations.promo_vested_total`; grepped `cycles_elapsed|vested` across tests. (c) Wording widened to be **state-scoped** rather than universal ("a schedule that is still `PROVISIONAL` or `ACTIVE`") so it stays consistent with the create/activate/clawback paths that also touch these fields; explicitly noted `VESTED`/`CLAWED_BACK` exclusion.
>
> **E2 — §3.3 scheduling timing.** (a) Subject: the `APPROVED → CUTOVER_SCHEDULED` automatic step. (b) Grepped `CUTOVER_SCHEDULED|schedule_if_due`; read `routes_migration.schedule_if_due`, both call sites in `evaluate_eligibility`/`check_eligibility`, `scheduling.migration_progress`, plus tests `test_03:78` and `test_09:188`. (c) Phrased to cover **both** the same-operation path and the clock-advance path, avoiding a claim that scheduling happens only immediately.
>
> **E3 — §3.9 window/state precedence.** (a) Subject: precedence between the open-window test and the `HELD` state gate on commit. (b) Read `routes_reservations.commit_reservation` (whole function), `scheduling.reservation_expiries`, PRD §2.9 (which lists "committing a reservation" under the generic state gate), test_06 `TestReservationCommitWindow`. (c) Added a clause preserving that `ERR_INVALID_STATE` still applies to a non-`HELD` hold inside an open window, so the change does not accidentally retire the §2.9 state gate.
>
> **E4 — §3.1 / §3.2 credential comparison.** (a) Subject: what the presented pin/account-number are compared against. (b) Read `routes_port._check_transfer_credentials`, both callers (submit, resubmit), `create_port_request` (stored pair), test_07 `TestTransferPinAgreement`. (c) Explicitly did **not** fold the missing-account-number 400 case into the 422 claim; kept the four-digit-format check named so the format branch is not lost.
>
> **E5 — §3.11 / §4 read roles.** (a) Subject: roles permitted on single-resource reads. (b) Grepped `require_roles` across all route modules; read `get_port_request`, `get_schedule`, `get_migration`. Confirmed only these two table rows conflicted with §3.11 prose. (c) Aligned table rows **to §3.11 prose** (the operative text the implementation follows); no other row touched.
>
> ### Considered and deliberately skipped
> - **§3.3 recovery-path re-entry timing** — implementation performs `APPROVED → ELIGIBILITY_CHECK → evaluate` in the same call, but this runs on the clock pass as well; adding a timing claim risked over-specifying. E2 already documents the observable scheduling outcome, so no edit.
> - **§3.7 `last_ops_run_at` canonical format** — verified this is *already determined* by §2.5 (three-fractional-digit timestamps); no PRD silence, so no edit.
> - **The known latent resubmit contradiction** (§3.2 priority-8 gate vs. the PROTECTED-clearing side effect) — deliberately untouched, per the diff note; no test exercised it.
>
> ### Diff items needing **no** PRD edit
> Pure fixture/helper bugs (no PRD silence or mismatch): the bare-line/`UNASSIGNED` activation corrections (`setup_pending_port_request`, `setup_ported_line`, `setup_protected_line_with_rejected_request`, test_03/04/08 inline setups), the `CLOCK_DAY_1` clock-advance additions, the `create_bare_line` import, the `create_active_promo_schedule` window advance, the `setup_migration_with_anchor_lines` out-of-service line, the test_03 `create_clawback_pair` activation, the test_06 closed-window assertion correction, and the test_02/08 freshness/timestamp fixes — all now consistent with PRD text as written.

Orchestrator verification (independent): `PRD.md` 336 lines / 73 978 bytes → `PRD_FINALIZED.md` 336 lines / 75 601 bytes (0% line delta, +1623 bytes). `diff` shows exactly 7 changed lines at lines 109, 123, 136, 149, 225, 266, 294 — matching the 7 reported edits, all in-place paragraph revisions, no new sections. I read the full diff and confirmed each edit matches the corresponding Step 7 `implementation/` fix and that the state-scoping wording in E1/E3 is correctly hedged rather than universally claimed.

## Step 9: Complete PRD — in progress

Always runs (per the skill, no skip condition). Launched alone in its own message.

## Step 9: Complete PRD — 2026-09-30T19:07:00.000Z

Subagent summary, verbatim:

> Done. All patches applied and verified.
>
> ## Source vs output
>
> - Source: `workspace/PRD_FINALIZED.md` — 336 lines, 75 458 chars
> - Output: `workspace/PRD_COMPLETED.md` — 336 lines, 87 079 chars (char-delta **+11 621**; `wc -c` delta +11 478)
> - 31 in-place hunks, zero new lines, zero new sections. Edit-only patch, line count unchanged.
>
> ## Counts
>
> - **ambiguity-pins: 26**
> - **mismatch-revisions: 5** (lines 132, 136, 155, 166, 194)
>
> ## Changes (one bullet per hunk)
>
> - §2.3 Pagination — insert — ambiguity — `limit`/`offset` out-of-band values are clamped/fallback rather than refused — `implementation/response.py:68-86`
> - §2.7 OCC — insert — ambiguity — `expected_subscriber_line_version` is optional; omitted ⇒ check skipped — `implementation/middleware.py:109-122`
> - §3.1 create port request — insert — ambiguity — credentials stored verbatim, cutover canonicalized, create does not consult `number_status` — `implementation/routes_port.py:62-98`
> - §3.1 submit — insert — ambiguity — bad `number_status`/stale cutover ⇒ `ERR_INVALID_STATE`; missing acct ⇒ `ERR_INVALID_REQUEST`; mismatched acct ⇒ `ERR_TRANSFER_PIN_MISMATCH` — `implementation/routes_port.py:127-154`
> - §3.2 catalog create — insert — ambiguity — `rejection_code` uniqueness, required fields, no `updated_at`/`version` — `implementation/routes_system.py:77-102`
> - §3.2 resubmit side effect — insert — ambiguity — pins the unconditional protection gate over the conditional clear (item c) — `implementation/routes_port.py:195-238`
> - §3.3 eligibility — **revise** — mismatch — evaluation is synchronous inside the eligibility call, not a scheduled event — `implementation/routes_migration.py:122-159`
> - §3.3 re-entry — insert — ambiguity — `cleared_at` must exceed the request's `updated_at`; other states ⇒ 409 — `implementation/routes_migration.py:137-146,162-172`
> - §3.3 scheduling/cutover — **revise**+insert — mismatch+ambiguity — tier ordering means no same-sweep completion; all `CONVERTED` plans plural; `device_balance_cents` read pre-conversion; `changed_at` applied after evaluation — `implementation/scheduling.py:93-113`, `routes_migration.py:148-157`
> - §3.4 create schedule — insert — ambiguity — `monthly_credit_cents` unused by either total; `installment_months>=1`; `window_start` required — `implementation/routes_promo.py:45-54`
> - §3.4 buffer test — insert — ambiguity — OCC checked ahead of the overlap test — `implementation/routes_promo.py:56-65`
> - §3.4 totals — revise — ambiguity — `cycles_elapsed` seeded at create; totals read only their own inputs — `implementation/routes_promo.py:85`, `calculations.py:55-71`
> - §3.4 clawback — **revise**+insert — mismatch — schedule state gate precedes the line-activity gate; explicit plan-selection rule — `implementation/routes_promo.py:132-182`
> - §3.5 plan create — insert — ambiguity — `upgrade_eligible_at` null until financed; required fields; arithmetic applied at quote — `implementation/routes_devices.py:36-88`
> - §3.5 activation/state — insert — mismatch — `UPGRADE_ELIGIBLE` blocks activation; full plan-state derivation and clock-driven promotion — `implementation/routes_devices.py:22-33`, `services.py:8-33`, `scheduling.py:214-225`
> - §3.5 assessment create — insert — ambiguity — estimate does not recompute plan balance/installment; new-assessment defaults; invalid `declared_condition` ⇒ 400 — `implementation/routes_devices.py:114-144`
> - §3.5 grade — insert — ambiguity — `plan_state` re-derived so a financed plan keeps its position — `implementation/routes_devices.py:169-202`
> - §3.6 account create — insert — ambiguity — score 0..1000 ⇒ 400; required `account_type`/`tax_id_last4` — `implementation/routes_lines.py:21-60`
> - §3.6 addition create — insert — ambiguity — account resolved before the `line_count` range test — `implementation/routes_additions.py:25-53`
> - §3.6 decline — **revise** — mismatch — decline does not recompute the account's `deposit_required_cents` — `implementation/routes_additions.py:126-133`
> - §3.7 line create — insert — ambiguity — `billing_mode` limited to `PREPAID`/`POSTPAID` — `implementation/routes_lines.py:79-85`
> - §3.7 mdn conflict — insert — ambiguity — create names `account_id` (must resolve) + `mdn` — `implementation/routes_lines.py:72-106`
> - §3.7 cancel — insert — ambiguity — already-cancelled ⇒ 409; missing `reason_code` ⇒ 400; `reason_code` unvalidated — `implementation/routes_lines.py:152-176`
> - §3.7 ops-run — insert — ambiguity — reclaimed lines bumped version; response is the `SystemConfig` row; rejection-record response is 201 — `implementation/routes_system.py:39-67`
> - §3.8 port cutover — insert — ambiguity — `account_status` forced to `OPEN`; statuses written unconditionally — `implementation/scheduling.py:26-67`
> - §3.9 reservation create — insert — ambiguity — required fields and account existence — `implementation/routes_reservations.py:37-76`
> - §3.9 overlap — insert — ambiguity — overlap test is existing-start strictly earlier AND existing-until strictly after new start — `implementation/routes_reservations.py:18-34`
> - §3.10 activate — insert — ambiguity — competing-case test measured via the line's `port_protection_status` — `implementation/routes_protection.py:80-93`
> - §3.10 deny — insert — ambiguity — `resolution` value checked before case state; invalid ⇒ 400 — `implementation/routes_protection.py:74-76,95-99`
> - §3.10 clear — insert — ambiguity — every `RESUBMITTED` request reset with log untouched; `PENDING` untouched — `implementation/routes_protection.py:101-119`
> - §3.11 visibility — insert — ambiguity — per-line plan / per-plan trade-in / flat trade-in read scopes and the Customer ownership 403 — `implementation/routes_devices.py:100-102,147-166`, `middleware.py:41-45`
>
> ## The three flagged items
>
> **(a)** Confirmed. `GET /portability/port-requests/{id}` = `[PlatformAdmin, CustomerService, CreditAnalyst, Customer]` and `GET /portability/promo-credit-schedules/{id}` = `[PlatformAdmin, CustomerService, Customer]` in both §4 and `routes_port.py:101-107` / `routes_promo.py:100-106`. The third such GET was **not** left inconsistent: `GET /portability/trade-in-assessments` is `Customer`-only in §4 and `routes_devices.py:147-153` is `require_roles("Customer")` — they agree. (I briefly mis-edited that row to a broader gate and reverted it; the file is correct.) A machine diff of all 43 table rows against the implementation's decorators shows **zero** role-gate mismatches.
>
> **(b)** Confirmed. `GET /portability/subscriber-lines/{id}/device-installment-plans` is a declared §4 row and an implemented endpoint (`routes_devices.py:100-102`, `PLAN_READERS` = `[PlatformAdmin, CustomerService, TradeInInspector, Customer]`). Role gate matches, and shape (paginated array of plan objects) is now pinned in §3.11.
>
> **(c)** Pinned in §3.2 without inventing a branch. The implementation's resubmit handler calls `_check_protection(line)` unconditionally before the conditional clear (`routes_port.py:203,229-236`), so the `PROTECTED` line never reaches the clearing hop; the PRD now states the unconditional gate reading governs and that the conditional side effect is unobservable through the API. No new state branch was added.
>
> ## Coverage
>
> Walked all 22 implementation modules exhaustively: all 9 `routes_*.py` (43/43 endpoints, every decorator, body-coercion order, error id/status), `scheduling.py` (all 5 scheduled transitions and their 3-tier ordering), `calculations.py` (all 6 calculation rules and every constant), `models.py` (all 12 serializers, all derived-field recomputations, `touch`/version semantics), `middleware.py`, `errors.py`, `response.py`, `clock.py`, `storage.py`, `lookups.py`, `services.py`, `app.py`. Verified 43/43 endpoints, 5/5 scheduled transitions, 6/6 calculations, 12/12 entity shapes. Tests were consulted only where an ambiguity could not be resolved from the implementation alone (OCC, trade-in settlement, migration scheduling) and never treated as authority; no test-driven behavior was pinned.

Orchestrator verification (independent): `PRD_FINALIZED.md` 336 lines / 75 601 bytes → `PRD_COMPLETED.md` 336 lines / 87 079 bytes (+11 478 bytes by `wc -c`; the subagent's +11 621 figure is close enough, the small gap is trailing-newline counting — immaterial). Line count unchanged, consistent with an edit-only in-place patch across 31 hunks. Spot-verified flagged item (a): §4's `GET /portability/trade-in-assessments` row reads `Customer` and `routes_devices.py:148` is `require_roles("Customer")` — they agree, so the reported mis-edit-and-revert left the file correct.

**Post-sweep validity re-confirmed**: `find workspace/implementation test_helpers test_suite -name '*.py' -newermt '2026-09-30 18:31:00'` returns nothing after Steps 8 and 9. Both steps wrote only Markdown PRD artifacts, never code, so the Step 7 8-round 101/101 sweep remains valid and is the authoritative result.

---

# Pipeline complete

All 9 steps done. Final state:

- **Scaffold**: 40 endpoints (at ceiling), 12 entities, 7 state machines, 6 calculations, 28 validations, 33 error codes, 5 roles, 2 concurrency rules; 19 difficulty + 26 corner instances, all uniquely PRD-derivable.
- **PRD chain**: PRD.md (336 lines) → PRD_FINALIZED.md (336, 7 edits) → PRD_COMPLETED.md (336, 31 hunks: 26 ambiguity-pins + 5 mismatch-revisions).
- **Implementation**: 22 Python/Flask modules, 2867 lines, 43 endpoints, in-memory storage only, no seeded data, `start.sh` executable and booting in ~1.5 s.
- **Tests**: 101 tests across 9 files + 9 helper modules; 52 from queue A, 49 from queue B; 0 skipped, 0 deleted.
- **Result**: all 8 rounds of the final stability sweep pass 101/101.

Deviations from the skill's default flow, all caller-directed or forced:
1. Steps 5 and 6 ran **sequentially**, not concurrently. The caller overrode the skill because this model endpoint duplicates parallel tool calls. This removed the *physical* isolation the concurrency normally gives Step 6 (its `test_suite/` cannot exist yet if Step 5 runs simultaneously), so I restored it *in software* via the ISOLATION RULE in the Step 6 prompt, then verified it held by grepping the implementation for any reference to forbidden artifacts — clean.
2. Step 2 needed a retry: the first attempt aborted on the 32000-token output cap before writing anything. The retry succeeded once I made the output-budget rule explicit.
3. The task index `3262` and directory were pre-allocated by the caller; I did not compute an index or create any other `task_*` directory.

Known unresolved item carried forward: the **latent scaffold contradiction** around resubmit (priority-8 `UNPROTECTED` gate vs. the endpoint's PROTECTED-clearing side effect), which originates in SCAFFOLD.yaml rather than the PRD. No test exercises the contradictory branch. Step 9 pinned the unconditional-gate reading in §3.2 without inventing a branch. Reported here rather than silently resolved, per Key Principle 1.