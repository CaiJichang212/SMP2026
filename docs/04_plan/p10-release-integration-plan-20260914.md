# P10 combined release integration draft

Status: review-only draft. It does not enable P10, alter the canonical entry or
config, change the current builder, or modify P9 qualification evidence.

## Activation contract

Add a separate `src/starnet/policy/p10_qualification.py` only after the frozen
48-case statistical gate passes and entry evidence is sealed. Its metadata is
independent of `p8_qualification.py`:

```python
from __future__ import annotations

P10_CERTIFIED_MODE = "combined"
P10_GATE_REPORT_SHA256 = "<sealed-p10-report-sha256>"
P10_GATE_REPORT_RELATIVE_PATH = "experiments/reports/<p10-release-result>.json"

def qualified_p10_mode(commander_description):
    if not isinstance(commander_description, dict):
        return None
    requested = (
        commander_description["experimental_p10_mode"]
        if "experimental_p10_mode" in commander_description
        else P10_CERTIFIED_MODE
    )
    if (P10_CERTIFIED_MODE == "combined"
            and requested == P10_CERTIFIED_MODE
            and isinstance(P10_GATE_REPORT_SHA256, str)
            and len(P10_GATE_REPORT_SHA256) == 64):
        return P10_CERTIFIED_MODE
    return None
```

This distinguishes a missing optional host field from an explicit unknown
value. Missing field selects the compiled, certified `combined` mode. Exact
`combined` also selects it. Explicit `None`, `plan_only`, `response_only`, or an
unknown future string closes P10 and retains qualified P9. With missing
qualification metadata, every input closes P10. Do not import `TypeAlias` or
use runtime-evaluated Python 3.10 typing names.

## Canonical entry patch

Import `qualified_p10_mode` and `P10RuntimeController`. Resolve P8 first, because
P10 is an augmentation of the qualified bounded P9 policy:

```python
p8_mode = qualified_p8_mode(commander_description.get("experimental_p8_mode"))
p10_mode = qualified_p10_mode(commander_description)
if p8_mode is not None and p10_mode is not None:
    controller_type = P10RuntimeController
    controller_options = {
        "p8_mode": p8_mode,
        "experiment_mode": p10_mode,
        "max_structures": 12,
        "beam_width": 4,
        "response_estimator": None,
        "require_stage_envelope": True,
    }
elif p8_mode is not None:
    controller_type = P8RuntimeController
    controller_options = {
        "p8_mode": p8_mode,
        "require_stage_envelope": True,
    }
else:
    controller_type = RuntimeController
    controller_options = {}
```

Keep `experimental_p10_mode` absent from canonical config so the released
default proves it does not depend on the host preserving a new optional field.
Tests must also deep-copy descriptions and verify explicit unknown values fall
back to `P8RuntimeController`, never unqualified `RuntimeController`.

## Builder and evidence

Keep the current P9 inline tuple and manifest unchanged for historical
verification. Define a distinct P10 inline order with these modules immediately
before the canonical entry:

1. `src/starnet/policy/public_response_mixture.py`
2. `src/starnet/policy/p9_prefix_experiment.py`
3. `src/starnet/policy/p10_structure_plan_experiment.py`
4. `src/starnet/runtime/p10_controller_experiment.py`
5. `src/starnet/policy/p10_qualification.py`

The production build must select P10 only when `qualified_p10_mode({})` returns
`combined` and the P10 verifier passes. P9 verification continues to reference
its existing report and `p8-release-sources-20260913.json`; it must not rewrite
or relabel those files. Add a new immutable P10 manifest containing:

- sealed P10 report path and SHA-256;
- all base P9 runtime source hashes;
- the five P10 module hashes above;
- canonical entry, config, and prompt hashes;
- validated unqualified assembled-model hash and final qualified-model hash;
- the selected mode `combined`, depth 12, and beam width 4.

The P10 verifier must require `statistical_gate_passed=true`, selected variant
`combined`, complete public-history/resource audit, real-LLM plan approval and
response activation, Python 3.9 real-framework evidence, and a completed release
seal. A statistical report with pending entry evidence cannot build P10.

Because changing qualification metadata changes the assembled model, seal in
two phases: validate an unreleased candidate with qualification disabled, then
permit only literal changes to the three P10 qualification metadata fields.
Reconstruct the pre-qualification model from the final assembly and require its
hash to equal the tested candidate. Apply this comparison to P10 metadata only;
do not overwrite or reinterpret P8 evidence.

## Local runner preservation

`run_baseline_openai.make_runner_controller` currently recognizes only P8. For
an eligible 50-node, 100-budget run, use `type(original)` and preserve:

```python
{
    "p8_mode": original.p8_mode,
    "require_stage_envelope": True,
    "experiment_mode": original.p10_experiment_mode,
    "max_structures": original.p10_max_structures,
    "beam_width": original.p10_beam_width,
    "response_estimator": None,
}
```

Passing `None` creates a fresh mixture ledger and prevents posterior state from
leaking between controller instances. `runner_policy_config` may still change
only the local step fuse. Ineligible node/budget envelopes fall back through the
existing runner behavior. Add output fields for P10 mode, search/error counters,
plan approvals/completions, and response activation.

## Required tests and final ZIP

Before enabling:

- absent/exact/unknown P10 mode truth table, with unknown mode retaining P9;
- only the commander description can explicitly override P10;
- Python 3.9 AST/import and top-level collision checks for the P10 inline order;
- P10 builder refuses missing, stale, pending, or statistically failed evidence;
- P9 builder/verifier still uses unchanged historical P9 evidence;
- baseline runner rebuild preserves combined/depth/width and starts a fresh ledger;
- generated single-file mock LLM legally approves one complete plan and every
  prefix action executes one per host step;
- invalid/forced-exception LLM output never starts a P10 prefix and falls back
  to the original P9 candidate set;
- real LLM on the target runtime approves and completes a plan, activates the
  response mixture where expected, and has zero action/planning/transport errors;
- final ZIP is tested directly under Python 3.9 real CaseVO and target runtime,
  with exact model/archive/source-manifest hashes and legal ZIP root members.

Forced-exception fallback is useful failure evidence but cannot serve as plan
execution evidence. No local result implies an official score improvement.
