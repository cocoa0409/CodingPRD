## Step 1: Create task directory — 2026-09-04T23:50:00.000Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2804_employee_perks_discount_marketplace and its workspace/ subdirectory. Index 2804 was pre-assigned by the orchestrator invocation; no scan of ./tasks/ was performed.

## Step 2: Generate scaffold — 2026-09-05T01:45:00.000Z

All three scaffold artifacts for task 2804 are complete and lint-clean.

**Output directory** `/home/ubuntu/github/CodingPRD/tasks/task_2804_employee_perks_discount_marketplace/`

| file | lines |
|---|---|
| `SCAFFOLD.yaml` | 3357 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2438 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 6420 |

**Lint verdict, verbatim**

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2804_employee_perks_discount_marketplace/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2804_employee_perks_discount_marketplace/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2804_employee_perks_discount_marketplace/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    66
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     59
  Calls scanned (§1.8+§1.9):  1319

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Structure and self-checks:
- `SCAFFOLD.yaml` top-level keys are exactly `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — no design keys; the scenario text begins at "Employee Perks & Discount Marketplace ..." and the difficulty directive appears nowhere in the file.
- Each design file has a single top-level key (`scaffold_difficulty_design`, `scaffold_corner_design`).
- §1.9 holds 86 instances (59 full recipes + 27 `excluded_because` stubs) across all nine guide sections: entities 12, state_machines 16, calculations 12, validations 13, endpoints 5, errors 10 (all stubs), rbac 6, cross-cutting complexity layers 7, consistency model 1.
- Verified programmatically: every `grounds` reference resolves into §1.1–§1.7 (calculations, entity fields, error ids, validation priorities, endpoint signatures, concurrency rule ids, state-machine transitions); all 60 error codes in the catalog are triggered or stub-attributed; every stub's `difficulty_instance` names a real §1.8 instance and carries no `test_recipe`; instance names are globally unique across both design files; no forbidden concurrency vocabulary; no stray instance-level keys.

Two defects were found and fixed while writing this final stretch: a `state_machines.Dispute.status.UNDER_REVIEW_to_...` ground that named a non-existent transition (corrected to `MERCHANT_RESPONDED_to_RESOLVED_MERCHANT_FAULT`), `calculations.redemption_economics` (real name `redemption_line_economics`), and in the consistency instance an `inventory_remaining` field that does not exist plus a 1-hour verification TTL assertion (the constant is 72 hours → `2026-08-04T00:00:00Z`).

Orchestrator verification: grep for "harder than expert" across the task dir returns no match — the difficulty directive did not leak into the scaffold.

## Step 3: Copy shared files — 2026-09-05T01:45:30.000Z

Copied ./INSTRUCTION.md to tasks/task_2804_employee_perks_discount_marketplace/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-05T02:07:00.000Z

PRD generation complete.

**Output:** `workspace/PRD.md` — 513 lines, 112,956 bytes, written in eleven `cat >>` heredoc appends (no single giant Write).

**Structure:** §1 Introduction (3 paragraphs) · §2 with ten subsections (2.1 RBAC, 2.2 verbatim response block, 2.3 Pagination, 2.4 Logical Clock & Epoch Sweep, 2.5 Common Resource Properties & Append-Only Records, 2.6 Monetary Discipline/Basis Points/Rounding, 2.7 Version Echo & Stale-Read Rejection, 2.8 Cascade Discipline, 2.9 Path Resolution & Rule-Evaluation Order, 2.10 Employee Privacy & Cohort Suppression) · §3 with nine subsections (partner recruitment/negotiation loop; acceptance, activation, exclusivity, coverage floor; employer onboarding, eligibility batches, roster; branded storefronts & derived posture; offers; placement slots & five-step pricing; redemption screening/verification/line economics; fulfilment, disputes, partner accountability; settlement statements & the ledger) · §4 endpoint table (4 columns, 66 rows) · §5 error table (2 columns, 60 rows).

**Ends at a real section boundary:** the last line is the final §5 table row `| `ERR_EXCLUSIVITY_TERMS_MISSING` | 422 |`. Nothing is mid-sentence, and there is no audit footer or contract-report block in the file.

```
Field coverage check:
- entities[].fields: 141 required, 141 present, 0 missing
- endpoints[].request_body: 65 required, 65 present, 0 missing
- endpoints[].query_params: 29 required, 29 present, 0 missing
- endpoints[].path_params: 0 required (scaffold declares only {id} path ids, never listed as inputs)
Status: PASS
```
Two independent passes were run; the second restricted the search window to §1–§3 only (excluding the §4/§5 tables) and still found 0 missing entity fields and 0 missing enum values, so every identifier is reachable in narrative rather than only in a table.

```
Rule coverage check:
- validations[] with priority: 42 checked, 42 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 4 checked, 4 expressed (write_endpoint + expected_<parent>_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 60 checked, 60 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed, 0 missing
- validations[] conditions: 42 checked, 42 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 66 endpoints + 42 applies_to scopes checked, all expressed, 0 missing
- entities[].fields[] structured content: 141 checked, 141 reconstructible from prose, 0 missing
- sibling-branch symmetry: 16 groups checked, 16 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1262
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```
§3 also contains zero raw (un-backticked) occurrences of `/perks` and zero raw HTTP method words.

**Other verifications:** §2.2 is byte-identical to `section-2.2-response-structure.md` (an earlier stray `---` rule after it was removed); all 66 endpoints in §4 match the scaffold's method, path and exact role set; all 60 error IDs and HTTP statuses in §5 match the scaffold exactly; no pseudocode, operator syntax (`>=`, `<=`, `*`, `clock_now`), or fuzzy words ("approximately", "roughly", "conservatively") anywhere in the document.

**Ambiguities resolved explicitly** (scaffold had a precondition with no nominated error, so the PRD names one to keep behaviour uniquely determined): agreement activation against a non-eligible partner → `ERR_MERCHANT_SUSPENDED`; offer resume past `window_end` → `ERR_OFFER_INVALID_STATE`; redemption creation is specified as an exact ordered check list (the scaffold declares no offer-status precondition, so none was invented); `audit_risk_score` is specified as computed at verification only (the calculation's declared trigger), since the field comment's extra "and at dispute resolution" would otherwise create two conflicting normative readings. Slot completion is stated to free the featured-concurrency ceiling while still counting toward the 7-day cooldown, reconciling the state-machine note with the cooldown validation.

The two withheld design files were never opened, grepped or referenced, and no sibling task directory was read.

Orchestrator truncation check: `tail -25` shows the file ending on the last complete §5 error-table row; 27 markdown headings present. Not truncated — no regeneration needed.

## Step 5: Generate unit tests — 2026-09-05T02:45:00.000Z

The suite is complete. Both queues are fully translated and machine-verified.

## Output

`test_helpers/` — 10 files, 2,370 lines
`__init__.py` 47 · `api_client.py` 256 · `api_errors.py` 144 · `assertions.py` 392 · `constants.py` 121 · `factories.py` 258 · `fixtures.py` 534 · `test_users.py` 59 · `time_utils.py` 84 · `types.py` 475

`test_suite/` — 12 files, 6,380 lines, **132 test functions**
`conftest.py` 49 · `test_corner_calculations_endpoints.py` 851 (12) · `test_corner_entities.py` 1013 (31) · `test_corner_rbac_layers.py` 651 (14) · `test_corner_state_machines.py` 1036 (13) · `test_corner_validations.py` 971 (21) · `test_difficulty_compensating_invariant.py` 244 (6) · `test_difficulty_cross_entity_dependency.py` 192 (4) · `test_difficulty_dual_variant_and_formula.py` 363 (9) · `test_difficulty_priority_and_boundary.py` 346 (8) · `test_difficulty_state_machine_and_cascade.py` 413 (9) · `test_difficulty_temporal_overlap.py` 251 (5)

## Verification (AST pass over all 132 tests)

- Every test has exactly one `Design:` line and it is the docstring's last line; every instance name resolves to a real `name:` in its own yaml section/rule (no dangling, no dual tags).
- Every test has exactly one `PRD: "…"` citation and each is a byte-exact substring of `workspace/PRD.md`.
- Queue A: all **18** difficulty instances covered, **41 tests**, every instance with >=2 (three have 3).
- Queue B: all **59** non-stub corner instances covered, **91 tests**; none of the 27 `excluded_because:` stubs was translated.
- All 11 test modules import cleanly under `PYTHONPATH=<task root>`; no duplicate test function names across the suite; `__pycache__` removed.
- Nothing written outside `test_helpers/` and `test_suite/`; `workspace/` (incl. `implementation/`) and `worklog.md` untouched; no stray `test_*` dirs under `workspace/`.

## Notes worth carrying forward

- PRD beat the design index in several places and the tests assert the PRD: `proposer_role` is `PARTNER_MANAGER` never `PROVIDER`; HTTP statuses come from the §5 map registered by `test_helpers` rather than the index's prose; `ERR_OFFER_INVALID_STATE` (not `ERR_OFFER_WINDOW_CLOSED`) on resume past `window_end`; a same-instant prior does not count toward AUDIT velocity (asserted 15, not the index's 23); `region_codes` patched to `["CA","NY"]` since `NV` is not a valid region.
- Three design assertions were dropped as not uniquely PRD-derivable rather than weakened: the cross-tenant membership *list* refusal, `last_employment_change_at` on the TERMINATED branch, and the membership `status` after a batch rewrite. The index's claim that statement creation carries computed totals contradicts §3.9 (a statement is born `DRAFT` with zeros) and was not encoded.
- `test_helpers/constants.py` gained `INVALID_RECORD_RATIO_EXCEEDED` (a duplicate definition was collapsed to one).
- Implementation-sensitive assertions flagged by the subagents: `eligible_headcount` recomputed at a later clock without an epoch run, and the six-row dispute ledger asserted in §3.8 write order (all four resolution rows share one instant).

Orchestrator verification: test_helpers/ and test_suite/ are at the task root (12 + 10 .py files); `find workspace -name "test_*" -type d` returns nothing, so no stray test dirs landed under workspace/.

## Step 6: Generate implementation — 2026-09-05T02:45:30.000Z

The implementation is complete and verified.

## What was done

Finished the Python + Flask implementation in `workspace/implementation/`. This session added the remaining seven modules on top of the foundation and five route groups written earlier:

| File | Lines |
|---|---|
| `app.py` | 53 |
| `auth.py` | 80 |
| `calc.py` | 207 |
| `cascade.py` | 218 |
| `clock.py` | 62 |
| `db.py` | 92 |
| `derive.py` | 424 |
| `errors.py` | 85 |
| `response.py` | 57 |
| `support.py` | 86 |
| `validate.py` | 200 |
| `requirements.txt` | 1 |
| `start.sh` | 10 (executable) |
| `routes/__init__.py` | 37 |
| `routes/agreements.py` | 358 |
| `routes/disputes.py` | 140 |
| `routes/eligibility.py` | 131 |
| `routes/employers.py` | 238 |
| `routes/ledger.py` | 36 |
| `routes/memberships.py` | 76 |
| `routes/merchants.py` | 120 |
| `routes/offers.py` | 219 |
| `routes/ops.py` | 91 |
| `routes/redemptions.py` | 338 |
| `routes/reports.py` | 140 |
| `routes/slots.py` | 215 |
| `routes/statements.py` | 159 |

3,863 lines total; all 66 PRD §4 endpoints are registered (Flask reports 67 rules including `static`). Storage is in-memory dicts only, empty on every boot — `grep` for seeding turns up nothing but the two comments asserting the absence.

## Verification

Three end-to-end smoke suites were run against a freshly booted server (random high port, killed by PID via `ss -ltnp` — no pattern kills), each starting from an empty store; all passed:

1. **Happy path (45 checks)** — the PRD's own worked numbers reproduce exactly: redemption economics for an 8,396-cent ticket give 1,679/6,717/806/**202**/604 (half-up, not banker's), and slot pricing gives 3 days → 150,000 → +1,500bps 22,500 → 172,500 → −500bps 8,625 → **163,875**. Ledger nets to zero across confirm/release and verify/refund pairs.
2. **Ordering and error catalogue (33 checks)** — 401/403/412/422/409/404 statuses match §5; `ERR_INVALID_WINDOW` precedes `ERR_DISCOUNT_SHAPE_MISMATCH`, `ERR_MIN_SPEND_NOT_MET` precedes `ERR_VERIFICATION_TOKEN_INVALID`, missing OCC echo is `ERR_VALIDATION` while a wrong one is `ERR_STALE_VERSION`; cooldown separation refuses a STANDARD run 4 days after a FEATURED one; epoch sweep counters are correct and idempotent on a second run.
3. **Cascades (57 checks)** — two merchant-fault resolutions reach score 40 → partner SUSPENDED → offers PAUSED (`MERCHANT_SUSPENDED`) → slots RELEASED (`OFFER_PAUSED`) with compensating refund; decay to 0 permits reinstatement without un-pausing anything; dispute respond/request-info cycles cap at 2; NO_FAULT forces credit to 0 and touches no statement while MERCHANT_FAULT drives FINALIZED → REOPENED with stale totals; storefront freeze and membership revocation each void pending redemptions with the right `void_reason`; epoch default-judges an abandoned OPEN dispute; partner termination cascades agreement → offer → slots and leaves `active_agreement_count` at 0.

## Judgement calls worth flagging

- **Band order beats §3 prose** where they disagree, since §2.9 says its ordering "is part of the contract". So scope (band 1) precedes own-state on `verify` even though §3.7 lists state first, and `ERR_AGREEMENT_NOT_ACTIVE` precedes `ERR_MERCHANT_SUSPENDED` on offer resume even though §3.5 lists the partner first.
- **Epoch offer expiry does not release slots.** §3.5 scopes slot release to "the latter two cases" (agreement and partner termination), so the sweep only stamps `expired_at`. Verified as such.
- **The cooldown separation rule keys on the existing slot's tier only.** The STANDARD carve-out is stated for the concurrency ceiling and deliberately omitted for the separation rule; the scaffold's `merchant-slot-cooldown` condition confirms it.
- **Reservation does not check offer status.** §3.7 says "exactly this sequence of checks" and never names offer state; the window check is what gates it.
- **Reports are allowed for `PlatformAdmin`.** SCAFFOLD's role matrix line 3269 excludes engagement-report from PlatformAdmin's GETs, but the endpoint table and PRD §4 both list it — PRD wins.
- `/_clock/set_current_utc` enforces neither identity nor role (all five roles are authorized and the scaffold scopes the identity rule to `/perks`); `/_ops/run-epoch` requires `PlatformAdmin`.
- Test constraints were honored throughout: `test_helpers/`, `test_suite/`, both `SCAFFOLD_*_DESIGN.yaml` files and every sibling task directory were never read, and `worklog.md` was not touched.

## Step 7: Run tests and iterate — 2026-09-05T03:30:00.000Z

Only the three intended test-layer files were touched; `implementation/` and `worklog.md` are untouched.

## Summary

**Iterations run:** 3 (each a full 8-round parallel sweep under `setsid nohup`).

| Iteration | Result |
|---|---|
| 1 | 44/132 in all 8 rounds |
| 2 | 131/132 in all 8 rounds |
| 3 | **132/132 in all 8 rounds** — 0 failed, 0 errors, 0 skipped |

Final sweep was fully deterministic across all 8 concurrent rounds — no flakiness, no load-induced timeouts.

**Root cause (one bug, 88 tests):** every failure traced to a single non-derivable status-code expectation on the two verb-path negotiation endpoints, `POST /perks/agreements/{id}/propose` and `/counter`. The fixtures asserted HTTP 201; the implementation returns 200 with the updated agreement.

The implementation is PRD-faithful and internally consistent here: it returns 201 for every noun-path resource creation (`/merchants`, `/agreements`, `/offers`, `/employers`, `/redemptions`, `/eligibility-files`, `/placement-slots`, `/disputes`, `/revenue-share-statements`) and 200 for every verb-path action. PRD §4 does not uniquely determine which band `/propose` falls in, because that call does both things at once:

- §4: *"Resource creation returns HTTP 201; every other successful call returns HTTP 200, including the action endpoints that drive a state transition and the list endpoints."*
- §3.1: *"A `PartnerManager` proposes terms, **moving the agreement `DRAFT -> PROVIDER_PROPOSED`**"* — an action endpoint driving a state transition -> 200.
- §3.1 also: *"Each accepted proposal **writes a new round**..."* -> resource creation -> 201.

Both readings are articulable from PRD prose, so unique derivability is broken (STEP 1b). Same ambiguity governs the response *body*: §2.2 says *"operations that create or modify a resource will return the created or updated resource object"*, which admits either the new round or the updated agreement.

**Tests deleted:** none. All 132 tests remain, no skip/xfail markers added, no `error_id` assertion downgraded.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `propose_round()` and `counter_round()`: dropped the strict `get_success_data(response, 201)` to lenient `get_success_data(response)`. PRD §4 does not pin the success status of these two verb-path endpoints, so the setup helper must not over-constrain it. This one fixture bug was the upstream cause of all 88 iteration-1 failures.

**Fixes applied to `test_suite/`** (STEP 1c partial-coverage splits — uncovered assertion removed, PRD-covered assertions kept):
- `test_corner_state_machines.py::test_first_provider_proposal_opens_round_one_and_lifts_the_partner_into_negotiation` — removed `expected_status=201` on the `/propose` call. The test's own PRD-quoted rule (round 1, `proposer_role = PARTNER_MANAGER`, partner lifted to `IN_NEGOTIATION`) is still fully asserted from `GET /agreements/{id}`, `GET /merchants/{id}` and `GET /negotiation-rounds`, which PRD §2.3 and §4 do pin.
- `test_corner_rbac_layers.py::…stale_agreement_version_on_the_merchant_counter…` — relaxed `validate_success(accepted, 201)` to `validate_success(accepted)` and dropped the two body assertions reading `round_number`/`proposer_role` off the `/counter` response. Both facts are re-asserted immediately below from the `GET /negotiation-rounds` history, so no PRD-covered coverage was lost; the test's actual subject (`ERR_STALE_VERSION` on a replayed counter) is untouched.

**Fixes applied to `implementation/`:** none — no implementation defect was found. All remaining `201` assertions in the suite target genuine noun-path resource creations, where PRD §4 is unambiguous, and all passed unmodified.

### Orchestrator verification note

The Step 7 subagent deleted its own `results.*.json` and `sweep.log` before exiting, so its clean-sweep claim had no surviving artifact. The orchestrator therefore re-ran the full 8-round sweep itself under `setsid nohup` and independently confirmed the result:

```
results.1.json 132/132 failed=0 errors=0 skipped=0
results.2.json 132/132 failed=0 errors=0 skipped=0
results.3.json 132/132 failed=0 errors=0 skipped=0
results.4.json 132/132 failed=0 errors=0 skipped=0
results.5.json 132/132 failed=0 errors=0 skipped=0
results.6.json 132/132 failed=0 errors=0 skipped=0
results.7.json 132/132 failed=0 errors=0 skipped=0
results.8.json 132/132 failed=0 errors=0 skipped=0
ALL 8 ROUNDS PASS: True
```

Step 8 is NOT skipped: Step 7 made 1 `test_helpers/` fix and 2 `test_suite/` fixes (>0 iterations beyond baseline), so PRD.md left a behavior open that the implementation has already pinned.

## Step 8: Finalize PRD — 2026-09-05T03:30:00.000Z

`PRD_FINALIZED.md` is written. The Step 7 diff reduced to a single PRD-silence, so the patch is a single-sentence insert.

**Size**: PRD.md 513 lines / 112,956 bytes → PRD_FINALIZED.md 513 lines / 113,411 bytes. Line delta 0 (0.00%); byte delta +455 (+0.40%). One line touched (line 377).

**Change list (1 change)**
- §4 (Endpoint Definitions, preamble) — insert — after "…including the action endpoints that drive a state transition and the list endpoints.", added: an action endpoint that also writes one of the §2.5 append-only records is still an action endpoint and not a resource creation; specifically `POST /perks/agreements/{id}/propose` and `POST /perks/agreements/{id}/counter` each append a negotiation round yet return **HTTP 200 with the updated agreement object in `data`**, not the new round, whose fields are read back via `GET /perks/agreements/{id}/negotiation-rounds` — `implementation/routes/agreements.py:182` (`propose`) and `:203` (`counter`), via `implementation/response.py:32` (`ok`, default 200).

**Pre-edit search log**
- (a) Subject: the success status code band *and* the response body identity of the two verb-path negotiation endpoints `/propose` and `/counter` — i.e. the global 201-vs-200 rule of §4 and the "created or updated resource object" rule of §2.2.
- (b) Paths enumerated (grepped/read):
  - `implementation/response.py` — `ok(data, status=200)`, `created(data) -> ok(data, 201)`, `listing(...) -> 200`. 201 exists on exactly one code path.
  - Every `response.created` callsite in the whole tree (9, all noun-path creations): `routes/merchants.py:42`, `routes/agreements.py:118`, `routes/employers.py:57`, `routes/employers.py:227` (eligibility-files), `routes/offers.py:92`, `routes/slots.py:136` (reserve), `routes/redemptions.py:127`, `routes/redemptions.py:322` (nested dispute filing), `routes/statements.py:71`. None is a verb path; my wording leaves all nine untouched.
  - Every `response.ok` callsite (all remaining verb-path actions, GETs and reports) — confirmed all verb-path actions return 200, including the ones that write append-only ledger rows: `routes/redemptions.py:253` (verify), `routes/slots.py:199/215` (confirm/release), `routes/disputes.py:140` (resolve), `routes/agreements.py:264/320/358` (decide/activate/terminate).
  - `implementation/routes/agreements.py` `propose` / `counter` / `_file_round` / `_republish` — the round is inserted with `versioned=False` and the handler returns the agreement.
  - `implementation/derive.py:163` `agreement_json` vs `:187` `round_json` — the returned payload is unambiguously the agreement shape (has `version`/`updated_at`, no `round_number`/`proposer_role`); `round_json` is only ever emitted by `GET .../negotiation-rounds` (`routes/agreements.py:159`).
  - Auxiliary evidence: `test_helpers/fixtures.py:67-96` (`propose_round`/`counter_round` now status-agnostic).
- (c) Wording adjustments made: (1) framed the rule generally ("an action endpoint that also writes one of the append-only records of §2.5") instead of carving out `/propose` and `/counter` as a lone exception, so it stays true of `verify`, `confirm`, `release` and `resolve`, which likewise append ledger entries and return 200 with the acted-on resource; (2) said "the updated agreement object" rather than "the parent resource" to avoid implying anything about the other endpoints' bodies; (3) added the `GET .../negotiation-rounds` pointer so excluding the round from the response body cannot be misread as the round not being persisted or readable.

No other PRD text was changed: the remaining Step 7 items (the `test_helpers/fixtures.py` status relaxation and the two `test_suite/` assertion removals) all trace to this same single ambiguity, and Step 7 applied no `implementation/` fixes, so there is no impl-vs-PRD mismatch to pin elsewhere.

Orchestrator verification: PRD_FINALIZED.md is 113,411 bytes vs PRD.md's 112,956 — not byte-identical, so the finalizer genuinely ran.

## Step 9: Complete PRD — 2026-09-05T04:10:00.000Z

Run as **three sequential file-partitioned passes** over one shared `workspace/PRD_COMPLETED.md`, partitioned by implementation module. Pass 1 did the `cp` from PRD_FINALIZED.md; passes 2 and 3 edited in place. Total: 513 lines / 113,411 bytes → 513 lines / 128,283 bytes (+14,872 bytes, +13.1%); 53 discrete edits (42 ambiguity-pins, 11 mismatch-revisions), all in-paragraph — no new sections, no new lines.

### Pass 1 — core + merchants/agreements/ops (app, auth, clock, db, errors, response, support, validate, calc, routes/__init__, merchants, agreements, ops)

Size 113,411 → 120,719 bytes. 16 ambiguity-pins, 3 mismatch-revisions (19 edits over 18 lines).

- §1 — revise — mismatch — "nothing reads the wall clock" was literally false; carved out the envelope stamp — `response.py:15-22`
- §2.1 — revise — mismatch — "every request must carry two headers" carved out for the clock endpoint, which applies no auth at all — `routes/ops.py:15-24`
- §2.1 — insert — ambiguity — whitespace-only `X-User-ID` = absent; id trimmed before ownership compare; absent/blank `X-User-Role` → `ERR_UNAUTHORIZED`; exact-spelling role compare after trim — `auth.py:46-60`
- §2.2 — insert — ambiguity — `api_request_id` = `req_` + 20 uppercase-alnum chars — `response.py:11-12`
- §2.2 — revise — mismatch — `api_request_timestamp` comes from the host clock, the only such timestamp in the API — `response.py:15-22`
- §2.3 — insert — ambiguity — blank pagination value rejected, absent one defaults; `total_count` pre-window; `has_more` = `offset + len(items) < total_count` — `validate.py:146-173`, `response.py:41-48`, `support.py:49-54`
- §2.3 — insert — ambiguity — identical `created_at` ties broken by server write sequence — `db.py:83-85`
- §2.3 — insert — ambiguity — filters match by exact equality, blank filter = absent, undeclared params ignored, boolean filter grammar — `support.py:61-70`, `validate.py:190-200`
- §2.4 — insert — mismatch — clock endpoint performs no identity/role check; ISO inputs normalised to UTC; sub-millisecond precision truncated not rounded — `routes/ops.py:16-24`, `clock.py:22-48`
- §2.4 — insert — ambiguity — each sweep pass completes before the next, rows visited in `created_at` ASC, fixing ledger append order — `routes/ops.py:32-83`
- §2.5 — insert — ambiguity — merchant read also recomputes `accrued_commission_payable_cents` and `active_agreement_count`; a read persists nothing and never bumps `updated_at`/`version` — `derive.py:142-160`
- §2.8 — insert — ambiguity — version increments once per row per request, not per touch; a row created by the request stays at version 1 — `db.py:65-80`
- §2.9 ¶1 — insert — ambiguity — a body FK that is absent/null/blank/non-string is a schema fault, not a not-found — `support.py:77-86`
- §2.9 band 1 — insert — mismatch — ownership only precedes existence where the named identifier is the principal's own; elsewhere the row is resolved first and a bad id yields not-found — `merchants.py:48-50`, `agreements.py:124-125`, `employers.py:21-25`, `memberships.py:22-24`, `redemptions.py:48-50`
- §2.9 band 3 — insert — ambiguity — absent/blank body = empty object; unparseable/non-object body = `ERR_VALIDATION`; no-body endpoints never inspect it; undeclared properties ignored; optional strings reject blank and store untrimmed; JSON `null` = not supplied — `validate.py:20-30,41-72`
- §3.1 — insert — ambiguity — merchant PATCH accepted in any status incl. `SUSPENDED`/`TERMINATED`, an empty PATCH still bumps `version`, `legal_name`/`primary_category` not amendable — `routes/merchants.py:73-89`
- §3.1 — insert — ambiguity — no partner-status guard on opening or negotiating a lane (only activation guards it); a `Merchant` listing agreements sees only its own — `routes/agreements.py:75-118,138-140`
- §3.2 — insert — ambiguity — the decision `note` is accepted but never persisted or returned — `routes/agreements.py:228-232`
- §3.2 — insert — ambiguity — a `Merchant` attempting `WITHDRAW` gets `ERR_UNAUTHORIZED`, ahead of schema/enum/state faults — `routes/agreements.py:215-217`
- §5 — insert — mismatch — catalogue re-scoped to declared endpoints; `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500 documented; trailing slash insignificant — `app.py:16,27-48`

Already pinned (no change): `errors.py` (all 62 statuses), `calc.py` (all 13 constants and every formula), `routes/__init__.py`, ops sweep passes 1–5, `db.py` insert semantics, `support.py` not-found map and OCC echo, `validate.py` two-pass enum ordering and window rule, merchants create/reinstate/terminate, agreements create/propose/counter/decide/activate/terminate incl. half-open exclusivity overlap-before-terms ordering and the coverage floor.

### Pass 2 — derive + employers/eligibility/memberships/offers/slots

Size 120,719 → 125,373 bytes. 15 ambiguity-pins, 4 mismatch-revisions (19 edits).

- §3.3 — insert — ambiguity — all three employer PATCH fields optional; a no-field amendment still bumps `updated_at`/`version`; `name`/`region_code` offered on it are ignored — `routes/employers.py:89-104`
- §3.3 — revise — mismatch — `effective_from` is recorded/echoed but used in no decision; currency comes from each record's own bounds — `routes/employers.py:190,211`, `derive.py:234`
- §3.3 — insert — ambiguity — the batch resource echoes the submitted `records` array back verbatim — `derive.py:237`
- §3.3 — insert — ambiguity — duplicate-ref detection compares only string references — `routes/employers.py:196-204`
- §3.3 — insert — ambiguity — a batch may be loaded from any storefront state or posture — `routes/employers.py:183-227`
- §3.3 — revise — ambiguity — required key "missing **or null**"; fourth test also fails a bound that does not parse as ISO 8601; `TERMINATED` is a valid record; reference checked for presence only — `routes/employers.py:165-180`
- §3.3 — revise — mismatch — the rejected branch leaves `integration_status` wherever it stands; the accepted branch sets `VALIDATED` from wherever it stands — `routes/eligibility.py:39-50`
- §3.3 — insert — ambiguity — a rewrite touches nothing beyond the five named fields (never `last_employment_change_at`); a new membership always lands `ELIGIBLE` with a null change stamp even when its record says `TERMINATED` — `routes/eligibility.py:87-105`
- §3.3 — insert — ambiguity — presence judged over **every** batch element incl. invalid ones; restoration reaches `SUSPENDED` only, a `REVOKED` row keeps `REVOKED`; the three membership counts defined — `routes/eligibility.py:69-73,106-125`
- §3.3 — revise — mismatch — employment write leaves eligibility `status` untouched on `ACTIVE`/`LEAVE` and revokes from `ELIGIBLE` and `SUSPENDED` alike, stamping `last_employment_change_at` in both branches — `routes/memberships.py:65-75`
- §3.3 — revise — mismatch — rehiring requires a fresh **membership**, not a fresh batch — `routes/eligibility.py:106-108`
- §3.3 — insert — ambiguity — an `EmployerAdmin` listing memberships sees only its own `employer_id` whatever filters it supplies — `routes/memberships.py:39`
- §3.4 — insert — ambiguity — all four branding properties required; the three strings only non-blank-checked and stored verbatim; repeated categories accepted — `routes/employers.py:112-118`
- §3.5 — insert — ambiguity — the referenced agreement must be the caller's own; another partner's is `ERR_SCOPE_VIOLATION` ahead of every schema check — `routes/offers.py:32-34`
- §3.5 — insert — ambiguity — the offer's `region_codes` is not checked for repeats — `routes/offers.py:44-45`
- §3.5 — insert — ambiguity — a `Merchant` reaches only its own offers; the other four roles read/list every offer — `routes/offers.py:99,115`
- §3.5 — insert — ambiguity — an explicit pause does **not** release the offer's `RESERVED`/`CONFIRMED` slots and writes no ledger entry, unlike the suspension-driven pause — `routes/offers.py:183-197`
- §3.6 — revise — ambiguity — "a state that permits placement" pinned to `ACTIVE` alone; the slot's `merchant_id` also copied from the offer — `routes/slots.py:69,121-123`
- §3.6 — insert — ambiguity — reserving refreshes the parent offer's `updated_at`/`version`; `Merchant` sees only its own slots, `EmployerAdmin` only its own storefront's — `routes/slots.py:135,144-145,159-162`
- §3.7 — insert — ambiguity — `verification_token` is not dropped from later representations; it appears carrying null — `derive.py:347`

Already pinned (no change): `derive.py` posture table, `eligible_headcount`, the 7d/30d counts, inventory triple, accrual pairs incl. the ×−1, `fulfillment_failure_score` read-time recompute, three-fractional-digit instants, append-only serializers, full field inventories; employers registration/posture/publish/suspend/freeze cascade and list filters; eligibility 500-bps inclusive boundary and role split; memberships scope-before-existence, `ERR_MEMBERSHIP_REVOKED` terminality, revocation cascade; offers discount shapes, window/footprint guards, submit/review asymmetry, resume guard set, `sold_out` tri-state; slots closed run intervals, featured ceiling of 2, 7-day separation, five-step pricing, confirm/release semantics and band ordering.

### Pass 3 — cascade + redemptions/disputes/reports/statements/ledger

Size 125,373 → 128,283 bytes. 11 ambiguity-pins, 4 mismatch-revisions (15 edits over 13 lines).

- §2.8 — insert — ambiguity — within every limb of either spine dependent rows are visited in `created_at` ASC, which is the append order of the compensating ledger entries — `cascade.py:51,100,124,157`
- §2.10 — insert — ambiguity — `period_start`/`period_end` required query params; never checked against each other, so an inverted period yields an empty population rather than `ERR_INVALID_WINDOW` — `routes/reports.py:55-56,105-106`
- §2.10 — insert — ambiguity — neither report is a paginated collection: `response_type` `object`, whole `category_rows` nested in `data`, no pagination fields in `meta`, `limit`/`offset` ignored — `routes/reports.py:89,133`
- §3.4 — revise — mismatch — `SETUP` also refuses **verifying a redemption** with `ERR_PROGRAM_NOT_LIVE`; both `SETUP` and `FROZEN` gate the same four operations — `routes/redemptions.py:186-190`
- §3.7 — insert — ambiguity — the membership scope test precedes both body FK lookups, and `offer_id` resolves before `membership_id` — `routes/redemptions.py:48-52`
- §3.7 — revise — mismatch — verification puts `ERR_SCOPE_VIOLATION` before the state check, per §2.9's bands — `routes/redemptions.py:172,178`
- §3.7 — revise — mismatch — verification posture gate also refuses `SETUP` with `ERR_PROGRAM_NOT_LIVE` — `routes/redemptions.py:187-190`
- §3.7 — insert — ambiguity — `gross_amount_cents` carries no range bound of its own; the minimum-spend rule is its only floor — `routes/redemptions.py:176`
- §3.7 — insert — ambiguity — a verification (success or fraud-blocked) never touches the offer row, so its `updated_at`/`version` stand still even though derived inventory counts move — `routes/redemptions.py:214,227-235`
- §3.7 — insert — ambiguity — by contrast all four void paths do touch the offer row — `cascade.py:41-45`
- §3.8 — insert — ambiguity — `remedy_offered_cents` accepted from 0 upward with no upper bound, never compared against the redemption's economics — `routes/disputes.py:68`
- §3.8 — insert — ambiguity — a later response omitting `remedy_offered_cents` writes null over the earlier offer — `routes/disputes.py:78`
- §3.8 — insert — ambiguity — on partner termination the slots released down the agreement limb record `release_reason` `AGREEMENT_TERMINATED`, never `MERCHANT_TERMINATED`; only offers that had been `ACTIVE`/`PAUSED` release slots — `cascade.py:126,113-114`
- §3.9 — insert — ambiguity — an `EmployerAdmin` listing statements reaches only its own `employer_id` whatever filters it supplies — `routes/statements.py:92`
- §3.9 — insert — ambiguity — re-finalize clears `reopen_reason` but deliberately leaves `reopened_at` standing — `routes/statements.py:133`
- §3.9 — revise — mismatch — ledger `employer_id` is null on **both** placement-fee types without exception and every redemption-derived entry copies the redemption's; `statement_id` is stamped once at write time, so only merchant-fault-resolution entries can carry one — `cascade.py:13-26,89-95,181-200`, `routes/slots.py:192-198`, `routes/redemptions.py:236-252`

Already pinned (no change): `routes/ledger.py` in full; cascade void/suspend reason codes, refund sign, expire eligible-status set, `MERCHANT_SUSPENDED`/`OFFER_PAUSED` pause, threshold-only-on-rescore suspension, five-level merchant-fault ordering; statements basis sets, half-open windows, five totals, no rounding at that level, `reversal_adjustment_cents` scoping, `statement_id` first-claim stamping, state-before-temporal finalize, finalize/pay segregation; reports population, grouping, category ASC ordering, inclusive floor, null-out shape, totals-include-suppressed, 8/2 floors; disputes state machines, 120-hour deadline reset, 2-request cap, `ERR_CREDIT_EXCEEDS_NET`, `NO_FAULT` forced-zero branch; redemptions reservation sequence, fraud two variants, line economics, persisted `FAILED` outcome, four void reasons, list-filter narrowing.

### Orchestrator final verification

- `wc -lc`: PRD.md 513/112,956 · PRD_FINALIZED.md 513/113,411 · PRD_COMPLETED.md 513/128,283.
- `cmp`: PRD_FINALIZED.md differs from PRD.md; PRD_COMPLETED.md differs from PRD_FINALIZED.md — neither step produced a byte-identical no-op.
- PRD_COMPLETED.md tail is the final §5 error-table row `| `ERR_EXCLUSIVITY_TERMS_MISSING` | 422 |` — not truncated.
- `workspace/implementation/` mtimes are unchanged since Step 6 generation (Step 7 applied no implementation fixes; Steps 8–9 are documentation-only), so the orchestrator-verified 8-round sweep of 132/132 still describes the shipped code.
- `workspace/implementation/results.{1..8}.json` all present, all 132/132.
- No stray `test_*` directories under `workspace/`; `test_helpers/` and `test_suite/` are at the task root.

Pipeline complete through Step 9.
