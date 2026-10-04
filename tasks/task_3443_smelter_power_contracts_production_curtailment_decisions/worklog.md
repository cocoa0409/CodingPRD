# Worklog — task_3443_smelter_power_contracts_production_curtailment_decisions

## Step 1: Create Task Directory — 2026-10-02T03:49:00.000Z

Pre-allocated task directory confirmed at ./tasks/task_3443_smelter_power_contracts_production_curtailment_decisions with workspace/ inside (no new index computed; no other task_* directory created).

## Step 2: Generate Scaffold — 2026-10-02T04:57:00.000Z

All three artifacts are generated, verified, and lint-clean. Final report:

## Deliverables (all in `/home/ubuntu/github/CodingPRD/tasks/task_3443_smelter_power_contracts_production_curtailment_decisions/`)

**SCAFFOLD.yaml** (1901 lines) — `domain_name: smelter-power-curtailment`, `api_prefix: /smelter-ops`. Pricing-engine archetype blended with posture-driven gating; flat topology; cyclic state machines; segregation-of-duties role model; immediate consistency. Complexity layers: dual-variant calculation, cascading side effects, optimistic concurrency, rate/threshold triggers.
- 12 entities: Smelter, Potline, PowerContract, PriceObservation, InterruptEvent, HedgePosition, AluminaSupplyAgreement, CurtailmentDecision, RestartPlan, EnvironmentalPermit, LaborAgreement, ProductionPlan
- 8 state machines (Potline full curtail→idle→shutdown→restart cycle; CurtailmentDecision approval chain with reject→revise loop, supersede, execute/reverse; plus contract/permit/hedge/plan/agreement lifecycles with clock-driven lazy EXPIRED transitions)
- 7 calculations with executed, pinned constants (FORWARD vs SETTLED power cost; hourly-round-then-sum settlement with LOSS_FACTOR 1.037 chosen specifically to avoid float-tie fragility; COST_PLUS vs MARKET_LINKED transfer pricing; multifactor margin gate; HOT/WARM/COLD restart cost; hedge coverage; tiered product-mix margin)
- 25 ordered validation rows (auth → authz → existence → SoD → OCC → state → safety → temporal → constraint → referential → fiscal), 24 error codes, 7 opaque roles, 40 endpoints (29 business + 10 reverse-reachability GETs + 1 `/_clock/set_current_utc` with the mandated 2026-09-01T00:00:00Z default)
- 2 OCC concurrency rules (decision-create on Potline.version, plan-create on Smelter.version — both true create-with-supersede races)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (1012 lines) — exactly 2 grounded instances per each of the 9 difficulty rules (18 total), every rule honoring its differentiation clause (different entity domains, different modes (a)/(b), different entities, different triggers with depth-3 and depth-2 cascades, different error-category pairs, different metrics/endpoints, different entity pairs, different interval semantics, different conserved quantities). All formula-derived asserts are literals computed by executing the formulas (e.g., forward 43.50 vs settled 38.92; settlement 133325.04 vs naive 133325.02; WARM restart estimate 467500; margin 137.60 with avoidable loss 12.40).

**SCAFFOLD_CORNER_DESIGN.yaml** (2819 lines) — 51 entries across all nine taxonomy sections (44 active instances + 7 `excluded_because` stubs pointing at §1.8 instances), covering required/system fields, immutability, invalid transitions, terminal lockdown, idempotency, selector tie-breaks, aggregate uniqueness, SoD identity checks, RBAC denials, envelope shape, pagination defaults, OCC stale/supersede pairs, derived-field reconciliation, and immediate consistency.

## Verification
- `scaffold_lint.py` verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (40 endpoints, 12 entities, 18 + 44 instances, 449 calls scanned)
- Additional audits passed: no forbidden concurrency vocabulary, zero name collisions across 69 instances, all `grounds:` refs resolve, no orphan error codes, enum closure on all 8 state machines, file-split honored (neither design key appears in SCAFFOLD.yaml), and every setup chain replays cleanly against the declared state machine, validations, and logical-clock default.

One judgment call to note: the scenario is broad, so I kept the endpoint surface at the 40-endpoint safety ceiling (per the repo memory about >40 breaking impl-gen) by folding SPL disposal into the permit gate and relocating the rounding-order difficulty rule onto monthly power settlement rather than adding a disposal-campaign entity.

Orchestrator verification: all three files exist, parse as YAML, SCAFFOLD.yaml has api_prefix `/smelter-ops`, domain `smelter-power-curtailment`, neither design key inside, 40 endpoints; both design files carry their single mandated top-level key.

