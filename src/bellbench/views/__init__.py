# src/bellbench/views/__init__.py
"""What the Workbench and the tutorial show: views drawn from results, never a number of their own.

The modules here lay out what the rest of the package computes. `base` holds
the parts a view is made of and how they are shown; `stepper` steps through a
written circuit's ideal states; `show` draws a circuit before it runs; `result`
lays out one run's result; `compare` sets runs and a benchmark's runs side by
side; `lessons` holds the tutorial's views. Every number comes from a run's
record, its scores, its counts or a benchmark's comparison table.

The views import the rest of the package, and only `bellbench.workbench`, the
entry point a notebook imports, imports the views: the modules that compute
results never do.
"""
