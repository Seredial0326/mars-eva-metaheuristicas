"""pytest setup for the E1/E2 tests.

On Windows, PyTorch and conda's NumPy/SciPy (MKL) can each load their own Intel
OpenMP runtime; the second one aborts the whole test run inside SciPy's
L-BFGS-B unless KMP_DUPLICATE_LIB_OK is set (reported by Aaron on the board,
2026-11-14). pytest loads this file before the test modules, which import torch
first. src/ml/maxent_irl.py sets the same for the scripts.
"""
import os

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