## Step 3: Copy Shared Files — 2026-10-02T04:59:00.000Z

Copied ./INSTRUCTION.md to tasks/task_3443_smelter_power_contracts_production_curtailment_decisions/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T05:20:00.000Z

PRD generation complete. All three hard contracts pass.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3443_smelter_power_contracts_production_curtailment_decisions/workspace/PRD.md` (314 lines, ends at §5 Error Code Catalogue — no audit footer). The two withheld design-index files were never opened or referenced.

**Structure:** §1 two-paragraph introduction (business-context angle); §2 with 11 subsections including a domain-derived logical-clock/lazy-expiry section (2.4, carries the exact `2026-09-01T00:00:00Z` startup default and the unprefixed `/_clock/set_current_utc` mount), a full 25-step Request Evaluation Order (§2.7) transcribing every `validations[].priority`, OCC (§2.8), pinned rounding orders (§2.9), market-data selector/tie-break rules (§2.10), and derived-state/computed-read rules (§2.11); §3 with 9 workflow-grouped subsections covering all 8 state machines, 7 calculations (FORWARD/SETTLED power cost, per-hour-rounded monthly settlement, transfer pricing, margin gate with constants 1.92/13.5/420/150, HOT/WARM/COLD restart schedule, hedge coverage, product-mix tiers), and both OCC rules; §4 minimal 4-column table (all 40 endpoints); §5 two-column table (all 24 errors).

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 98 required, 98 present, 0 missing (incl. component/allocation/snapshot inner fields)
- endpoints[].request_body: all present (incl. to_iso8601, expected_potline_version, expected_smelter_version, reason, closed_price_usd)
- endpoints[].query_params: limit, offset present, 0 missing
- enum/state values: 53 required, 53 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 25 checked, 25 expressed in §2.7 ordered prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (endpoint capability + expected_<parent>_version + ERR_STALE_VERSION/412), no race framing, 0 missing
- state_machines[].transitions: 26 checked, 26 fully expressed (from/to, actors, preconditions+error_id, side effects incl. version bumps and the 3-link execute cascade), 0 missing
- calculations[]: 7 checked, 7 fully expressed with all constants and pinned rounding orders, 0 missing
- validations[] conditions: 25 checked, 25 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (supersede cascades, parent-version bumps on gated creates, read-null vs write-error split for ERR_NO_PRICE_OBSERVATION), 0 missing
- entities[].fields[] structured content: defaults/initials/nullability reconstructible (take_or_pay_pct 0.9, community_impact_clause false, common_fields:false pair carry only id+created_at), 0 missing
- sibling-branch symmetry: curtail 5-branch depth matrix, dual reject states, dual restart sources, 3 lazy expiries all at equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 437
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Two repairs were needed post-draft and applied: naming the bare `status` field and the `COMPLETED`/`SUSPENDED` target states, and explicitly tying shutdown/start state-mismatch failures to `ERR_POTLINE_INVALID_STATE`/`ERR_RESTART_PLAN_INVALID_STATE`. Note one scaffold quirk transcribed faithfully: validation priorities 12/13 place the labor notice-period check ahead of the agreement-presence check on execute; the PRD states this declared order verbatim rather than "fixing" it.

Orchestrator verification: PRD.md is 313 lines; `/smelter-ops` appears 41×; `/_clock/set_current_utc` documented at line 243 as outside the business prefix; 74 `ERR_` mentions.

## Step 5: Generate Unit Tests — 2026-10-02T05:45:00.000Z

Generation complete and fully verified. Summary:

## Output

**`test_helpers/`** (9 files, all compile):
- `types.py` — 12 entity TypedDicts + status/role enums; `PriceObservation`/`InterruptEvent` carry only `id`+`created_at` (append-only, per PRD §2.5)
- `api_client.py` — one method per endpoint; clock endpoint mounted **unprefixed** (`/_clock/set_current_utc`), all business endpoints under `/smelter-ops`
- `api_errors.py` — all 24 error IDs with HTTP map, registered via `set_error_http_status_map`
- `assertions.py`, `factories.py`, `constants.py` (all PRD calc constants: INTERRUPTIBLE_DISCOUNT_PCT 0.25, LOSS_FACTOR 1.037, margin-gate constants, restart class schedule, HEDGE_MIN_COVERAGE 0.5, DEFAULT_CLOCK `2026-09-01T00:00:00Z`)
- `test_users.py` — 7 role headers + per-instance builders for SoD user-id threading (all roles are `opaque`, so no entity-backed ownership threading is needed)
- `fixtures.py` — tiered composites: `setup_site`, `setup_idled_potline`, `setup_planned_restart`, `propose_decision` (re-reads live potline version for OCC), `approve_decision` (segregated ctrl-1/vp-1), `setup_approved_decision`, `setup_executed_decision`, `setup_executed_and_reversed`, `post_standard_price_set`, `set_clock`

**`test_suite/`** — `conftest.py` + 11 test files, **80 tests**, `pytest --collect-only` passes.

## Coverage audit (machine-verified)
- **Queue A (difficulty):** all 18 instances have exactly 2 tests each (36 tests)
- **Queue B (corner):** all 44 non-stub instances have exactly 1 test; all 7 `excluded_because:` stubs untranslated and their `difficulty_instance` pointers resolve
- Every test has exactly one `Design:` tag resolving to a real instance; no unknown tags
- **Zero instances skipped** — all 62 passed the PRD-first two-condition filter
- Every docstring citation survives a whitespace-normalized literal grep of PRD.md (initial run caught 4 fabricated RBAC table paraphrases; fixed by quoting the exact §4 authorization-table rows verbatim)
- No `skip`/`skipif`/`xfail` anywhere; no "scaffold" references in generated code

## Key decisions
- `executed_at` assertions compare **parsed instants** against `2026-09-01T00:00:00Z` (the pinned default clock), not string equality — the instant is uniquely derivable, the serializer's fractional-digit format is not
- All fixture dates are reachable from the default clock: contract windows `[2026-01-01, 2027-01-01)`, observations ≤ clock, hedge/plan months ≥ 2026-09, restart planned dates ≥ (possibly advanced) clock; non-default clocks (09-02, 09-03, 09-06, 09-10, 09-11) are set inside each test that needs them since the server restarts per test
- Priority-pair tests (state-beats-permit, notice-beats-hedge) cite the verbatim §2.7 numbered items plus the masking sentence, satisfying the asserted-ordering rule

Orchestrator verification (independent): all 21 python files compile; api_client mounts `/_clock/set_current_utc` unprefixed with zero wrongly-prefixed occurrences; AST tag audit — 80 tests, 62 valid non-stub instances (18 difficulty + 44 corner) + 7 stubs, no bad tags, no uncovered instances; the 18 tag "duplicates" are exactly the sanctioned 2-tests-per-difficulty-instance pattern (36 + 44 = 80).

## Step 6: Generate Implementation — 2026-10-02T06:15:00.000Z

Done. The implementation is complete, compiles, and passed a full end-to-end smoke test on a dynamic port (server killed by exact PID afterward).

## What was built

`/home/ubuntu/github/CodingPRD/tasks/task_3443_smelter_power_contracts_production_curtailment_decisions/workspace/implementation/` — Python + Flask, 20 source files, per-domain modules:

- **Foundation**: `app.py` (factory + error handlers, `0.0.0.0:$PORT`), `start.sh` (guarded pip install, `exec python3 app.py`), `db.py` (empty in-memory store + server-owned logical clock defaulting to `2026-09-01T00:00:00Z`), `errors.py` (full 24-id catalog from PRD §5), `envelope.py` (exact `meta`/`response_type`/`data` envelope, pagination fields), `auth.py` (`X-User-ID`/`X-User-Role`, 7 roles), `util.py` (ISO-8601 parse/format, Decimal helpers, pagination 10/0, 1–100), `constants.py` (single definition site for every PRD constant).
- **Services**: `core.py` (lazy EXPIRED transitions with version bumps, posture/derived fields, restart class, contract-year bounds), `pricing.py` (FORWARD/SETTLED effective cost, round-per-hour-then-sum monthly settlement with LOSS_FACTOR 1.037 and 25% interruptible discount, transfer price), `decisions.py` (margin gate snapshot with 1.92/13.5/420/150 constants), `restart.py` (HOT/WARM/COLD schedule, whole-day flooring, crew cost).
- **Routes**: 12 blueprints covering all 39 business endpoints under `/smelter-ops` plus `POST /_clock/set_current_utc` unprefixed.

## Key fidelity decisions (PRD over scaffold where they diverged)

- **Execute gate order**: notice period checked before agreement presence (rule 12 < 13), implemented as: agreement exists + notice unmet → 422 `ERR_LABOR_NOTICE_PERIOD`; no agreement → 409 `ERR_LABOR_AGREEMENT_INACTIVE`.
- **SoD before state** on the two approve endpoints (rule 4 < 8).
- **All-FIXED settled cost** returns `f/total_mw` regardless of observations (per the scaffold's variant-neutral "regardless of observations" clause); null only when market-exposed and no in-month obs.
- Interrupt event window rule per PRD prose: `start_at >= window_start`, `end_at > start_at`, both `<= clock` (no `end_at <= window_end` constraint).
- RESTARTING potline class uses the downtime origin captured at plan start (handles stale `last_full_shutdown_at` after a restart cycle).

## Verification performed

- `py_compile` on all 20 files — clean (one real bug found and fixed: `plan_json` vs `production_plan_json` import mismatch in two route files).
- Constant audit: each of 17 named constants defined exactly once in `constants.py`; zero literal leaks elsewhere.
- Error-catalog audit via AST walk: all 24 catalog ids are raised; nothing raised is uncatalogued (no KeyError→500 path).
- Live smoke test on a dynamic port: 401/403/404/409/412/422 error paths, clock set, contract activate + overlap semantics, potline power gate, decision pipeline (OCC 412, SoD 403, notice 422, execute cascade with `take_or_pay_exposed` flip, reverse), emergency curtail/idle, shutdown gating, restart flow with SPL permit gate, hedge close P&L, lazy expiry, pagination meta — all correct, including exact numbers (margin 1001.75, estimate 82000, actual 112000, P&L 300000, month settlement 218400).
- No test_suite/, test_helpers/, or design files were touched; no seeding at startup.

Orchestrator verification (Step 6→7 hand-off constant grep): impl and test_helpers constants identical for every shared literal (LOSS_FACTOR 1.037, INTERRUPTIBLE_DISCOUNT_PCT 0.25, ALUMINA_RATIO 1.92, POWER_INTENSITY 13.5, OTHER_CONVERSION 420, RESTART_RESERVE 150, HEDGE_MIN_COVERAGE 0.5, WARM 24 / COLD 720, CREW 15000, BILLET/SLAB/VA 180/220/350, capacity factor 30, default clock 2026-09-01T00:00:00Z); RESTART_CLASS_SCHEDULE dicts byte-identical; impl VA_PREMIUM tiers 120/180/240 match PRD §3 prose; all impl files compile; clock blueprint registered unprefixed, all 11 business blueprints under `/smelter-ops`.

## Step 7: Run Tests and Iterate — 2026-10-02T06:12:00.000Z

All 8 rounds pass 80/80. The `results.*.json` files remain in `workspace/implementation/` per the output contract.

## Summary

- **Iterations run:** 2 (initial sweep: 78/80 × 8 rounds, same 2 tests failing in every round; post-fix sweep: 80/80 × 8 rounds, clean).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_3443_smelter_power_contracts_production_curtailment_decisions/test_helpers/factories.py` — `create_alumina_agreement_payload`: made the defaults pricing-model-aware. Previously the factory unconditionally defaulted `base_cost_per_tonne`/`markup_pct`, so any override to `pricing_model="MARKET_LINKED"` left those forbidden fields in the payload and the implementation correctly rejected it with `ERR_INVALID_REQUEST`. Now a `MARKET_LINKED` payload defaults to `market_discount_pct` only (no cost-plus fields); `COST_PLUS` keeps the original cost-plus defaults. This fixed both `test_cost_plus_transfer_price` and `test_market_linked_transfer_price_diverges` (they share `_setup_two_agreements`, whose MARKET_LINKED leg tripped the 400 in setup — consistent with the triage-hint pattern of one fixture bug masquerading as multiple implementation bugs).

