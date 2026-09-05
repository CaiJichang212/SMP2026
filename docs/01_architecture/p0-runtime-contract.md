# P0 runtime contract

Development is locked to Python 3.12.3, casevo 0.3.19 (source commit
`d3b8d1f81fe0b3d41ff80908351bd5ebd6809155`), Mesa 2.4.0, NetworkX 3.6.1 and
ChromaDB 1.5.9. `uv.lock` is the dependency lock. The required constructor
signatures are checked by `uv run python scripts/preflight_runtime.py` before a
probe or submission build.

The checked contract is:

```text
ModelBase(tar_graph, llm, context=None, prompt_path='./prompt/',
          memory_path=None, memory_num=10, reflect_file='reflect.txt',
          type_schedule=False)
AgentBase(unique_id, model, description, context)
```

The submission passes a three-role collaboration graph, an absolute prompt
directory and `reflect.txt`. The outer model advances CaseVO time only after an
actual public environment action. It never calls `end_turn`, private APIs, or
`trigger_eval`.
