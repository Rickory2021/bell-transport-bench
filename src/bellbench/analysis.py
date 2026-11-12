# src/bellbench/analysis.py
"""How a run reads its shots: the analysis its circuit file names, from the registry here.

The analysis is the one step of a run that a strategy chooses (docs/DESIGN.md,
section 7). It takes each basis's raw counts, keyed as Qiskit writes them with
every register, the circuit's classical registers (name and size, in order, the
port register last) and the settings the circuit file gives, and returns for
each basis the port counts over all shots and over the shots it keeps, with any
Pauli frame already applied to both. It never sees the noise model and never
computes a fidelity: one fidelity function scores what it returns, and
`read_shots` refuses an answer whose counts do not add up, so every strategy is
scored the same way.

A circuit file names its analysis as `{name, settings}`:

- `postselect` keeps a shot when every register other than the port reads all
  0, and takes no settings. A circuit with no other register keeps every shot.
  It refuses a frame register, whose bits say what the analysis must flip
  rather than whether to keep the shot.
- `parity` takes `checks`, a list of groups of bits, and optional `frame_z` and
  `frame_x` lists of bits, each bit written as `register[index]`. A shot is kept
  when every group has even parity. When the frame_z bits have odd parity, a Z
  is owed on the first port, so its outcome flips in the XX and YY bases; when
  the frame_x bits do, an X is owed and its outcome flips in the ZZ and YY
  bases. A group may include frame bits, as a check measured after a frame bit
  must. Every bit of every register other than the port is read by a group or a
  frame, a frame_z bit comes from a frame_z register and a frame_x bit from a
  frame_x one, so no bit is left unread or read as the wrong kind.

Correction, which flips result bits to undo a detected error, is not here: a
decoder joins the registry when a strategy first needs one.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from bellbench.fidelity import BASES
from bellbench.pipeline import PORT_REGISTER, split_key

Registers = Sequence[tuple[str, int]]  # each classical register's name and size, in order, the port last
BIT = re.compile(r"([a-z][a-z0-9_]*)\[(\d+)\]")

# Which bases' first-port outcome a Pauli owed on that port flips: Z flips X and Y, X flips Z and Y.
FLIPS = {"frame_z": ("XX", "YY"), "frame_x": ("ZZ", "YY")}


@dataclass(frozen=True)
class PortCounts:
    """For each basis, the port counts over every shot and over the shots kept, frame applied to both."""

    all: dict[str, dict[str, int]]
    kept: dict[str, dict[str, int]]


@dataclass(frozen=True)
class Entry:
    """One registered analysis: `check` refuses settings that do not fit the registers; `read` reads the shots."""

    check: Callable[[Mapping, Registers], None]
    read: Callable[[Mapping[str, Mapping[str, int]], Registers, Mapping], PortCounts]


# -- The contract ------------------------------------------------------------------


def check_analysis(spec, registers: Registers) -> None:
    """Raise a ValueError when `spec` names no registered analysis or its settings do not fit the registers."""
    if not isinstance(spec, Mapping) or "name" not in spec or not set(spec) <= {"name", "settings"}:
        raise ValueError(f"an analysis is {{name, settings}}; got {spec!r}")
    if spec["name"] not in REGISTRY:
        raise ValueError(f"no analysis named {spec['name']!r}; known: {', '.join(REGISTRY)}")
    settings = spec.get("settings", {})
    if not isinstance(settings, Mapping):
        raise ValueError(f"the {spec['name']} analysis's settings are a mapping; got {settings!r}")
    _check_registers(registers)
    REGISTRY[spec["name"]].check(settings, registers)


def read_shots(spec, raw: Mapping[str, Mapping[str, int]], registers: Registers, shots: int) -> PortCounts:
    """Read each basis's shots with the analysis `spec` names, and check its answer against the contract."""
    check_analysis(spec, registers)
    ports = REGISTRY[spec["name"]].read(raw, registers, spec.get("settings", {}))
    for basis in BASES:
        every, kept = ports.all[basis], ports.kept[basis]
        if any(not re.fullmatch(r"[01]{2}", k) for k in (*every, *kept)):
            raise ValueError(f"the {spec['name']} analysis returned port outcomes that are not two bits: {basis}")
        if sum(every.values()) != shots:
            raise ValueError(
                f"the {spec['name']} analysis counted {sum(every.values())} shots of {shots} in {basis}"
            )
        if sum(kept.values()) > shots:
            raise ValueError(f"the {spec['name']} analysis kept more shots than were run in {basis}")
    return ports


# -- postselect --------------------------------------------------------------------


def _check_postselect(settings: Mapping, registers: Registers) -> None:
    if settings:
        raise ValueError(f"the postselect analysis takes no settings; got {dict(settings)!r}")
    frames = [name for name, _ in registers if _role(name) in FLIPS]
    if frames:
        raise ValueError(
            f"postselect reads every register but the port as a check, and {', '.join(frames)} carries a Pauli "
            "frame; name the parity analysis, with the frame listed in its settings"
        )


