# P9 candidate-generation development result

## Decision

Reject both candidate-domain variants. Neither is eligible for production or
confirmation. The P8 source, qualification, runtime, and submission config were
not changed by this experiment.

The protocol was fixed in
`experiments/manifests/p9-candidate-generation-development-20260913.json` before
the screen. The implementation commit `92b0541` was created after the 501 jobs
had started, rather than before measurement as required by the autoresearch
workflow. The strategy files had already been written; the later commit also
added progress persistence and cross-variant rollout-cache reuse. This ordering
error is disclosed rather than treating the screen as a fully compliant run.
The 502--503 expansion started after commit `1604b48` recorded the screen.

## Results

All cases use the 22 existing P8 development families, the standard response
stratum, 50 nodes, 100 initial budget, and paired seeds. P8 conservative is the
primary comparator.

| Cohort | Variant | Pairs | Mean delta vs P8 | Win / tie / loss | Worst | Failures |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| screen 501 | depth2 | 22 | +0.449316 | 1 / 21 / 0 | 0.000000 | 0 |
| screen 501 | portfolio | 22 | +0.449316 | 1 / 21 / 0 | 0.000000 | 0 |
| expansion 502--503 | depth2 | 44 | 0.000000 | 0 / 44 / 0 | 0.000000 | 0 |
| expansion 502--503 | portfolio | 44 | -0.022590 | 0 / 42 / 2 | -0.768176 | 0 |
| combined 501--503 | depth2 | 66 | +0.149772 | 1 / 65 / 0 | 0.000000 | 0 |
| combined 501--503 | portfolio | 66 | +0.134710 | 1 / 63 / 2 | -0.768176 | 0 |

The preregistered expansion rule required a positive mean over P8 on
repetitions 502--503. Depth2 returned exactly zero and portfolio was negative,
so both fail. Reserved repetitions 801--805 remain unopened.

## Attribution

The only depth2 change was `lollipop/501`. At the first post-scan action it chose
cut `2-17` instead of cut `13-33`, producing +9.884950 final score. Its five
scenario estimate was +10.242545 mean with +5.856071 minimum. Repetitions 502
and 503 showed no change, so this is a one-seed development observation.

Depth2 uses a two-level budget search only to nominate its first action. The P9
rollout then resumes public greedy immediately; it does not evaluate or execute
the second structural action from the plan. Therefore this experiment tests a
better first-action proposal, not the intended two-action structural
complementarity. A full-prefix experiment must simulate the complete structural
prefix before the common continuation and define how each later real action is
revalidated.

Portfolio's two losses were `grid_lattice/502` (-0.225885) and `/503`
(-0.768176). They came from the added `observed_comm_roi` candidate. The first
known response made that immediate communication look better, but the future
path still depended on assumed responses for untried nodes. Five paired prior
scenarios predicted nonnegative deltas, while the realized hidden response
draws made the reordered communication portfolio slightly worse. Adding more
communication representatives therefore increases exposure to response-model
error without demonstrated upside.

The local environment used by these already-running jobs did not clamp opinion
updates to `[-100, 100]`. This is a known evaluator-model defect discovered
during the run. It cannot affect this cohort: across all 22 families and
repetitions 501--503, the maximum possible node opinion after all three positive
communications is `max(initial_w + 26.25*r) = 64.605882`; zero of 66 seeds can
reach +100. This evidence does not validate the uncapped runner for a new
high-opinion distribution.

The results support two next mechanisms outside this frozen experiment: test a
complete structure prefix rather than only its first action, and validate future
policies on bounded high-opinion distributions where communication saturation
changes marginal value.
