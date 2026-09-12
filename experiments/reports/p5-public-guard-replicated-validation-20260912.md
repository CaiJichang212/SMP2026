# P5 comm->shield guard replicated validation (2026-09-12)

## Scope and score scale

The best supplied platform result is `765.8400` from
`starnet-public-greedy-experimental-20260908.zip`; it is not `761.9467`.
The requested `>900` is an official hidden-seed **raw average score** target.
The 100-point dynamic ladder score in `docs/00_rules/task-spec.md` is a later
relative mapping based on `BaseAvg` and the field's `MaxAvg`. Local
`LocalPublicEnvironment.evaluate()` values are terminal-score screening
outputs. Neither the 100-point formula nor a local terminal score can be used
to claim that the official raw target has been reached.

The `765.8400` archive used `llm_schedule: off` and three configured roles.
Under the clarified rule that every agent's final decision must be made by an
LLM, it is a historical strategy-shape control and must not be resubmitted as
a compliant candidate. Relative to the current shape, that archive also used
a first-response prior of `15` instead of `12.75`, lacked the newer structural
risk gate, and lacked the `min_observed_responses=4` / ROI `1.25` defaults.
Those coupled differences prevent attributing its platform result to one
parameter.

## Design

The candidate suppresses communication to a node only when the same current
public state contains a legal, positive-gain shield for that node. Every
`(block, family, node_count, repetition)` is paired against the current
`public_greedy`. A third, guard-disabled implementation must reproduce the
production controller within `1e-8`; this detects experiment-runner drift.

Inference uses the topology-family mean as the bootstrap unit (10,000 draws,
seed `20260912`). Repetitions are not treated as independent topology samples.
The inherited promotion gate requires zero candidate failures, exact
guard-disabled reproduction, every family mean nonnegative, and a strictly
positive family-bootstrap 95% lower bound. The 50- and 100-node strata are
reported separately.

The three named `holdout` families already appeared in earlier reports. New
repetition IDs are unseen seeds within known families, not topology-disjoint
holdout evidence. A true generalization gate still requires new frozen graph
families or official hidden seeds.

## Results

This run evaluated 121 pairs (363 complete policy sessions). All candidate
sessions had zero failed actions, and all guard-disabled sessions reproduced
the production controller.

| Stratum | Pairs | Win/tie/loss | Pair mean | Min / max | Family-bootstrap 95% CI | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 50-node independent, r1-10 | 40 | 2/38/0 | +0.4973 | 0 / +12.6408 | [0, +1.4920] | fail: lower bound is zero |
| 50-node known-holdout, r1-10 | 30 | 2/27/1 | +2.5756 | -1.7784 / +46.7862 | [-0.1778, +7.9047] | fail: negative family mean and CI |
| 50-node known-family confirmation, r11-20 | 30 | 3/26/1 | +0.9929 | -107.2779 / +72.1781 | [0, +2.9787] | fail: lower bound is zero |
| 100-node independent, r1-3 | 12 | 2/10/0 | +6.4424 | 0 / +62.7898 | [0, +19.3272] | fail: lower bound is zero |
| 100-node known-holdout, r1-3 | 9 | 0/9/0 | 0 | 0 / 0 | [0, 0] | fail: no benefit |

The expanded 50-node known-holdout block first produced a negative
`double_bridge_communities` family mean of `-0.1778`. In the separately frozen
r11-20 confirmation, that family tied, while `negative_hub_spokes` averaged
`+2.9787`; however one seed lost `-107.2779`. The positive average is therefore
sparse and has a material left-tail risk. At 100 nodes the effect remained
confined to `tree_broom` in the independent block and disappeared entirely in
the known-holdout block.

## Conclusion and next experiment

The comm->shield guard does not pass the local promotion gate and should stay
disabled by default. Its zero-failure record and occasional gains make it a
useful experimental arm, but the evidence does not support expected progress
from `765.8400` to `>900`.

The most valuable next work is to diagnose the `negative_hub_spokes r11`
counterexample at the candidate/action-sequence level, then freeze new graph
families that stress redundant cuts, mixed-sign articulation regions, and
shield-after-persuasion interactions. A revised guard should enter official
paired testing only after every new family is nonnegative and the family-level
bootstrap lower bound is strictly positive. Platform raw averages remain the
only evidence for the `>900` objective.

## Reproduction and artifacts

```bash
UV_CACHE_DIR=/tmp/smp2026-uv-cache uv run python scripts/run_public_comm_shield_guard.py --block independent --repetitions 10 --output experiments/reports/p5-public-guard-50node-independent-r10-raw-20260912.json
UV_CACHE_DIR=/tmp/smp2026-uv-cache uv run python scripts/run_public_comm_shield_guard.py --block holdout --repetitions 10 --output experiments/reports/p5-public-guard-50node-known-holdout-r10-raw-20260912.json
UV_CACHE_DIR=/tmp/smp2026-uv-cache uv run python scripts/run_public_guard_confirmatory.py --block holdout --node-count 50 --first-repetition 11 --last-repetition 20 --output experiments/reports/p5-public-guard-confirmatory-raw-20260912.json
UV_CACHE_DIR=/tmp/smp2026-uv-cache uv run python scripts/run_public_guard_confirmatory.py --block independent --node-count 100 --first-repetition 1 --last-repetition 3 --output experiments/reports/p5-public-guard-100node-independent-r3-raw-20260912.json
UV_CACHE_DIR=/tmp/smp2026-uv-cache uv run python scripts/run_public_guard_confirmatory.py --block holdout --node-count 100 --first-repetition 1 --last-repetition 3 --output experiments/reports/p5-public-guard-100node-holdout-r3-raw-20260912.json
```

Frozen plans are in
`experiments/manifests/p5-public-guard-confirmatory-20260912.json` and
`experiments/manifests/p5-public-guard-100node-validation-20260912.json`.
