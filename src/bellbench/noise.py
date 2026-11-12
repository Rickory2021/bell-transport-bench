# src/bellbench/noise.py
"""NoiseControl: a processor model's graph, ports, Target and noise model.

NoiseControl turns a processor file and a noise profile, with a scale factor,
overrides and the conditional channels, into what a run needs
(docs/DESIGN.md, sections 4 and 5):

- `graph`, `ports` and `edges`: the coupling graph, by qubit id.
- `target`: Qiskit's description of the processor, which compilation uses.
- `noise_model`: the Aer noise model the noisy simulation uses.
- `has_durations`: whether the model has timings, so a run schedules its
  circuit before simulating; a depolarising profile has none.

How each profile kind becomes a model:

- **snapshot**: every qubit and directed coupler takes the profile's values,
  then the overrides, then the scale. The Target goes through Aer's
  `NoiseModel.from_backend` without readout errors, and each qubit then gets
  its asymmetric readout error. The Target's measurement error is the mean of
  the two misread probabilities.
- **depolarising**: the Target holds only the graph and the gate set, and the
  model is one depolarising error after the named gate on every directed edge,
  with no readout error and no decay.

NoiseControl checks every value after the overrides and the scale, and raises a
ValueError naming the field instead of capping an invalid one: a probability
outside 0 to 1, T2 above 2 T1, a gate error below what the gate's decay alone
causes, or a gate error above the largest one Aer can build for that gate. Aer
would otherwise cap T2, or drop or cap that gate's error, without a warning.

An override is `{qubits, field, value}`, its field named by the profile's own
key path (OVERRIDE_FIELDS); a two-qubit override names a coupler and applies in
both directions, and durations cannot be overridden.

The conditional channels (CONDITIONAL_CHANNELS) are an input of their own, each
None or a probability, swept over a range rather than given a claimed value;
the scale leaves them alone. `reset_error` is the probability that a reset
leaves its qubit in |1>, applied after the decay that the reset's duration
already brings. A run whose circuit resets, or measures a qubit and acts on it
again, stops while the matching channel is None (docs/DESIGN.md, section 4).
`mid_circuit_measurement_error` raises NotImplementedError when set, until it
is built.

NoiseControl records each config file's path and content hash when it builds,
and its scale, overrides and conditional channels cannot change afterwards.
`export_as_yaml` returns that record as NoiseControl's part of the run YAML, and
`from_yaml` rebuilds a NoiseControl from it, refusing a file whose content hash
changed.
"""

import math
import numbers
from collections.abc import Mapping, Sequence

from qiskit.circuit.library import get_standard_gate_name_mapping
from qiskit.providers import BackendV2, Options
from qiskit.quantum_info import average_gate_fidelity
from qiskit.transpiler import InstructionProperties, QubitProperties, Target
from qiskit_aer.noise import NoiseModel, ReadoutError, depolarizing_error, pauli_error, thermal_relaxation_error

from bellbench.configs import check_unchanged, load_recorded, name_from_record, processor_graph

T1 = "qubit.t1_relaxation_time"
T2 = "qubit.t2_dephasing_time"
READS_1_WHEN_0 = "qubit.readout_error.reads_1_when_0"
READS_0_WHEN_1 = "qubit.readout_error.reads_0_when_1"
QUBIT_FIELDS = (T1, T2, READS_1_WHEN_0, READS_0_WHEN_1)
PROBABILITY_FIELDS = (READS_1_WHEN_0, READS_0_WHEN_1)
GATE_ERROR_FIELD = "gates.{gate}.error_probability"
OVERRIDE_FIELDS = QUBIT_FIELDS + (GATE_ERROR_FIELD,)

CONDITIONAL_CHANNELS = ("reset_error", "mid_circuit_measurement_error")

STANDARD_GATES = get_standard_gate_name_mapping()


