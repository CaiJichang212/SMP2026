# Explore: topology marginal score and budget completion

Lab-only prototype `src/starnet/optimization_lab.py`, excluded from submission.
Compare incumbent candidate heuristic with marginal-gain-per-cost greedy and
one-structural-action lookahead including remaining communication budget.
Enumerate legal shields and cuts, update all component influence weights after
each topology change. Positive node shields are allowed only if their net
estimated final outcome is beneficial; no fixed negative-weight threshold.

Development seeds120-125: six graph families, n50, budget100. Simulator first,
then official sandbox replay on identical JSON. Incumbent here means algorithmic
candidate-selection control without LLM, NOT the original ZIP's official score.
Save every action, seed hash, request trace, resource and budget metrics.

Holdout: indices126-143 vary positive/negative mixtures, hub sign, persona
correlation, effects and permutations. Never select on hidden platform seeds.
Candidate must beat incumbent paired mean without violating natural baseline;
report every regression and proxy error rather than suppress it.
