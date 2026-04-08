"""
C++ AST parser using libclang Python bindings.

Extracts:
  - Symbols  : functions, methods, classes, structs, variables, enums
  - Call edges: caller → callee (within the same TU)
  - Include edges

Falls back to a lightweight regex scanner if libclang is unavailable.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── data classes returned by the parser ───────────────────────────────────────

@dataclass
class SymbolInfo:
    name: str
    qualified_name: str
    kind: str                        # FUNCTION | METHOD | CLASS | STRUCT | VARIABLE | ENUM | CONSTRUCTOR | …
    signature: str
    line_start: int
    line_end: int
    col_start: int
    is_definition: bool
    is_declaration: bool
    parent_usr: Optional[str]        # USR of enclosing class/namespace
    namespace_path: str
    visibility: str                  # public | private | protected | ""
    return_type: str
    usr: str                         # Unified Symbol Resolution (clang unique ID)
    template_params: str = ""        # e.g. "typename T, int N"


@dataclass
class CallInfo:
    caller_usr: str
    callee_name: str
    callee_usr: Optional[str]
    line: int
    col: int
    code_snippet: str
    call_type: str = "direct"        # direct | indirect


@dataclass
class IncludeInfo:
    included_path: str
    line: int
    is_system: bool


@dataclass
class InheritanceInfo:
    class_usr: str
    base_name: str
    base_usr: Optional[str]
    access: str                      # public | protected | private | ""
    is_virtual: bool = False


@dataclass
class ParseResult:
    file_path: str
    file_hash: str
    line_count: int
    symbols: list[SymbolInfo] = field(default_factory=list)
    calls: list[CallInfo] = field(default_factory=list)
    includes: list[IncludeInfo] = field(default_factory=list)
    inherits: list[InheritanceInfo] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    used_fallback: bool = False


# ── clang kind → our kind string ──────────────────────────────────────────────

_CLANG_KIND_MAP: dict[int, str] = {}

def _build_kind_map():
    try:
        import clang.cindex as ci
        _CLANG_KIND_MAP.update({
            ci.CursorKind.FUNCTION_DECL.value:        "FUNCTION",
            ci.CursorKind.CXX_METHOD.value:           "METHOD",
            ci.CursorKind.CONSTRUCTOR.value:           "CONSTRUCTOR",
            ci.CursorKind.DESTRUCTOR.value:            "DESTRUCTOR",
            ci.CursorKind.CLASS_DECL.value:            "CLASS",
            ci.CursorKind.STRUCT_DECL.value:           "STRUCT",
            ci.CursorKind.CLASS_TEMPLATE.value:        "CLASS_TEMPLATE",
            ci.CursorKind.FUNCTION_TEMPLATE.value:     "FUNCTION_TEMPLATE",
            ci.CursorKind.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION.value: "CLASS_TEMPLATE_PARTIAL_SPECIALIZATION",
            ci.CursorKind.VAR_DECL.value:              "VARIABLE",
            ci.CursorKind.FIELD_DECL.value:            "FIELD",
            ci.CursorKind.ENUM_DECL.value:             "ENUM",
            ci.CursorKind.ENUM_CONSTANT_DECL.value:    "ENUM_CONSTANT",
            ci.CursorKind.NAMESPACE.value:             "NAMESPACE",
            ci.CursorKind.TYPEDEF_DECL.value:          "TYPEDEF",
            ci.CursorKind.TYPE_ALIAS_DECL.value:       "TYPE_ALIAS",
        })
    except ImportError:
        pass


# ── visibility helper ─────────────────────────────────────────────────────────

_ACCESS_MAP = {1: "public", 2: "protected", 3: "private"}


def _visibility(cursor) -> str:
    try:
        import clang.cindex as ci
        return _ACCESS_MAP.get(cursor.access_specifier.value, "")
    except Exception:
        return ""


# ── qualified name builder ────────────────────────────────────────────────────

def _qualified_name(cursor) -> str:
    parts = []
    c = cursor
    while c and c.kind.is_translation_unit() is False:
        if c.spelling:
            parts.append(c.spelling)
        else:
            # Anonymous namespace / struct / class
            parts.append("(anonymous)")
        c = c.semantic_parent
        if c and c.kind.is_translation_unit():
            break
    return "::".join(reversed(parts))


def _namespace_path(cursor) -> str:
    """Return namespace + class scope path, not the symbol itself."""
    try:
        import clang.cindex as ci
        _SCOPE_KINDS = {
            ci.CursorKind.NAMESPACE,
            ci.CursorKind.CLASS_DECL,
            ci.CursorKind.STRUCT_DECL,
            ci.CursorKind.CLASS_TEMPLATE,
        }
        parts = []
        c = cursor.semantic_parent
        while c and not c.kind.is_translation_unit():
            if c.kind in _SCOPE_KINDS:
                parts.append(c.spelling if c.spelling else "(anonymous)")
            c = c.semantic_parent
        return "::".join(reversed(parts))
    except Exception:
        return ""


# ── main clang-based parser ───────────────────────────────────────────────────

_SYMBOL_KINDS: set[int] = set()
_FUNC_KINDS: set[int] = set()
_CLASS_KINDS: set[int] = set()
_TEMPLATE_KINDS: set[int] = set()


def _init_kind_sets():
    try:
        import clang.cindex as ci
        _SYMBOL_KINDS.update({
            ci.CursorKind.FUNCTION_DECL.value,
            ci.CursorKind.CXX_METHOD.value,
            ci.CursorKind.CONSTRUCTOR.value,
            ci.CursorKind.DESTRUCTOR.value,
            ci.CursorKind.CLASS_DECL.value,
            ci.CursorKind.STRUCT_DECL.value,
            ci.CursorKind.CLASS_TEMPLATE.value,
            ci.CursorKind.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION.value,
            ci.CursorKind.FUNCTION_TEMPLATE.value,
            ci.CursorKind.VAR_DECL.value,
            ci.CursorKind.FIELD_DECL.value,
            ci.CursorKind.ENUM_DECL.value,
            ci.CursorKind.NAMESPACE.value,
            ci.CursorKind.TYPEDEF_DECL.value,
            ci.CursorKind.TYPE_ALIAS_DECL.value,
        })
        _FUNC_KINDS.update({
            ci.CursorKind.FUNCTION_DECL.value,
            ci.CursorKind.CXX_METHOD.value,
            ci.CursorKind.CONSTRUCTOR.value,
            ci.CursorKind.DESTRUCTOR.value,
            ci.CursorKind.FUNCTION_TEMPLATE.value,
        })
        _CLASS_KINDS.update({
            ci.CursorKind.CLASS_DECL.value,
            ci.CursorKind.STRUCT_DECL.value,
            ci.CursorKind.CLASS_TEMPLATE.value,
            ci.CursorKind.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION.value,
        })
        _TEMPLATE_KINDS.update({
            ci.CursorKind.CLASS_TEMPLATE.value,
            ci.CursorKind.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION.value,
            ci.CursorKind.FUNCTION_TEMPLATE.value,
        })
    except ImportError:
        pass


def _extract_template_params(cursor) -> str:
    """Collect template parameter names from a template cursor.

    Returns a string like ``"typename T, int N"`` or ``""`` if none found.
    """
    try:
        import clang.cindex as ci
        _TPARAM_KINDS = {
            ci.CursorKind.TEMPLATE_TYPE_PARAMETER,
            ci.CursorKind.TEMPLATE_NON_TYPE_PARAMETER,
            ci.CursorKind.TEMPLATE_TEMPLATE_PARAMETER,
        }
        params: list[str] = []
        for child in cursor.get_children():
            if child.kind in _TPARAM_KINDS:
                if child.kind == ci.CursorKind.TEMPLATE_TYPE_PARAMETER:
                    params.append(f"typename {child.spelling}" if child.spelling else "typename")
                elif child.kind == ci.CursorKind.TEMPLATE_NON_TYPE_PARAMETER:
                    type_str = child.type.spelling if child.type else ""
                    params.append(f"{type_str} {child.spelling}".strip())
                else:
                    params.append(f"template {child.spelling}" if child.spelling else "template")
        return ", ".join(params)
    except Exception:
        return ""


class ClangParser:
    def __init__(self, extra_args: list[str] | None = None):
        try:
            import clang.cindex as ci
            import subprocess, platform
            _build_kind_map()
            _init_kind_sets()
            self._ci = ci
            self._index = ci.Index.create()

            # Build default args with SDK path on macOS
            default_args = ["-std=c++17", "-x", "c++"]
            if platform.system() == "Darwin":
                try:
                    sdk = subprocess.check_output(
                        ["xcrun", "--show-sdk-path"], stderr=subprocess.DEVNULL
                    ).decode().strip()
                    default_args += [f"-isysroot{sdk}", f"-I{sdk}/usr/include"]
                except Exception:
                    pass

            self._extra_args = extra_args or default_args
            self._available = True
        except ImportError:
            self._available = False
            self._ci = None

    @property
    def available(self) -> bool:
        return self._available

    @staticmethod
    def compute_file_hash(file_path: str | Path) -> str:
        """Compute SHA-256 hash of a file without parsing it."""
        return hashlib.sha256(Path(file_path).read_bytes()).hexdigest()

    def parse_file(self, file_path: str | Path) -> ParseResult:
        path = str(file_path)
        content = Path(path).read_bytes()
        file_hash = hashlib.sha256(content).hexdigest()
        lines = content.decode("utf-8", errors="replace").splitlines()
        line_count = len(lines)

        result = ParseResult(file_path=path, file_hash=file_hash, line_count=line_count)

        if not self._available:
            return self._fallback_parse(path, lines, result)

        try:
            tu = self._index.parse(
                path,
                args=self._extra_args,
                options=self._ci.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD,
            )
        except Exception as e:
            result.errors.append(f"libclang TU parse error: {e}")
            return self._fallback_parse(path, lines, result)

        for diag in tu.diagnostics:
            if diag.severity >= self._ci.Diagnostic.Error:
                result.errors.append(f"[{diag.severity}] {diag.spelling}")

        # -- collect includes
        for inc in tu.get_includes():
            if inc.depth == 1:
                result.includes.append(IncludeInfo(
                    included_path=str(inc.include.name) if inc.include else "",
                    line=inc.location.line,
                    is_system=False,
                ))

        # -- walk AST
        self._walk(tu.cursor, path, lines, result, current_func_usr=None)
        return result

    def _walk(self, cursor, file_path: str, lines: list[str], result: ParseResult,
              current_func_usr: str | None):
        ci = self._ci
        kind_val = cursor.kind.value

        # only process nodes that belong to our file
        loc = cursor.location
        if loc.file and str(loc.file.name) != file_path:
            return

        # ── emit symbol ───────────────────────────────────────────────────────
        if kind_val in _SYMBOL_KINDS and cursor.spelling:
            is_def  = cursor.is_definition()
            is_decl = not is_def
            parent = cursor.semantic_parent
            parent_usr = None
            if parent and not parent.kind.is_translation_unit():
                parent_usr = parent.get_usr() or None

            try:
                ret_type = cursor.result_type.spelling if kind_val in _FUNC_KINDS else ""
            except Exception:
                ret_type = ""

            # Collect template parameters for template kinds
            tpl_params = ""
            if kind_val in _TEMPLATE_KINDS:
                tpl_params = _extract_template_params(cursor)

            sym = SymbolInfo(
                name          = cursor.spelling,
                qualified_name= _qualified_name(cursor),
                kind          = _CLANG_KIND_MAP.get(kind_val, cursor.kind.name),
                signature     = cursor.displayname,
                line_start    = loc.line,
                line_end      = cursor.extent.end.line,
                col_start     = loc.column,
                is_definition = is_def,
                is_declaration= is_decl,
                parent_usr    = parent_usr,
                namespace_path= _namespace_path(cursor),
                visibility    = _visibility(cursor),
                return_type   = ret_type,
                usr           = cursor.get_usr(),
                template_params= tpl_params,
            )
            result.symbols.append(sym)

            if kind_val in _FUNC_KINDS:
                current_func_usr = cursor.get_usr()

        # ── emit call ─────────────────────────────────────────────────────────
        elif cursor.kind == ci.CursorKind.CALL_EXPR and current_func_usr:
            called = cursor.referenced
            callee_name = cursor.spelling or (called.spelling if called else "")
            callee_usr  = (called.get_usr() if called else None) or None
            # Determine call type: indirect if callee is unresolved
            call_type = "indirect" if called is None else "direct"
            snippet = ""
            if loc.line > 0 and loc.line <= len(lines):
                snippet = lines[loc.line - 1].strip()
            result.calls.append(CallInfo(
                caller_usr   = current_func_usr,
                callee_name  = callee_name,
                callee_usr   = callee_usr,
                line         = loc.line,
                col          = loc.column,
                code_snippet = snippet,
                call_type    = call_type,
            ))

        # ── emit inheritance ──────────────────────────────────────────────────
        elif cursor.kind == ci.CursorKind.CXX_BASE_SPECIFIER:
            parent = cursor.semantic_parent
            if parent and parent.kind.value in _CLASS_KINDS:
                class_usr = parent.get_usr()
                base_name = cursor.spelling or cursor.displayname or ""
                base_def = cursor.referenced
                base_usr = (base_def.get_usr() if base_def else None) or None
                access = _visibility(cursor)
                is_virtual = cursor.is_virtual_base() if hasattr(cursor, "is_virtual_base") else False
                result.inherits.append(InheritanceInfo(
                    class_usr  = class_usr,
                    base_name  = base_name,
                    base_usr   = base_usr,
                    access     = access,
                    is_virtual = is_virtual,
                ))

        for child in cursor.get_children():
            self._walk(child, file_path, lines, result, current_func_usr)

    # ── regex fallback ────────────────────────────────────────────────────────

    _FUNC_RE = re.compile(
        r'(?:^|\s)(?:(?:static|inline|virtual|explicit|constexpr|override|noexcept)\s+)*'
        r'(?P<ret>[\w:*&<>\s]+?)\s+'
        r'(?P<qname>(?:\w+::)*\w+)\s*\([^;{]*\)\s*(?:const\s*)?(?:override\s*)?(?:noexcept\s*)?[{;]',
        re.MULTILINE,
    )
    _CLASS_RE = re.compile(
        r'^\s*(?:class|struct)\s+(?P<name>\w+)(?:\s*[:{]|\s+final\s*[:{])', re.MULTILINE
    )
    _CALL_RE  = re.compile(r'\b(\w[\w:]*)\s*\(', re.MULTILINE)

    def _fallback_parse(
        self, file_path: str, lines: list[str], result: ParseResult
    ) -> ParseResult:
        result.used_fallback = True
        text = "\n".join(lines)

        # symbols
        for m in self._FUNC_RE.finditer(text):
            lineno = text[:m.start()].count("\n") + 1
            name = m.group("qname")
            result.symbols.append(SymbolInfo(
                name=name, qualified_name=name, kind="FUNCTION",
                signature=m.group(0).strip()[:120],
                line_start=lineno, line_end=lineno, col_start=1,
                is_definition="{" in m.group(0),
                is_declaration=";" in m.group(0),
                parent_usr=None, namespace_path="", visibility="",
                return_type=m.group("ret").strip(),
                usr=f"fallback::{file_path}::{name}::{lineno}",
            ))
        for m in self._CLASS_RE.finditer(text):
            lineno = text[:m.start()].count("\n") + 1
            name = m.group("name")
            result.symbols.append(SymbolInfo(
                name=name, qualified_name=name, kind="CLASS",
                signature=f"class {name}",
                line_start=lineno, line_end=lineno, col_start=1,
                is_definition=True, is_declaration=False,
                parent_usr=None, namespace_path="", visibility="",
                return_type="", usr=f"fallback::{file_path}::{name}::{lineno}",
            ))

        # include directives
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#include"):
                m = re.search(r'[<"](.+?)[>"]', stripped)
                if m:
                    result.includes.append(IncludeInfo(
                        included_path=m.group(1),
                        line=i,
                        is_system=stripped[8:].strip().startswith("<"),
                    ))

        return result