class NoiseControl:
    """One processor model under one noise profile, with its scale, overrides and conditional channels."""

    def __init__(
        self,
        processor: str,
        noise: str,
        scale: float = 1.0,
        overrides: Sequence[Mapping] = (),
        conditional: Mapping | None = None,
    ):
        self.processor_name = processor
        self.noise_name = noise
        self.processor, processor_record = load_recorded("processor", processor)
        self.profile, noise_record = load_recorded("noise", noise)
        self._records = {"processor": processor_record, "noise": noise_record}
        self.kind = self.profile["kind"]
        if self.kind not in _BUILDERS:
            raise ValueError(f"noise profile {noise!r}: unknown kind {self.kind!r}; known: {', '.join(_BUILDERS)}")

        self.graph = processor_graph(self.processor)
        self.ports = tuple(self.processor["ports"])
        self.edges = tuple(tuple(e) for e in self.processor["edges"])
        self.num_qubits = self.graph.number_of_nodes()

        self._scale = _check_scale(scale)
        self._overrides = _check_overrides(overrides, self.profile, self.graph)
        self._conditional = _check_conditional(conditional)

        self.target, self.noise_model = _BUILDERS[self.kind](self)

    @property
    def has_durations(self) -> bool:
        """Whether the Target carries gate durations, so a run's circuit is scheduled before simulating."""
        return self.kind == "snapshot"

    # Fixed at the build, so the export always describes the model; each read returns a copy.

    @property
    def scale(self) -> float:
        """The scale factor the model was built with."""
        return self._scale

    @property
    def overrides(self) -> tuple[dict, ...]:
        """The overrides the model was built with, as `{qubits: [ids], field, value}` copies, in order."""
        return tuple({**o, "qubits": list(o["qubits"])} for o in self._overrides)

    @property
    def conditional(self) -> dict:
        """Both conditional channels, as a copy."""
        return dict(self._conditional)

    # -- YAML ------------------------------------------------------------------

    def export_as_yaml(self) -> dict:
        """NoiseControl's part of the run YAML: the files it was built from, by path and hash, and its settings."""
        return {
            "processor": dict(self._records["processor"]),
            "noise": dict(self._records["noise"]),
            "scale": self.scale,
            "overrides": list(self.overrides),
            "conditional": self.conditional,
        }

    @classmethod
    def from_yaml(cls, record: Mapping) -> "NoiseControl":
        """Rebuild a NoiseControl from `export_as_yaml`'s mapping; refuses a file whose hash changed."""
        expected = {"processor", "noise", "scale", "overrides", "conditional"}
        if set(record) != expected:
            raise ValueError(f"a NoiseControl record has the keys {sorted(expected)}; got {sorted(record)}")
        processor = name_from_record(record["processor"], "processor")
        noise = name_from_record(record["noise"], "noise")
        nc = cls(processor, noise, record["scale"], record["overrides"], record["conditional"])
        for kind in ("processor", "noise"):
            check_unchanged(record[kind], nc._records[kind])
        return nc


# -- Building ------------------------------------------------------------------


class _TargetBackend(BackendV2):
    """A backend that only carries a Target, so Aer's NoiseModel.from_backend can read it."""

    def __init__(self, target: Target):
        super().__init__(name="bellbench-target")
        self._target = target

    @property
    def target(self):
        return self._target

    @property
    def max_circuits(self):
        return None

    @classmethod
    def _default_options(cls):
        return Options()

    def run(self, run_input, **options):
        raise NotImplementedError("this backend only carries a Target; simulate with Aer")


def _build_snapshot(nc: NoiseControl):
    profile = nc.profile
    qubit_values = _qubit_values(nc)
    gate_errors = _gate_errors(nc)
    _check_values(qubit_values, gate_errors, profile)

    target = Target(
        num_qubits=nc.num_qubits,
        dt=profile["time_step"],
        qubit_properties=[QubitProperties(t1=qubit_values[q][T1], t2=qubit_values[q][T2]) for q in range(nc.num_qubits)],
    )
    for gate, spec in profile["gates"].items():
        target.add_instruction(
            _standard(gate, spec["qubits"]),
            {qargs: InstructionProperties(error=error, duration=spec["duration"]) for qargs, error in gate_errors[gate].items()},
        )
    target.add_instruction(
        STANDARD_GATES["measure"],
        {
            (q,): InstructionProperties(
                error=(qubit_values[q][READS_1_WHEN_0] + qubit_values[q][READS_0_WHEN_1]) / 2,
                duration=profile["measure"]["duration"],
            )
            for q in range(nc.num_qubits)
        },
    )
    if "reset" in profile:  # a profile without reset data cannot run a circuit that resets
        target.add_instruction(
            STANDARD_GATES["reset"],
            {(q,): InstructionProperties(duration=profile["reset"]["duration"]) for q in range(nc.num_qubits)},
        )
    target.add_instruction(STANDARD_GATES["delay"], {(q,): None for q in range(nc.num_qubits)})

    noise_model = NoiseModel.from_backend(_TargetBackend(target), readout_error=False)
    for q in range(nc.num_qubits):
        p10, p01 = qubit_values[q][READS_1_WHEN_0], qubit_values[q][READS_0_WHEN_1]
        noise_model.add_readout_error(ReadoutError([[1 - p10, p10], [p01, 1 - p01]]), [q])
    reset_error = nc.conditional["reset_error"]
    if reset_error is not None and "reset" in profile:
        _add_after(noise_model, _bit_flip(reset_error), "reset", nc.num_qubits)
    return target, noise_model