- **Fixes applied to `implementation/`:** none — the implementation's conditional-shape rejection was PRD-faithful. PRD §3.4 states verbatim: "`MARKET_LINKED` requires `market_discount_pct` (a fraction at least 0 and strictly below 1) and forbids both `base_cost_per_tonne` and `markup_pct`. Violating the conditional shape is rejected with `ERR_INVALID_REQUEST`."

Orchestrator verification: all 8 results.*.json present showing 80/80 passed, written 06:11:43 — after the only fix (test_helpers/factories.py 06:09:17) and after the newest implementation/ source write (06:00:33, Step 6 era). Sweep post-dates every change; implementation/ untouched by Step 7.

## Step 8: Finalize PRD — 2026-10-02T06:15:00.000Z

All verification is complete. Zero edits are warranted — this matches the explicitly permitted zero-edit outcome.

**Summary**

- **Line counts / %-delta:** PRD.md = 313 lines; PRD_FINALIZED.md = 313 lines; 0.0% delta. Verified byte-identical via `diff -q` and `cmp`.

- **Changes made:** none. PRD_FINALIZED.md is a byte-identical copy of PRD.md.

- **Per-item analysis of the single `<step_7_diff>` item** (test_helpers/factories.py `create_alumina_agreement_payload` made pricing-model-aware; no implementation/ fixes; no test deletions):
  - **(a) Subject:** conditional parameter shape for AluminaSupplyAgreement creation by `pricing_model` — which fields each model requires/forbids and the rejection error.
  - **(b) Impl paths enumerated and read:** `workspace/implementation/routes/alumina.py` lines 15–70 (the `POST /smelter-ops/alumina-agreements` route — the Step 7 site): COST_PLUS branch requires `base_cost_per_tonne` + `markup_pct` (markup >= 0) and rejects `market_discount_pct` with `ERR_INVALID_REQUEST` (lines 32–41); MARKET_LINKED branch requires `market_discount_pct` in [0, 1) and rejects `base_cost_per_tonne`/`markup_pct` with `ERR_INVALID_REQUEST` (lines 42–56). Off-site paths touching the same fields: `workspace/implementation/services/pricing.py` lines 133–142 (`transfer_price`: COST_PLUS = base × (1+markup), index ignored; MARKET_LINKED = latest GLOBAL ALUMINA_INDEX × (1−discount), None when no observation; `round2_dec` half-up) and `workspace/implementation/serializers.py` line 140 (read-side echo of `market_discount_pct`). Also `test_helpers/factories.py` lines 78–104 (the fixed fixture, whose own comment cites PRD §3.4).
  - **(c) Wording adjustment:** none needed. PRD §3.4 (PRD.md line 187) already states verbatim: "The two models carry mutually exclusive parameter sets: `COST_PLUS` requires `base_cost_per_tonne` ... and `markup_pct` (the inter-segment markup fraction, zero or more) and forbids `market_discount_pct`; `MARKET_LINKED` requires `market_discount_pct` (a fraction at least 0 and strictly below 1) and forbids both `base_cost_per_tonne` and `markup_pct`. Violating the conditional shape is rejected with `ERR_INVALID_REQUEST`." PRD line 189 likewise pins the read-side price computation verbatim. The implementation matches both passages exactly; the Step 7 failures were caused solely by the fixture's unconditional cost-plus defaults leaking forbidden fields into MARKET_LINKED payloads. This is a pure fixture bug — no PRD silence, no PRD/impl mismatch — so no edit was made.

