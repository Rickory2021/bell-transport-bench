"""Smoke test: the package imports and the pinned Qiskit stack loads."""

import bellbench


def test_package_imports():
    assert bellbench.__version__


def test_qiskit_stack_imports():
    import qiskit
    import qiskit_aer
    import qiskit_ibm_runtime  # noqa: F401

    assert qiskit.__version__ == "2.6.2"