def _bit_flip(p: float):
    return pauli_error([("X", p), ("I", 1 - p)])


def _add_after(noise_model: NoiseModel, error, instruction: str, num_qubits: int) -> None:
    """Add `error` after whatever `instruction` already carries on each qubit; Aer composes the second error after
    the first, and its warning that it did so is turned off, since that is the point."""
    for q in range(num_qubits):
        noise_model.add_quantum_error(error, instruction, [q], warnings=False)


def _build_depolarising(nc: NoiseControl):
    spec = nc.profile["depolarising"]
    gates, after = spec["gates"], spec["after_gate"]
    if after not in gates:
        raise ValueError(f"noise profile {nc.noise_name!r}: after_gate {after!r} is not in its gates {gates}")
    probability = spec["probability"] * nc.scale
    _check_probability("depolarising.probability", probability, nc.scale)

    target = Target(num_qubits=nc.num_qubits)
    for gate in gates:
        op = _standard(gate)
        target.add_instruction(op, {qargs: None for qargs in _qargs(op.num_qubits, nc)})
    target.add_instruction(STANDARD_GATES["measure"], {(q,): None for q in range(nc.num_qubits)})

    noise_model = NoiseModel(basis_gates=list(gates))
    after_op = _standard(after)
    error = depolarizing_error(probability, after_op.num_qubits)
    for qargs in _qargs(after_op.num_qubits, nc):
        noise_model.add_quantum_error(error, after, list(qargs))
    return target, noise_model


_BUILDERS = {"snapshot": _build_snapshot, "depolarising": _build_depolarising}


# -- Values: profile, then overrides, then scale --------------------------------


def _qubit_values(nc: NoiseControl) -> dict[int, dict[str, float]]:
    """Each qubit's T1, T2 and readout errors, after the overrides and the scale."""
    q = nc.profile["qubit"]
    base = {
        T1: q["t1_relaxation_time"],
        T2: q["t2_dephasing_time"],
        READS_1_WHEN_0: q["readout_error"]["reads_1_when_0"],
        READS_0_WHEN_1: q["readout_error"]["reads_0_when_1"],
    }
    values = {qubit: dict(base) for qubit in range(nc.num_qubits)}
    for o in nc._overrides:
        if o["field"] in QUBIT_FIELDS:
            values[o["qubits"][0]][o["field"]] = o["value"]
    for v in values.values():  # the scale multiplies probabilities and the decay rates 1/T1 and 1/T2
        v[T1] /= nc.scale
        v[T2] /= nc.scale
        for field in PROBABILITY_FIELDS:
            v[field] *= nc.scale
    return values


def _gate_errors(nc: NoiseControl) -> dict[str, dict[tuple, float]]:
    """Each native gate's error on each qubit or directed coupler, after the overrides and the scale."""
    errors = {}
    for gate, spec in nc.profile["gates"].items():
        errors[gate] = {qargs: spec["error_probability"] for qargs in _qargs(spec["qubits"], nc)}
    for o in nc._overrides:
        gate = _override_gate(o["field"])
        if gate is not None:
            qubits = tuple(o["qubits"])
            errors[gate][qubits] = o["value"]
            if len(qubits) == 2:
                errors[gate][qubits[::-1]] = o["value"]
    return {gate: {qargs: e * nc.scale for qargs, e in by_qargs.items()} for gate, by_qargs in errors.items()}


