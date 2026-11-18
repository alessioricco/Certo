# Temperature tools

Write a small Python module `temps.py` with a pytest test file
`test_temps.py`.

1. `c_to_f(c)` and `f_to_c(f)` convert between Celsius and Fahrenheit.
2. `parse_reading("21.5C")` returns the value in Celsius as a float; it
   accepts a `C` or `F` suffix (converting F to C) and raises ValueError
   for anything else.

Tests must cover both parts, including the ValueError.
