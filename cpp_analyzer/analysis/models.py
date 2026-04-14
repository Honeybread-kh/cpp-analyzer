"""
Data models for config analysis: parameters, dependencies, and overrides.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class ConfigParam:
    name: str
    qualified_name: str = ""
    config_type: str = ""          # bool, int, enum, string, float, J_COLOR_SPACE, ...
    source_kind: str = ""          # CLI_ARG, STRUCT_FIELD, DEFINE, ENV_VAR, GFLAGS, ...
    default_value: str | None = None
    min_value: str | None = None
    max_value: str | None = None
    enum_values: str | None = None  # pipe-separated: "JDCT_ISLOW|JDCT_IFAST|JDCT_FLOAT"
    cli_flag: str | None = None
    setter_function: str | None = None
    defined_file: str = ""
    defined_line: int = 0
    description: str = ""
    ifdef_guard: str | None = None  # e.g. "C_LOSSLESS_SUPPORTED"

    CSV_HEADERS = [
        "name", "qualified_name", "type", "source_kind",
        "default", "min", "max", "enum_values",
        "cli_flag", "setter_function",
        "file", "line", "description", "ifdef_guard",
    ]

    def csv_row(self) -> list[str]:
        return [
            self.name,
            self.qualified_name,
            self.config_type,
            self.source_kind,
            self.default_value or "",
            self.min_value or "",
            self.max_value or "",
            self.enum_values or "",
            self.cli_flag or "",
            self.setter_function or "",
            self.defined_file,
            str(self.defined_line),
            self.description,
            self.ifdef_guard or "",
        ]


@dataclass
class ConfigDependency:
    source_config: str
    source_condition: str = ""     # e.g. "== 12", "!= 0"
    target_config: str = ""
    forced_value: str | None = None
    relationship_type: str = ""    # DIRECT_OVERRIDE | CASCADE | MUTUAL_EXCLUSION | AGGREGATION
    file: str = ""
    line: int = 0
    function: str = ""
    code_snippet: str = ""

    CSV_HEADERS = [
        "source_config", "condition", "target_config", "forced_value",
        "relationship_type", "file", "line", "function", "code_snippet",
    ]

    def csv_row(self) -> list[str]:
        return [
            self.source_config,
            self.source_condition,
            self.target_config,
            self.forced_value or "",
            self.relationship_type,
            self.file,
            str(self.line),
            self.function,
            self.code_snippet.replace("\n", " ")[:200],
        ]


# ── taint analysis models ────────────────────────────────────────────────────

@dataclass
class TaintNode:
    variable: str              # "cfg->param", "local_var", "REG_WRITE(CTRL_0, val)"
    node_type: str = ""        # SOURCE | INTERMEDIATE | SINK
    transform: str = ""        # "<< 8", "/ BASE_CLK", ""
    file: str = ""
    line: int = 0
    function: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TaintNode":
        return cls(
            variable=d.get("variable", ""),
            node_type=d.get("node_type", ""),
            transform=d.get("transform", ""),
            file=d.get("file", ""),
            line=d.get("line", 0),
            function=d.get("function", ""),
        )


@dataclass
class DataFlowPath:
    source: TaintNode
    sink: TaintNode
    steps: list[TaintNode] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source": self.source.to_dict(),
            "sink": self.sink.to_dict(),
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DataFlowPath":
        return cls(
            source=TaintNode.from_dict(d["source"]),
            sink=TaintNode.from_dict(d["sink"]),
            steps=[TaintNode.from_dict(s) for s in d.get("steps", [])],
        )

    @property
    def depth(self) -> int:
        return len(self.steps) + 2  # source + steps + sink

    def format_chain(self) -> str:
        """Format as human-readable chain: source →(transform)→ ... → sink."""
        parts = []
        nodes = [self.source] + self.steps + [self.sink]
        for i, node in enumerate(nodes):
            loc = f"[{node.file}:{node.line}, {node.function}]" if node.file else ""
            if i == 0:
                parts.append(f"{node.variable}")
            else:
                arrow = f"→({nodes[i-1].transform})→" if nodes[i-1].transform else "→"
                parts.append(f"  {arrow} {node.variable}  {loc}")
        return "\n".join(parts)


# ── config field spec ────────────────────────────────────────────────────────

@dataclass
class ConfigFieldSpec:
    """Specification of a config struct field with enum/range metadata."""
    field_name: str
    struct_name: str = ""
    field_type: str = ""
    enum_type: str | None = None
    enum_values: list[str] = field(default_factory=list)
    min_value: str | None = None
    max_value: str | None = None
    register_sinks: list[str] = field(default_factory=list)
    transforms: list[str] = field(default_factory=list)
    description: str = ""
    file: str = ""
    line: int = 0
    gated_by: str | None = None
    gates: list[str] = field(default_factory=list)
    co_depends: list[str] = field(default_factory=list)

    CSV_HEADERS = [
        "field_name", "struct_name", "field_type", "enum_type", "enum_values",
        "min_value", "max_value", "register_sinks", "transforms",
        "description", "file", "line",
        "gated_by", "gates", "co_depends",
    ]

    def csv_row(self) -> list[str]:
        return [
            self.field_name,
            self.struct_name,
            self.field_type,
            self.enum_type or "",
            "|".join(self.enum_values),
            self.min_value or "",
            self.max_value or "",
            "|".join(self.register_sinks),
            "|".join(self.transforms),
            self.description,
            self.file,
            str(self.line),
            self.gated_by or "",
            "|".join(self.gates),
            "|".join(self.co_depends),
        ]

    def to_dict(self) -> dict:
        return asdict(self)
