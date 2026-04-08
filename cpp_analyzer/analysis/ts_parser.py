"""
Tree-sitter based C source parser for structural pattern analysis.
Provides utilities to parse files and extract AST patterns relevant to
configuration analysis (if→assign, struct definitions, field assignments).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import tree_sitter_c as tsc
from tree_sitter import Language, Parser, Node

C_LANG = Language(tsc.language())

_parser = Parser(C_LANG)


def parse_file(path: str | Path) -> Node | None:
    text = Path(path).read_bytes()
    tree = _parser.parse(text)
    return tree.root_node


def parse_bytes(source: bytes) -> Node:
    return _parser.parse(source).root_node


def node_text(node: Node) -> str:
    return node.text.decode("utf-8", errors="replace")


def walk_type(root: Node, node_type: str) -> Iterator[Node]:
    """Yield all descendant nodes of given type."""
    for child in root.children:
        if child.type == node_type:
            yield child
        yield from walk_type(child, node_type)


def walk_named(root: Node) -> Iterator[Node]:
    """Yield all named descendant nodes recursively."""
    for child in root.named_children:
        yield child
        yield from walk_named(child)


# ── struct field extraction ─────────────────────────────────────────────────

def extract_struct_fields(root: Node) -> list[dict]:
    """Extract all struct definitions and their fields from a parsed file.

    Returns list of dicts:
        struct_name, field_name, field_type, line, comment
    """
    results = []
    for struct_node in walk_type(root, "struct_specifier"):
        name_node = struct_node.child_by_field_name("name")
        if name_node is None:
            continue
        struct_name = node_text(name_node)

        body = struct_node.child_by_field_name("body")
        if body is None:
            continue

        for decl in body.named_children:
            if decl.type != "field_declaration":
                continue

            # extract type
            type_node = decl.child_by_field_name("type")
            field_type = node_text(type_node) if type_node else ""

            # extract declarator(s) — may have multiple: int a, b;
            for child in decl.named_children:
                field_name = None
                if child.type == "field_identifier":
                    field_name = node_text(child)
                elif child.type in ("pointer_declarator", "array_declarator"):
                    for sub in walk_named(child):
                        if sub.type == "field_identifier":
                            field_name = node_text(sub)
                            break
                    if field_name and child.type == "pointer_declarator":
                        field_type = field_type + " *"

                if field_name:
                    comment = _find_adjacent_comment(decl)
                    results.append({
                        "struct_name": struct_name,
                        "field_name": field_name,
                        "field_type": field_type.strip(),
                        "line": decl.start_point[0] + 1,
                        "comment": comment,
                    })

    return results


def _find_adjacent_comment(node: Node) -> str:
    """Find inline comment on the same line as a node."""
    node_line = node.start_point[0]

    # check next sibling (inline comment on same line)
    sib = node.next_sibling
    if sib and sib.type == "comment" and sib.start_point[0] == node_line:
        return node_text(sib).strip("/* \t\n/")

    # check non-named siblings too
    sib = node.next_named_sibling
    if sib and sib.type == "comment" and sib.start_point[0] == node_line:
        return node_text(sib).strip("/* \t\n/")

    return ""


# ── if → field assignment patterns ──────────────────────────────────────────

def extract_if_field_overrides(root: Node) -> list[dict]:
    """Find patterns: if (ptr->fieldA <op> val) { ptr->fieldB = forced; }

    Returns list of dicts:
        source_field, condition_op, condition_value,
        target_field, forced_value, line, code_snippet
    """
    results = []
    for if_node in walk_type(root, "if_statement"):
        cond = if_node.child_by_field_name("condition")
        cons = if_node.child_by_field_name("consequence")
        if cond is None or cons is None:
            continue

        # parse condition: look for field_expression <op> value
        cond_info = _parse_field_condition(cond)
        if cond_info is None:
            continue

        # parse consequence: look for field assignments
        assigns = _extract_field_assignments(cons)
        for a in assigns:
            if a["field_name"] != cond_info["field_name"]:
                results.append({
                    "source_field": cond_info["field_name"],
                    "condition_op": cond_info["op"],
                    "condition_value": cond_info["value"],
                    "target_field": a["field_name"],
                    "target_ptr": a["ptr_name"],
                    "forced_value": a["value"],
                    "line": if_node.start_point[0] + 1,
                    "code_snippet": node_text(if_node)[:200],
                })

    return results


def extract_self_overrides(root: Node) -> list[dict]:
    """Find patterns where a field is conditionally reassigned:
        if (<any_condition>) { ptr->fieldA = new_value; }

    This catches cases where a user-set value gets overridden by internal logic,
    e.g. user sets A=2 via CLI, but code does: if (B > 10) A = 1;

    Unlike extract_if_field_overrides which only captures cross-field deps,
    this captures ALL conditional field assignments regardless of what the
    condition checks.

    Returns list of dicts:
        target_field, target_ptr, forced_value,
        condition_text, condition_fields (list of field names in condition),
        line, code_snippet, enclosing_function
    """
    results = []
    for if_node in walk_type(root, "if_statement"):
        cond = if_node.child_by_field_name("condition")
        cons = if_node.child_by_field_name("consequence")
        if cond is None or cons is None:
            continue

        cond_text = node_text(cond).strip()
        # extract all field names referenced in the condition
        cond_fields = _extract_all_field_names(cond)

        assigns = _extract_field_assignments(cons)
        for a in assigns:
            func_name = _find_enclosing_function(if_node)
            results.append({
                "target_field": a["field_name"],
                "target_ptr": a["ptr_name"],
                "forced_value": a["value"],
                "condition_text": cond_text[:200],
                "condition_fields": cond_fields,
                "line": if_node.start_point[0] + 1,
                "code_snippet": node_text(if_node)[:300],
                "enclosing_function": func_name or "",
            })

    return results


def _extract_all_field_names(node: Node) -> list[str]:
    """Extract all field_identifier names within a node (conditions, etc.)."""
    names = []
    for child in walk_type(node, "field_identifier"):
        names.append(node_text(child))
    return list(set(names))


def _parse_field_condition(cond_node: Node) -> dict | None:
    """Parse a condition like (ptr->field == value)."""
    # unwrap parenthesized_expression
    inner = cond_node
    if inner.type == "parenthesized_expression" and inner.named_child_count > 0:
        inner = inner.named_children[0]

    if inner.type == "binary_expression":
        left = inner.child_by_field_name("left")
        right = inner.child_by_field_name("right")
        op_node = inner.child_by_field_name("operator")

        if left is None or right is None:
            return None

        # get operator from children
        op = ""
        for child in inner.children:
            if not child.is_named and child.type in ("==", "!=", "<", ">", "<=", ">="):
                op = child.type
                break
        if not op and op_node:
            op = node_text(op_node)

        field_name = _extract_field_name(left)
        if field_name is None:
            field_name = _extract_field_name(right)
            value = node_text(left).strip()
        else:
            value = node_text(right).strip()

        if field_name:
            return {"field_name": field_name, "op": op, "value": value}

    return None


def _extract_field_name(node: Node) -> str | None:
    """Extract field name from field_expression (ptr->field or obj.field)."""
    if node.type == "field_expression":
        field = node.child_by_field_name("field")
        if field:
            return node_text(field)
    return None


def _extract_ptr_name(node: Node) -> str | None:
    """Extract pointer/object name from field_expression."""
    if node.type == "field_expression":
        arg = node.child_by_field_name("argument")
        if arg:
            return node_text(arg)
    return None


def _extract_field_assignments(node: Node) -> list[dict]:
    """Extract all field assignments (ptr->field = value) within a node."""
    results = []
    for assign in walk_type(node, "assignment_expression"):
        left = assign.child_by_field_name("left")
        right = assign.child_by_field_name("right")
        if left is None or right is None:
            continue

        field_name = _extract_field_name(left)
        ptr_name = _extract_ptr_name(left)
        if field_name:
            results.append({
                "field_name": field_name,
                "ptr_name": ptr_name or "",
                "value": node_text(right).strip(),
                "line": assign.start_point[0] + 1,
            })
    return results


# ── CLI handler → field assignment mapping ──────────────────────────────────

def extract_cli_handler_assignments(root: Node) -> list[dict]:
    """Find CLI arg handlers that set struct fields.

    Detects patterns:
        if (keymatch(arg, "name", N)) { ptr->field = val; }
        case 'x': ptr->field = val; break;
        if (strcmp(argv[i], "--name") == 0) { ptr->field = val; }

    Returns list of dicts:
        cli_flag, assignments: [{field_name, value}], line
    """
    results = []

    for if_node in walk_type(root, "if_statement"):
        cond = if_node.child_by_field_name("condition")
        cons = if_node.child_by_field_name("consequence")
        if cond is None or cons is None:
            continue

        cli_flag = _extract_cli_flag_from_condition(cond)
        if cli_flag is None:
            continue

        assigns = _extract_field_assignments(cons)
        if assigns:
            results.append({
                "cli_flag": cli_flag,
                "assignments": assigns,
                "line": if_node.start_point[0] + 1,
            })

    return results


def _extract_cli_flag_from_condition(cond_node: Node) -> str | None:
    """Extract CLI flag name from various parser patterns."""
    text = node_text(cond_node)

    # keymatch(arg, "name", N)
    import re
    m = re.search(r'keymatch\s*\(\s*\w+\s*,\s*"([^"]+)"', text)
    if m:
        return f"-{m.group(1)}"

    # strcmp(argv[x], "--name") or strcmp(argv[x], "-name")
    m = re.search(r'strn?cmp\s*\(\s*argv\s*\[.*?\]\s*,\s*"(-{1,2}[^"]+)"', text)
    if m:
        return m.group(1)

    # getopt case: not in if_statement but in switch case
    return None


# ── bulk assignment detection (defaults functions) ──────────────────────────

def extract_bulk_assignments(root: Node, min_count: int = 5) -> list[dict]:
    """Find functions with many field assignments to the same pointer.
    These are likely config initialization functions.

    Returns list of dicts:
        function_name, ptr_name, assignments: [{field, value, line}], line_start
    """
    results = []
    for func in walk_type(root, "function_definition"):
        decl = func.child_by_field_name("declarator")
        body = func.child_by_field_name("body")
        if decl is None or body is None:
            continue

        func_name = _get_function_name(decl)
        if not func_name:
            continue

        assigns = _extract_field_assignments(body)
        # group by pointer name
        by_ptr: dict[str, list[dict]] = {}
        for a in assigns:
            by_ptr.setdefault(a["ptr_name"], []).append(a)

        for ptr_name, ptr_assigns in by_ptr.items():
            if len(ptr_assigns) >= min_count:
                results.append({
                    "function_name": func_name,
                    "ptr_name": ptr_name,
                    "assignments": [
                        {"field": a["field_name"], "value": a["value"], "line": a["line"]}
                        for a in ptr_assigns
                    ],
                    "line_start": func.start_point[0] + 1,
                })

    return results


def _get_function_name(declarator: Node) -> str | None:
    """Extract function name from a function declarator node."""
    if declarator.type == "function_declarator":
        name = declarator.child_by_field_name("declarator")
        if name:
            return node_text(name)
    # handle pointer_declarator wrapping
    for child in walk_named(declarator):
        if child.type == "identifier":
            return node_text(child)
    return None


# ── switch/if-chain cascade detection ───────────────────────────────────────

def extract_cascade_patterns(root: Node, min_branches: int = 3) -> list[dict]:
    """Detect switch or if-else chains where one config value
    determines multiple field assignments across branches.

    Returns list of dicts:
        switch_field, branches: [{case_value, assignments}], line, function
    """
    results = []

    # switch statements
    for switch in walk_type(root, "switch_statement"):
        cond = switch.child_by_field_name("condition")
        body = switch.child_by_field_name("body")
        if not cond or not body:
            continue

        field = None
        inner = cond
        if inner.type == "parenthesized_expression" and inner.named_child_count:
            inner = inner.named_children[0]
        field = _extract_field_name(inner)
        if not field:
            continue

        branches = []
        for case_node in walk_type(body, "case_statement"):
            case_val_node = case_node.child_by_field_name("value")
            case_val = node_text(case_val_node) if case_val_node else "default"
            assigns = _extract_field_assignments(case_node)
            if assigns:
                branches.append({
                    "case_value": case_val,
                    "assignments": [
                        {"field": a["field_name"], "value": a["value"]}
                        for a in assigns
                    ],
                })

        if len(branches) >= min_branches:
            func_name = _find_enclosing_function(switch)
            results.append({
                "switch_field": field,
                "branches": branches,
                "line": switch.start_point[0] + 1,
                "function": func_name or "",
            })

    return results


def _find_enclosing_function(node: Node) -> str | None:
    """Walk up the tree to find the enclosing function name."""
    current = node.parent
    while current:
        if current.type == "function_definition":
            decl = current.child_by_field_name("declarator")
            if decl:
                return _get_function_name(decl)
        current = current.parent
    return None


# ── macro extraction ────────────────────────────────────────────────────────

def extract_macros_with_assignments(root: Node) -> list[dict]:
    """Find #define macros whose body contains field assignments.

    Returns list of dicts:
        macro_name, params, body, line
    """
    import re
    results = []
    for node in walk_type(root, "preproc_function_def"):
        name_node = node.child_by_field_name("name")
        if not name_node:
            continue
        macro_name = node_text(name_node)
        body = node_text(node)
        # check if body has -> assignment pattern
        if re.search(r'\w+->\w+\s*=', body):
            params_node = node.child_by_field_name("parameters")
            params = node_text(params_node) if params_node else ""
            results.append({
                "macro_name": macro_name,
                "params": params,
                "body": body[:500],
                "line": node.start_point[0] + 1,
            })
    return results


# ── dataflow: all assignments + call arguments ────────────────────────────

def extract_all_assignments(root: Node) -> list[dict]:
    """Extract all assignments within function bodies for dataflow analysis.

    Captures both assignment_expression (a = b) and init_declarator (int a = b),
    including compound assignments (+=, |=, <<=, etc.).

    Returns list of dicts sorted by line:
        lhs, rhs, rhs_vars (list), operator, transform, line, function
    """
    import re
    results = []

    for func in walk_type(root, "function_definition"):
        decl = func.child_by_field_name("declarator")
        body = func.child_by_field_name("body")
        if decl is None or body is None:
            continue
        func_name = _get_function_name(decl) or ""

        # 1. assignment_expression: a = b, a += b, a |= b, etc.
        for assign in walk_type(body, "assignment_expression"):
            left = assign.child_by_field_name("left")
            right = assign.child_by_field_name("right")
            if left is None or right is None:
                continue

            lhs = node_text(left).strip()
            rhs = node_text(right).strip()

            # extract operator (=, +=, |=, <<=, etc.)
            operator = "="
            for child in assign.children:
                if not child.is_named and child.type not in (lhs, rhs):
                    op_text = child.type
                    if "=" in op_text:
                        operator = op_text
                        break

            # compute transform for compound assignments
            transform = ""
            if operator != "=":
                base_op = operator.replace("=", "")
                transform = f"{base_op} {rhs}"

            rhs_vars = _extract_variables(right)
            results.append({
                "lhs": lhs,
                "rhs": rhs,
                "rhs_vars": rhs_vars,
                "operator": operator,
                "transform": transform,
                "line": assign.start_point[0] + 1,
                "function": func_name,
            })

        # 2. init_declarator: int a = b; auto* p = &config;
        for init_decl in walk_type(body, "init_declarator"):
            declarator = init_decl.child_by_field_name("declarator")
            value = init_decl.child_by_field_name("value")
            if declarator is None or value is None:
                continue

            lhs = node_text(declarator).strip()
            rhs = node_text(value).strip()
            rhs_vars = _extract_variables(value)

            results.append({
                "lhs": lhs,
                "rhs": rhs,
                "rhs_vars": rhs_vars,
                "operator": "=",
                "transform": "",
                "line": init_decl.start_point[0] + 1,
                "function": func_name,
            })

    results.sort(key=lambda x: (x["function"], x["line"]))
    return results


def extract_call_arguments(root: Node) -> list[dict]:
    """Extract call expressions and their arguments for inter-procedural analysis.

    Returns list of dicts:
        callee_name, args (list of {index, expression}), line, function
    """
    results = []

    for func in walk_type(root, "function_definition"):
        decl = func.child_by_field_name("declarator")
        body = func.child_by_field_name("body")
        if decl is None or body is None:
            continue
        func_name = _get_function_name(decl) or ""

        for call in walk_type(body, "call_expression"):
            callee_node = call.child_by_field_name("function")
            args_node = call.child_by_field_name("arguments")
            if callee_node is None or args_node is None:
                continue

            callee_name = node_text(callee_node).strip()
            args = []
            idx = 0
            for arg in args_node.named_children:
                args.append({
                    "index": idx,
                    "expression": node_text(arg).strip(),
                })
                idx += 1

            results.append({
                "callee_name": callee_name,
                "args": args,
                "line": call.start_point[0] + 1,
                "function": func_name,
            })

    return results


def extract_function_params(root: Node) -> list[dict]:
    """Extract function parameter lists for argument-to-parameter mapping.

    Returns list of dicts:
        function_name, params (list of {index, name, type}), line
    """
    results = []

    for func in walk_type(root, "function_definition"):
        decl = func.child_by_field_name("declarator")
        if decl is None:
            continue
        func_name = _get_function_name(decl) or ""

        # find parameter_list within the declarator
        params = []
        for param_list in walk_type(decl, "parameter_list"):
            idx = 0
            for param in param_list.named_children:
                if param.type == "parameter_declaration":
                    p_type_node = param.child_by_field_name("type")
                    p_decl_node = param.child_by_field_name("declarator")
                    p_type = node_text(p_type_node).strip() if p_type_node else ""
                    p_name = ""
                    if p_decl_node:
                        # handle pointer_declarator, reference_declarator wrapping
                        for sub in walk_named(p_decl_node):
                            if sub.type == "identifier":
                                p_name = node_text(sub)
                                break
                        if not p_name:
                            p_name = node_text(p_decl_node).strip()
                    params.append({
                        "index": idx,
                        "name": p_name,
                        "type": p_type,
                    })
                    idx += 1
            break  # only first parameter_list

        results.append({
            "function_name": func_name,
            "params": params,
            "line": func.start_point[0] + 1,
        })

    return results


def _extract_variables(node: Node) -> list[str]:
    """Extract all variable/field references from an expression node."""
    vars_found = []

    # handle root node itself being a field_expression
    if node.type == "field_expression":
        vars_found.append(node_text(node).strip())
        return vars_found

    # field expressions: ptr->field, obj.field
    for fe in walk_type(node, "field_expression"):
        vars_found.append(node_text(fe).strip())

    # plain identifiers (but not those already part of field_expressions)
    field_expr_ranges = set()
    for fe in walk_type(node, "field_expression"):
        for i in range(fe.start_byte, fe.end_byte):
            field_expr_ranges.add(i)

    for ident in walk_type(node, "identifier"):
        if ident.start_byte not in field_expr_ranges:
            name = node_text(ident).strip()
            # skip common non-variable identifiers (function names in calls)
            parent = ident.parent
            if parent and parent.type == "call_expression":
                func_node = parent.child_by_field_name("function")
                if func_node and ident.start_byte == func_node.start_byte:
                    continue
            vars_found.append(name)

    return vars_found