Orchestrator verification: `diff -q workspace/PRD.md workspace/PRD_FINALIZED.md` confirms byte-identical; PRD.md line 187 independently read and contains the quoted conditional-shape sentence; 0 implementation/*.py files newer than results.8.json (impl untouched post-sweep).

## Step 9: Complete PRD — 2026-10-02T06:28:00.000Z

The diff is exactly the 14 intended hunks and nothing else. The task is complete.

## Summary

**Source vs output:** `PRD_FINALIZED.md` (identical to `PRD.md`) → `PRD_COMPLETED.md`. 313 → 315 lines; 52,082 → 54,646 chars (+2,564). All changes are inline sentence-level inserts; no new sections, no deletions.

**Counts:** 14 ambiguity-pins, 0 mismatch-revisions. I found no place where the PRD describes behavior the implementation contradicts — every divergence was PRD silence on a corner the impl had to resolve, so the adjudication rule's mismatch branch never triggered, and there are no impl gaps to report.

**Walk list (everything enumerated):**
- Route modules (12): `clock.py`, `smelters.py` (create/read + 7 child lists), `potlines.py` (create/read/curtail/shutdown + 2 child lists), `contracts.py` (create/read/activate, interrupt-event create/list), `prices.py`, `hedges.py` (open/close), `alumina.py`, `decisions.py` (propose/economic-approve/labor-approve/reject/revise/execute/reverse), `restarts.py` (create/start/complete), `permits.py` (create/suspend), `labor.py` (register/expire), `plans.py`. All 35 routes verified against the §4 table including role sets and 200/201 statuses.
- Service functions: `services/core.py` (3 lazy expirations, posture, curtailed capacity, open hedged tonnes, coverage ratio, restart class, covering-contract/labor/permit selectors, contract-year bounds, take-or-pay), `services/pricing.py` (forward, settled, month-to-date settlement, transfer price, interruptible hours), `services/decisions.py` (economics snapshot), `services/restart.py` (estimated/actual cost, whole-day counting).
- Serializers (12 shapes, incl. `fmt_iso` vs `fmt_wall` distinction); every `raise_err` site diffed against `ERROR_CATALOG` (all 24 catalog ids raised, no orphan raises); auth middleware; envelope; pagination parser; constants diffed against PRD values (all match).

**One bullet per change (all `insert`/`revise` = ambiguity-pin):**
- §2.3 — insert — ambiguity — pagination rejects non-integer/out-of-range `limit`/`offset` with `ERR_INVALID_REQUEST`; `created_at` ties break by `id` ascending; `has_more` = `offset + returned < total_count` — impl `util.py:163-183`, `envelope.py:24-34`, `smelters.py:62-68`
- §2.4 — insert — ambiguity — clock-set accepts any instant, not necessarily after the current reading — `routes/clock.py:14-18`
- §2.5 — insert — ambiguity — echoed client/logical-clock timestamps render canonical ISO with fractional part only when nonzero; 3-fractional-digit rule applies to `created_at`/`updated_at` — `util.py:33-44`
- §2.8 — insert — ambiguity — OCC gates are exact-equality both directions; missing/non-integer `expected_*_version` → `ERR_INVALID_REQUEST` before comparison — `decisions.py:48-58`, `plans.py:42-52`
- §2.10 — revise — ambiguity — `price_usd` with >2 decimal places rejected `ERR_INVALID_REQUEST` — `prices.py:33-37`
- §2.11 — insert — ambiguity — a `RESTARTING` line's `restart_cost_class` uses the downtime origin captured at plan start against the same thresholds — `services/core.py:115-122`, `restarts.py:97-98`
- §3.1 — revise — ambiguity — `line_code` uniqueness is an operator convention, not server-enforced — `potlines.py:30` (no uniqueness check). Judgment call: PRD declared no error/§2.7 rule for duplicates, so I read "unique" as descriptive and pinned non-enforcement rather than reporting an impl gap
- §3.1 — revise — ambiguity — depth exactly 0 from `OPERATING` is rejected `ERR_CURTAILMENT_DEPTH_INVALID` — `potlines.py:83-87`
- §3.2 — insert — ambiguity — interrupt-event recording is not gated on contract status; a contract with no `INTERRUPTIBLE` component rejects with `ERR_INVALID_REQUEST` — `contracts.py:146,164-171`
- §3.3 — insert — ambiguity — settled variant at exactly month start (zero elapsed hours) degenerates to the latest in-window observation's price — `services/pricing.py:76-78`
- §3.3 — insert — ambiguity — settlement bills only whole elapsed hours; an hour with no observation at-or-before it prices at the earliest observation at or before the clock — `services/pricing.py:106-114`
- §3.5 — revise — ambiguity — reject's optional `reason` is accepted but neither persisted nor surfaced — `decisions.py:137-146`, `serializers.py:148-165`
- §3.5 — insert — ambiguity — revise does not re-check potline status, does not supersede other decisions, and re-applies creation's missing-data rejections via snapshot recompute — `decisions.py:149-169`
- §3.7 — revise — ambiguity — `closed_price_usd` carries no positivity constraint — `hedges.py:89-91`
- §3.1 / §3.8 — revise — ambiguity — `labor_headcount` and `notice_period_days` are integers — `smelters.py:40`, `labor.py:22` (counted as two edits, one pin class)

**Notable non-changes (verified aligned, no edit needed):** §2.7 ordering is honored everywhere observable — including the restart `start` endpoint, where the PRD declares no potline-state gate (rule 6) for that action, so the impl's plan-state-before-permit order (rules 9→11, confirmed by `test_07`) is consistent; the impl's defensive potline checks in restart start/complete are unreachable dead code but contradict nothing. The same-error-id inversions (e.g. rule 15 vs 16 in hedge creation) are unobservable. Test-helper `constants.py` matches impl constants exactly (no drift).

Orchestrator verification: PRD_COMPLETED.md exists (315 lines, +2,564 chars — not a silent no-op); all 14 diff hunks independently read — every hunk is an inline sentence-level silence-fill, none deletes or softens an explicit PRD claim; the one flagged judgment call (§3.1 `line_code` uniqueness read as operator convention) is exonerated because PRD declares no error_id or §2.7 validation rule for duplicates, so enforcement was never uniquely derivable and inventing one impl-side is forbidden; 0 implementation/*.py files newer than the clean sweep (results files intact, 8/8) — the 80/80 × 8-round sweep remains valid.