def _check_values(qubit_values, gate_errors, profile) -> None:
    """Raise a ValueError naming the field for any value the noise model would otherwise change silently."""
    for q, v in qubit_values.items():
        for field in PROBABILITY_FIELDS:
            _check_probability(f"{field} on qubit {q}", v[field])
        if not v[T1] > 0 or not v[T2] > 0:
            raise ValueError(f"{T1} and {T2} on qubit {q} must be greater than 0")
        if v[T2] > 2 * v[T1]:
            raise ValueError(f"{T2} on qubit {q} is {v[T2]:.6g} s, above 2 x {T1} ({2 * v[T1]:.6g} s)")
    for gate, by_qargs in gate_errors.items():
        duration = profile["gates"][gate]["duration"]
        field = GATE_ERROR_FIELD.format(gate=gate)
        for qargs, error in by_qargs.items():
            _check_probability(f"{field} on qubits {qargs}", error)
            floor, ceiling = _error_range(qargs, duration, qubit_values)
            if error < floor:
                raise ValueError(
                    f"{field} on qubits {qargs} is {error:.6g}, below the {floor:.6g} its {duration:.6g} s "
                    "of decay alone causes; Aer would drop the gate error"
                )
            if error > ceiling:
                raise ValueError(
                    f"{field} on qubits {qargs} is {error:.6g}, above the {ceiling:.6g} Aer can build for a "
                    f"{len(qargs)}-qubit gate with {duration:.6g} s of decay; Aer would cap the gate error"
                )


def _error_range(qargs, duration, qubit_values) -> tuple[float, float]:
    """The lowest and highest gate error Aer builds as stated, as average gate infidelities.

    The lowest is the infidelity that T1 and T2 decay alone cause over `duration`.
    Aer models the rest of the error as a depolarising channel after that decay,
    and caps it twice: the error at dim/(dim + 1), the infidelity of a fully
    random channel, and the depolarising parameter at 4^n/(4^n - 1). The highest
    error is whichever cap binds first, and equals dim/(dim + 1) with no decay.
    """
    n, dim = len(qargs), 2 ** len(qargs)
    decay = 0.0
    if duration:
        error = None
        for q in qargs:
            single = thermal_relaxation_error(qubit_values[q][T1], qubit_values[q][T2], duration)
            error = single if error is None else error.expand(single)
        decay = 1 - average_gate_fidelity(error)
    max_depolarising = 4**n / (4**n - 1)
    ceiling = min(dim / (dim + 1), decay + max_depolarising * (dim * (1 - decay) - 1) / dim)
    return decay, ceiling


# -- Input checks ----------------------------------------------------------------


def _is_number(value) -> bool:
    """A real number other than a bool, numpy numbers included."""
    return isinstance(value, numbers.Real) and not isinstance(value, bool)


def _is_id(value) -> bool:
    """An integer qubit id other than a bool, numpy integers included."""
    return isinstance(value, numbers.Integral) and not isinstance(value, bool)


def _check_scale(scale) -> float:
    if not _is_number(scale) or not math.isfinite(scale) or scale <= 0:
        raise ValueError(f"scale must be a finite number greater than 0 (the ideal simulation covers no noise); got {scale!r}")
    return float(scale)


def _check_probability(field: str, value: float, scale: float | None = None) -> None:
    if not 0 <= value <= 1:
        after = f" after scale {scale:g}" if scale is not None else ""
        raise ValueError(f"{field} is {value:.6g}{after}; a probability must be between 0 and 1")


