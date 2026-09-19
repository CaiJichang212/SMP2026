# Boundary fixtures

`seed-151-n100.json`:100nodes,budget200,250steps/calls; small-world topology with
persona-correlated initial weights. Generated with make_matrix_seed(151,100).

`seed-144-negative.json`:50nodes,budget100,120steps/calls; replace all prompt
effects by[-5,-10,-15] to test feedback-based rejection of further communication.

`seed-145-zero.json`:50nodes,budget100,120steps/calls; all prompt effects zero.

These are custom fixtures, not official hidden seeds. Their r/prompts/graph are
available only to the test harness and sandbox server, never the participant.

`seed-cut3-zero.json`: three-node path, weights[100,0,0], all-zero prompts,
budget20. Exercises actual LLM-authorized cut routing after feedback establishes
that communication is ineffective; no action is forced by the harness.
