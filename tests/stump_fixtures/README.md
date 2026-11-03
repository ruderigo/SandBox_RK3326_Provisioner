# Stump test fixtures (from SandBox_Stump_On, MIT licence)

Copied unchanged from [SandBox_Stump_On](https://github.com/ruderigo/SandBox_Stump_On)
at 1.0.0-beta.47 (b1d0f6c), for `tests/test_stump.py`:

- `board_sim.py`: Team Stump's pretend board for Arborist's tests
  (`tests/arborist/board_sim.py`): MicroPython's raw REPL, raw-paste mode
  and soft reset over stdin/stdout. Here each piece of code is run by
  `tests/fake_micropython.py` (CPython standing in for MicroPython's Unix port).
- `settings.py`, `radio.py`, `store.py`, `lora_boards.py`: the Stump's own
  modules the board runs to write its settings and radio (the bundle holds
  them compiled; CPython runs these sources).

MIT License, Copyright (c) 2026 ruderigo.