def _check_overrides(overrides, profile, graph) -> tuple[dict, ...]:
    """Validate overrides and return them as `{qubits: [ids], field, value}` dicts, in order."""
    if isinstance(overrides, Mapping) or isinstance(overrides, str):
        raise ValueError("overrides must be a list of {qubits, field, value} entries")
    if overrides and profile["kind"] != "snapshot":
        raise ValueError(f"a {profile['kind']} noise profile takes no overrides")
    checked, seen = [], set()
    for o in overrides:
        if not isinstance(o, Mapping) or set(o) != {"qubits", "field", "value"}:
            raise ValueError(f"an override has exactly the keys qubits, field and value; got {o!r}")
        field, value = o["field"], o["value"]
        qubits = [o["qubits"]] if _is_id(o["qubits"]) else list(o["qubits"])
        if not qubits or not all(_is_id(q) for q in qubits):
            raise ValueError(f"override of {field!r}: qubits must be one qubit id or a list of ids; got {o['qubits']!r}")
        qubits = [int(q) for q in qubits]
        for q in qubits:
            if q not in graph:
                raise ValueError(f"override of {field!r}: qubit {q} is not on the processor graph")
        if not _is_number(value) or not math.isfinite(value):
            raise ValueError(f"override of {field!r}: value must be a finite number; got {value!r}")
        value = float(value)

        gate = _override_gate(field)
        if field in QUBIT_FIELDS:
            needed = 1
        elif gate is not None:
            if gate not in profile["gates"]:
                raise ValueError(f"override of {field!r}: the profile has no gate {gate!r}")
            needed = profile["gates"][gate]["qubits"]
        elif isinstance(field, str) and field.endswith("duration"):
            raise ValueError(f"override of {field!r}: durations cannot be overridden")
        else:
            allowed = ", ".join(OVERRIDE_FIELDS)
            raise ValueError(f"override field {field!r} is not one of: {allowed}")
        if len(qubits) != needed:
            raise ValueError(f"override of {field!r} names {len(qubits)} qubit(s); it takes {needed}")
        if needed == 2 and not graph.has_edge(*qubits):
            raise ValueError(f"override of {field!r}: qubits {qubits} are not a coupler of the processor graph")

        key = (frozenset(qubits), field)
        if key in seen:
            raise ValueError(f"override of {field!r} on qubits {qubits} is given twice")
        seen.add(key)
        checked.append({"qubits": qubits, "field": field, "value": value})
    return tuple(checked)


def _override_gate(field) -> str | None:
    """The gate a `gates.<gate>.error_probability` field names, or None."""
    if isinstance(field, str):
        parts = field.split(".")
        if len(parts) == 3 and parts[0] == "gates" and parts[2] == "error_probability":
            return parts[1]
    return None


def _check_conditional(conditional) -> dict:
    """Validate and return both conditional channels; setting the mid-circuit one raises until it is built."""
    channels = dict.fromkeys(CONDITIONAL_CHANNELS)
    if conditional is None:
        return channels
    if not isinstance(conditional, Mapping) or not set(conditional) <= set(CONDITIONAL_CHANNELS):
        raise ValueError(f"conditional takes only the keys {', '.join(CONDITIONAL_CHANNELS)}; got {conditional!r}")
    for channel, value in conditional.items():
        if value is None:
            continue
        if not _is_number(value) or not 0 <= value <= 1:
            raise ValueError(f"conditional {channel} must be null or a probability between 0 and 1; got {value!r}")
        channels[channel] = float(value)
    for channel, value in channels.items():
        if channel == "mid_circuit_measurement_error" and value is not None:
            raise NotImplementedError(
                f"conditional channel {channel} is not built yet; it is built together with the first check "
                "that needs it, so a value is never accepted and silently ignored"
            )
    return channels


# -- Helpers ----------------------------------------------------------------------


def _qargs(num_qubits: int, nc: NoiseControl) -> list[tuple]:
    """Every qubit for a one-qubit gate, or every directed coupler for a two-qubit gate."""
    if num_qubits == 1:
        return [(q,) for q in range(nc.num_qubits)]
    if num_qubits == 2:
        return [qargs for a, b in nc.edges for qargs in ((a, b), (b, a))]
    raise ValueError(f"gates act on 1 or 2 qubits; got {num_qubits}")


def _standard(name: str, num_qubits: int | None = None):
    """Qiskit's standard instruction for a gate name, checked against the qubits the profile gives it."""
    if name not in STANDARD_GATES:
        raise ValueError(f"gate {name!r} is not one of Qiskit's standard gate names")
    op = STANDARD_GATES[name]
    if num_qubits is not None and op.num_qubits != num_qubits:
        raise ValueError(f"gate {name!r} acts on {op.num_qubits} qubit(s); the profile says {num_qubits}")
    return op
