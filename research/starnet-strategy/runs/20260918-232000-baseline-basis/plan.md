# Baseline: public consensus sensitivity

Measure one nonzero initial weight (10) per node on path5, star6, cycle6,
clique5, barbell7, preferential-attachment9. No intervention, 100 budget,
zero LLM calls, two HTTP requests per measurement. Compare empirical coefficients
to degree+1 normalized within each connected component. Script: probe_consensus.py.

Do not inspect server internals. This identifies an empirical proxy, not a proof
of hidden evaluator mechanics. Next validate arbitrary weights and changed graphs.
