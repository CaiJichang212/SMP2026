# Optimization matrix

All files are public, self-built test seeds, not official hidden seeds. Never
pass their hidden fields (`r`, prompts, initial graph) to a participant model.

-120-125: development,50nodes,budget100.
-126-143: simulator holdout; official sandbox subset126,127,134,135,142,143.
-Topology determined by index modulo6: preferential attachment, small world,
 random, community, hub with path, disconnected path/small-world.
-Weights vary by regime: mixed, persona correlated, mostly positive, all negative.
-Prompt strengths: all six permutations; scales0.4,1,2; heterogeneous persona r.

Generator: `src/starnet/optimization_lab.py:make_matrix_seed`; locked NetworkX.
Files and SHA256 recorded in each matrix JSONL are the reproducibility authority.
The simulation is an empirical score approximation, not the official engine.
Real-LLM paired tests use120,124,134; selection and held-out roles are documented.