def _read_postselect(raw, registers: Registers, settings: Mapping) -> PortCounts:
    every, kept = _empty(), _empty()
    for basis in BASES:
        for key, n in raw[basis].items():
            bits = _split(key, registers)
            port = bits.pop(PORT_REGISTER)
            _add(every[basis], port, n)
            if all(set(b) <= {"0"} for b in bits.values()):
                _add(kept[basis], port, n)
    return PortCounts(every, kept)


# -- parity ------------------------------------------------------------------------


def _check_parity(settings: Mapping, registers: Registers) -> None:
    unknown = set(settings) - {"checks", "frame_z", "frame_x"}
    if unknown:
        raise ValueError(f"the parity analysis takes checks, frame_z and frame_x; got {sorted(unknown)}")
    checks = settings.get("checks")
    if not isinstance(checks, list) or any(not isinstance(g, list) or not g for g in checks):
        raise ValueError(f"parity's checks are a list of non-empty lists of bits; got {checks!r}")
    sizes = dict(registers)
    read = set()
    for where, bits in [("checks", b) for b in checks] + [(f, settings.get(f, [])) for f in FLIPS]:
        if not isinstance(bits, list):
            raise ValueError(f"parity's {where} is a list of bits; got {bits!r}")
        for bit in bits:
            name, index = _parse_bit(bit, sizes)
            if where in FLIPS and _role(name) != where:
                raise ValueError(f"parity's {where} lists {bit}, which is not a bit of a {where} register")
            read.add((name, index))
    for name, size in registers:
        for index in range(size):
            if name != PORT_REGISTER and (name, index) not in read:
                raise ValueError(f"parity reads no group or frame with {name}[{index}]; list every bit it measures")


def _read_parity(raw, registers: Registers, settings: Mapping) -> PortCounts:
    sizes = dict(registers)
    groups = [[_parse_bit(b, sizes) for b in group] for group in settings["checks"]]
    frames = {f: [_parse_bit(b, sizes) for b in settings.get(f, [])] for f in FLIPS}
    every, kept = _empty(), _empty()
    for basis in BASES:
        for key, n in raw[basis].items():
            bits = _split(key, registers)
            port = bits[PORT_REGISTER]
            for frame, flipped in FLIPS.items():
                if basis in flipped and _parity(bits, frames[frame]):
                    port = port[0] + ("1" if port[1] == "0" else "0")  # the first port is the right-hand bit
            _add(every[basis], port, n)
            if not any(_parity(bits, group) for group in groups):
                _add(kept[basis], port, n)
    return PortCounts(every, kept)


REGISTRY = {
    "postselect": Entry(_check_postselect, _read_postselect),
    "parity": Entry(_check_parity, _read_parity),
}


# -- Helpers -------------------------------------------------------------------------


def _check_registers(registers: Registers) -> None:
    names = [name for name, _ in registers]
    if not names or names[-1] != PORT_REGISTER or names.count(PORT_REGISTER) != 1:
        raise ValueError(f"the registers end with the one port register; got {names}")


def _role(name: str) -> str:
    """The role a register's name starts with: frame_z, frame_x, or the part before its first underscore."""
    for frame in FLIPS:
        if name == frame or name.startswith(frame + "_"):
            return frame
    return name.split("_")[0]


def _parse_bit(bit, sizes: Mapping[str, int]) -> tuple[str, int]:
    match = BIT.fullmatch(bit) if isinstance(bit, str) else None
    if match is None:
        raise ValueError(f"a bit is written register[index], such as check_zz[0]; got {bit!r}")
    name, index = match.group(1), int(match.group(2))
    if name == PORT_REGISTER or name not in sizes:
        raise ValueError(f"{bit} is not a bit of the circuit's registers {[n for n in sizes if n != PORT_REGISTER]}")
    if index >= sizes[name]:
        raise ValueError(f"{bit} is past the end of {name}, which has {sizes[name]} bit(s)")
    return name, index


def _split(key: str, registers: Registers) -> dict[str, str]:
    """A count key as each register's bit string; Qiskit writes the last register first."""
    return split_key(key, [name for name, _ in registers])


def _parity(bits: Mapping[str, str], refs: Sequence[tuple[str, int]]) -> int:
    """The parity of the bits named; inside a register's string the highest bit comes first."""
    return sum(int(bits[name][-1 - index]) for name, index in refs) % 2


def _empty() -> dict[str, dict[str, int]]:
    return {basis: {} for basis in BASES}


def _add(counts: dict[str, int], port: str, n: int) -> None:
    counts[port] = counts.get(port, 0) + n
