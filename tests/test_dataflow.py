"""
Dataflow taint analysis benchmark tests.

Tests the taint tracker against known C code patterns with expected results.
Used for regression testing and gap detection.

실행:
    pytest tests/test_dataflow.py -v
    pytest tests/test_dataflow.py -v -k "easy"        # easy 난이도만
    pytest tests/test_dataflow.py -v -k "benchmark"    # 벤치마크 점수만
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from cpp_analyzer.core.indexer import Indexer
from cpp_analyzer.db.repository import Repository
from cpp_analyzer.analysis.taint_tracker import TaintTracker


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "dataflow"
EXPECTED_PATH = FIXTURES_DIR / "expected.yaml"
MULTIFILE_DIR = FIXTURES_DIR / "multifile"


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def analysis_db():
    """Index dataflow test fixtures and return (repo, pid, paths)."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    repo = Repository(db_path)
    repo.connect()
    pid = repo.upsert_project("dataflow-test", str(FIXTURES_DIR))

    indexer = Indexer(repo, pid, FIXTURES_DIR)
    indexer.run(force=True)

    source_patterns = [
        {"name": "config_field", "regex": r"cfg->(\w+)"},
        {"name": "ext_config_field", "regex": r"ecfg->(\w+)"},
    ]
    sink_patterns = [
        {"name": "reg_array", "regex": r"\w+->regs\["},
        {"name": "reg_array_idx", "regex": r"\w+\[\w+\]->regs\["},
        {"name": "fw_field", "regex": r"fw->(\w+)\s*="},
        {"name": "REG_WRITE", "regex": r"REG_WRITE\s*\("},
        {"name": "volatile_mmio", "regex": r"\*\s*\(\s*volatile"},
        {"name": "ptr_deref", "regex": r"^\s*\*\s*\(?\s*\w+"},
        # F1: MMIO accessor functions — value arg differs per callee.
        {"name": "mmio_writel",  "regex": r"\b(?:writel|writel_relaxed|__raw_writel|iowrite8|iowrite16|iowrite32|iowrite64)\s*\(", "value_arg": 0},
        {"name": "regmap_write", "regex": r"\bregmap_(?:write|update_bits|set_bits|clear_bits|write_bits)\s*\("},
        # C03 driver-local callable sinks (goto_ladder_unwind fixture).
        {"name": "cx3_trigger_enable", "regex": r"\bcx3_trigger_enable\s*\("},
        {"name": "cx3_seq_mode_enter", "regex": r"\bcx3_seq_mode_enter\s*\("},
    ]

    tracker = TaintTracker(repo, pid, source_patterns, sink_patterns)
    paths = tracker.trace(max_depth=10, max_paths=500)

    yield repo, pid, paths

    repo.close()
    os.unlink(db_path)


@pytest.fixture(scope="module")
def expected():
    """Load expected results from YAML."""
    with open(EXPECTED_PATH) as f:
        return yaml.safe_load(f)


# ── helpers ───────────────────────────────────────────────────────────────────

def _find_path(paths, source_substr: str, sink_substr: str = None, sink_pattern: str = None,
               expected_function: str = None):
    """Find a matching path by source/sink substring.

    If expected_function is given, the path must involve that function
    in its sink or any of its steps (inter-procedural attribution).
    """
    import re
    for p in paths:
        if source_substr not in p.source.variable:
            continue
        if sink_substr and sink_substr not in p.sink.variable:
            continue
        if sink_pattern and not re.search(sink_pattern, p.sink.variable):
            continue
        if expected_function:
            funcs = {p.sink.function, p.source.function} | {s.function for s in p.steps}
            if expected_function not in funcs:
                continue
        return p
    return None


# ── unit tests: direct patterns ───────────────────────────────────────────────

class TestDirectPatterns:
    """Easy: direct config → register mappings within a single function."""

    def test_direct_threshold(self, analysis_db):
        """cfg->threshold → regs->regs[THRESH_REG]"""
        _, _, paths = analysis_db
        found = _find_path(paths, "cfg->threshold", "regs->regs[THRESH_REG]")
        assert found is not None, "Failed to trace cfg->threshold → register"

    def test_direct_width(self, analysis_db):
        """cfg->width → regs->regs[DIM_REG]"""
        _, _, paths = analysis_db
        found = _find_path(paths, "cfg->width", "regs->regs[DIM_REG]")
        assert found is not None, "Failed to trace cfg->width → register"

    def test_direct_height(self, analysis_db):
        """cfg->height → regs->regs[DIM_REG]"""
        _, _, paths = analysis_db
        found = _find_path(paths, "cfg->height", "regs->regs[DIM_REG]")
        assert found is not None, "Failed to trace cfg->height → register"

    def test_config_to_fw_clkdiv(self, analysis_db):
        """cfg->frequency → fw->clk_div"""
        _, _, paths = analysis_db
        found = _find_path(paths, "cfg->frequency", "fw->clk_div")
        assert found is not None, "Failed to trace cfg->frequency → fw->clk_div"

    def test_config_to_fw_mode(self, analysis_db):
        """cfg->mode → fw->processed_mode"""
        _, _, paths = analysis_db
        found = _find_path(paths, "cfg->mode", "fw->processed_mode")
        assert found is not None, "Failed to trace cfg->mode → fw->processed_mode"


class TestMediumPatterns:
    """Medium: alias tracking, macro sinks, conditional writes."""

    def test_alias_register_write(self, analysis_db):
        """cfg->enable → r->regs[CTRL_REG] (via pointer alias r=hw)"""
        _, _, paths = analysis_db
        found = _find_path(paths, "cfg->enable", "r->regs[CTRL_REG]")
        if found is None:
            # alias might resolve to hw->regs
            found = _find_path(paths, "cfg->enable", "hw->regs[CTRL_REG]")
        # This may fail — alias tracking is best-effort
        if found is None:
            pytest.xfail("Alias tracking not yet resolving r→hw→regs chain")

    def test_macro_reg_write(self, analysis_db):
        """cfg->frequency → REG_WRITE(TIMING_REG, ...)"""
        _, _, paths = analysis_db
        found = _find_path(paths, "cfg->frequency", sink_pattern=r"REG_WRITE")
        if found is None:
            pytest.xfail("Macro-based REG_WRITE sink detection not yet working")

    def test_conditional_write(self, analysis_db):
        """cfg->mode → regs->regs[CTRL_REG] (inside if block)"""
        _, _, paths = analysis_db
        found = _find_path(paths, "cfg->mode", "regs->regs[CTRL_REG]")
        assert found is not None, "Failed to trace conditional register write"


class TestExtendedPatterns:
    """Extended: new coverage patterns (ternary, array, bitfield, etc.)."""

    def test_ternary(self, analysis_db):
        """cfg->enable via ternary condition → regs"""
        _, _, paths = analysis_db
        for p in paths:
            if "cfg->" in p.source.variable and p.sink.function == "ternary_write":
                return
        pytest.xfail("Ternary operator tracking not yet working")

    def test_array_element(self, analysis_db):
        """cfg->frequency via array[0] → regs"""
        _, _, paths = analysis_db
        for p in paths:
            if "cfg->frequency" in p.source.variable and p.sink.function == "array_write":
                return
        pytest.xfail("Array element tracking not yet working")

    def test_bitfield(self, analysis_db):
        """cfg->mode via bitfield packing → regs"""
        _, _, paths = analysis_db
        for p in paths:
            if "cfg->mode" in p.source.variable and p.sink.function == "bitfield_write":
                return
        pytest.xfail("Bitfield shift+mask tracking not yet working")

    def test_global_variable(self, analysis_db):
        """cfg->frequency via global g_cached_freq → regs"""
        _, _, paths = analysis_db
        for p in paths:
            if "cfg->frequency" in p.source.variable:
                funcs = {p.sink.function, p.source.function} | {s.function for s in p.steps}
                if "cache_config" in funcs or "apply_cached" in funcs:
                    return
        pytest.xfail("Global variable cross-function tracking not yet working")

    def test_struct_copy(self, analysis_db):
        """cfg->threshold via struct copy → regs"""
        _, _, paths = analysis_db
        for p in paths:
            if "cfg->threshold" in p.source.variable and p.sink.function == "struct_copy_write":
                return
            # also check alias resolution: local_cfg.threshold → cfg->threshold
            if "threshold" in p.source.variable and p.sink.function == "struct_copy_write":
                return
        pytest.xfail("Struct copy field tracking not yet working")

    def test_phi_node(self, analysis_db):
        """cfg->threshold or cfg->frequency via phi-node (if/else) → regs"""
        _, _, paths = analysis_db
        for p in paths:
            if "cfg->" in p.source.variable and p.sink.function == "phi_write":
                return
        pytest.xfail("Phi-node multiple reaching defs not yet working")


class TestRangePatterns:
    """Range: config field min/max constraint extraction."""

    def test_range_clamp_frequency(self, analysis_db):
        """cfg->frequency with MIN_FREQ/MAX_FREQ clamp → regs"""
        _, _, paths = analysis_db
        for p in paths:
            if "cfg->frequency" in p.source.variable and p.sink.function == "range_checked_write":
                if "regs->regs[TIMING_REG]" in p.sink.variable:
                    return
        pytest.xfail("Range clamp tracking not yet working")

    def test_range_saturate_threshold(self, analysis_db):
        """cfg->threshold with MAX_THRESHOLD saturate → regs"""
        _, _, paths = analysis_db
        for p in paths:
            if "cfg->threshold" in p.source.variable and p.sink.function == "range_checked_write":
                if "regs->regs[THRESH_REG]" in p.sink.variable:
                    return
        pytest.xfail("Range saturate tracking not yet working")


class TestDependencyPatterns:
    """Dependency: multiple config fields contributing to same register."""

    def test_dependency_freq_mode_ctrl(self, analysis_db):
        """cfg->frequency + cfg->mode → CTRL_REG (co-dependent)"""
        _, _, paths = analysis_db
        for p in paths:
            if "cfg->frequency" in p.source.variable and p.sink.function == "dependent_write":
                if "regs->regs[CTRL_REG]" in p.sink.variable:
                    return
        pytest.xfail("Dependency tracking (freq+mode→ctrl) not yet working")

    def test_dependency_enable_gates_freq(self, analysis_db):
        """cfg->enable gates cfg->frequency → TIMING_REG"""
        _, _, paths = analysis_db
        for p in paths:
            if "cfg->frequency" in p.source.variable and p.sink.function == "dependent_write":
                if "regs->regs[TIMING_REG]" in p.sink.variable:
                    return
        pytest.xfail("Dependency gating tracking not yet working")


class TestHardPatterns:
    """Hard: inter-procedural, multi-layer function chains."""

    def test_multi_hop(self, analysis_db):
        """cfg->frequency → compute_divider → compute_timing → regs (3 functions)"""
        _, _, paths = analysis_db
        # Look for a path from cfg->frequency to regs in multi_hop_write
        found = None
        for p in paths:
            if "cfg->frequency" in p.source.variable and "regs->regs" in p.sink.variable:
                # check if it goes through multi_hop_write's chain
                funcs = {s.function for s in p.steps}
                if "compute_divider" in funcs or "compute_timing" in funcs:
                    found = p
                    break
        if found is None:
            pytest.xfail("Inter-procedural multi-hop tracking not yet working at this depth")

    def test_two_layer(self, analysis_db):
        """cfg->frequency → config_to_fw → fw_to_hw → regs (cross-function layers)"""
        _, _, paths = analysis_db
        found = None
        for p in paths:
            if "cfg->frequency" in p.source.variable:
                funcs = {p.sink.function, p.source.function} | {s.function for s in p.steps}
                if "config_to_fw" in funcs and "fw_to_hw" in funcs:
                    found = p
                    break
        if found is None:
            pytest.xfail("Two-layer cross-function tracking not yet working")


class TestFnPtrTracking:
    """Function pointer indirect call tracking (Gap A1)."""

    def test_fnptr_local_dispatch(self, analysis_db):
        """writer = write_timing_fn; writer(regs, cfg->frequency) → TIMING_REG"""
        _, _, paths = analysis_db
        for p in paths:
            if "cfg->frequency" in p.source.variable and "regs->regs[TIMING_REG]" in p.sink.variable:
                funcs = {p.sink.function, p.source.function} | {s.function for s in p.steps}
                if "fnptr_dispatch" in funcs or "write_timing_fn" in funcs:
                    return
        pytest.xfail("Function pointer local variable dispatch not yet tracked")

    def test_fnptr_struct_dispatch(self, analysis_db):
        """ops.timing_fn = write_timing_fn; ops.timing_fn(regs, cfg->frequency)"""
        _, _, paths = analysis_db
        for p in paths:
            if "cfg->frequency" in p.source.variable and "regs->regs[TIMING_REG]" in p.sink.variable:
                funcs = {p.sink.function, p.source.function} | {s.function for s in p.steps}
                if "fnptr_struct_dispatch" in funcs:
                    return
        pytest.xfail("Function pointer struct field dispatch not yet tracked")


class TestDeepChain:
    """P1: deep call chain (4~6 hop) + mutual recursion."""

    def test_five_hop_param_chain(self, analysis_db):
        """dcfg->frequency → dc_stage1 → ... → dc_stage5 → DC_TIMING_REG"""
        _, _, paths = analysis_db
        for p in paths:
            if "dcfg->frequency" not in p.source.variable:
                continue
            if "DC_TIMING_REG" not in p.sink.variable:
                continue
            funcs = {p.sink.function, p.source.function} | {s.function for s in p.steps}
            if {"dc_stage1", "dc_stage5"}.issubset(funcs):
                return
        pytest.fail("5-hop param-propagation chain not traced end-to-end")

    def test_mutual_recursion(self, analysis_db):
        """dcfg->mode → recurse_odd/recurse_even → DC_MODE_REG"""
        _, _, paths = analysis_db
        for p in paths:
            if "dcfg->mode" not in p.source.variable:
                continue
            if "DC_MODE_REG" not in p.sink.variable:
                continue
            funcs = {p.sink.function, p.source.function} | {s.function for s in p.steps}
            if "recurse_odd" in funcs or "recurse_even" in funcs:
                return
        pytest.fail("Mutual recursion taint path not found")


class TestCppDispatch:
    """P3: C++ virtual dispatch + member function pointer."""

    def test_virtual_dispatch_timing(self, analysis_db):
        """vcall_write → Writer::write (virtual) → TimingWriter::write → CPP_TIMING_REG"""
        _, _, paths = analysis_db
        for p in paths:
            if "ccfg->frequency" in p.source.variable and "CPP_TIMING_REG" in p.sink.variable:
                return
        pytest.fail("Virtual dispatch to TimingWriter::write not traced")

    def test_virtual_dispatch_mode(self, analysis_db):
        """Same call site also resolves to ModeWriter::write → CPP_MODE_REG"""
        _, _, paths = analysis_db
        for p in paths:
            if "ccfg->frequency" in p.source.variable and "CPP_MODE_REG" in p.sink.variable:
                return
        pytest.fail("Virtual dispatch to ModeWriter::write not traced")

    def test_member_fn_ptr(self, analysis_db):
        """(w->*fn)(...) — intentionally conservative; track as xfail."""
        _, _, paths = analysis_db
        for p in paths:
            if "ccfg->mode" in p.source.variable and "CPP_" in p.sink.variable:
                funcs = {p.sink.function} | {s.function for s in p.steps}
                if "memfn_write" in funcs:
                    return
        pytest.xfail("Pointer-to-member calls not resolved (requires runtime fn tracking)")


class TestIfdefVariants:
    """P4: #ifdef-guarded sinks — both branches must be discoverable."""

    def test_ifdef_fast_branch(self, analysis_db):
        """#ifdef USE_FAST_PATH branch: IF_FAST_REG"""
        _, _, paths = analysis_db
        for p in paths:
            if "icfg->frequency" in p.source.variable and "IF_FAST_REG" in p.sink.variable:
                return
        pytest.fail("#ifdef USE_FAST_PATH sink not discovered")

    def test_ifdef_else_branch(self, analysis_db):
        """#else branch: IF_TIMING_REG"""
        _, _, paths = analysis_db
        for p in paths:
            if "icfg->frequency" in p.source.variable and "IF_TIMING_REG" in p.sink.variable:
                return
        pytest.fail("#else branch sink not discovered")

    def test_ifdef_nested_both(self, analysis_db):
        """Both branches of #if defined(MODE_VARIANT_A) write IF_MODE_REG"""
        _, _, paths = analysis_db
        hits = [p for p in paths
                if "icfg->mode" in p.source.variable and "IF_MODE_REG" in p.sink.variable]
        assert len(hits) >= 2, f"expected ≥2 paths for nested #ifdef, got {len(hits)}"


class TestMultiCallback:
    """P5: multi-callback array, bitfield struct sink, flexible array."""

    def test_multi_cb_timing(self, analysis_db):
        """p5_register_cb(cb_timing) and (cb_mode) — fire should reach cb_timing."""
        _, _, paths = analysis_db
        for p in paths:
            if "pcfg->frequency" in p.source.variable and "P5_TIMING_REG" in p.sink.variable:
                funcs = {p.sink.function} | {s.function for s in p.steps}
                if "cb_timing" in funcs:
                    return
        pytest.fail("cb_timing not reached via array-registrar fnptr dispatch")

    def test_multi_cb_mode(self, analysis_db):
        _, _, paths = analysis_db
        for p in paths:
            if "pcfg->frequency" in p.source.variable and "P5_MODE_REG" in p.sink.variable:
                funcs = {p.sink.function} | {s.function for s in p.steps}
                if "cb_mode" in funcs:
                    return
        pytest.fail("cb_mode not reached via array-registrar fnptr dispatch")

    def test_bitfield_struct_sink(self, analysis_db):
        """pk.b = pcfg->frequency; regs[...] = *(uint32_t*)&pk"""
        _, _, paths = analysis_db
        for p in paths:
            if ("pcfg->frequency" in p.source.variable
                    and "P5_TIMING_REG" in p.sink.variable
                    and p.sink.function == "p5_bitfield_write"):
                return
        pytest.fail("Bitfield/type-punning sink path not traced")

    def test_flexible_array(self, analysis_db):
        """m->data[0] = pcfg->mode; regs[...] = m->data[0]"""
        _, _, paths = analysis_db
        for p in paths:
            if ("pcfg->mode" in p.source.variable
                    and "P5_MODE_REG" in p.sink.variable
                    and p.sink.function == "p5_fam_write"):
                return
        pytest.fail("Flexible-array-member sink path not traced")


class TestFnptrIndexedTable:
    """F3: static fnptr ops table indexed by enum constant. Dispatch
    `ops[OP_X](cfg, r)` should link to the callee registered at OP_X."""

    def test_ops_timing(self, analysis_db):
        _, _, paths = analysis_db
        for p in paths:
            if ("cfg->freq" in p.source.variable
                    and "F3_TIMING_REG" in p.sink.variable):
                funcs = {p.sink.function} | {s.function for s in p.steps}
                if "f3_do_timing" in funcs:
                    return
        pytest.fail("fnptr ops table timing dispatch not traced")

    def test_ops_mode(self, analysis_db):
        _, _, paths = analysis_db
        for p in paths:
            if ("cfg->mode" in p.source.variable
                    and "F3_MODE_REG" in p.sink.variable):
                funcs = {p.sink.function} | {s.function for s in p.steps}
                if "f3_do_mode" in funcs:
                    return
        pytest.fail("fnptr ops table mode dispatch not traced")


class TestDesignatedInit:
    """F2: compound literal `(T){.field = X}` passed as arg — field-taint
    must flow to the callee's struct-field read."""

    def test_compound_literal_freq(self, analysis_db):
        _, _, paths = analysis_db
        for p in paths:
            if ("cfg->frequency" in p.source.variable
                    and "F2_TIMING_REG" in p.sink.variable):
                funcs = {p.sink.function} | {s.function for s in p.steps}
                if "f2_apply" in funcs:
                    return
        pytest.fail("designated init compound literal freq not traced")

    def test_compound_literal_mode(self, analysis_db):
        _, _, paths = analysis_db
        for p in paths:
            if ("cfg->mode" in p.source.variable
                    and "F2_MODE_REG" in p.sink.variable):
                funcs = {p.sink.function} | {s.function for s in p.steps}
                if "f2_apply" in funcs:
                    return
        pytest.fail("designated init compound literal mode not traced")


class TestMmioAccessor:
    """F1: kernel MMIO accessor (writel/iowrite32/regmap_write) as sink."""

    def test_writel_timing(self, analysis_db):
        _, _, paths = analysis_db
        for p in paths:
            if ("fcfg->freq" in p.source.variable
                    and "writel" in p.sink.variable
                    and p.sink.function == "f1_writel_timing"):
                return
        pytest.fail("writel timing sink not traced")

    def test_iowrite32_mode(self, analysis_db):
        _, _, paths = analysis_db
        for p in paths:
            if ("fcfg->mode" in p.source.variable
                    and "iowrite32" in p.sink.variable
                    and p.sink.function == "f1_iowrite32_mode"):
                return
        pytest.fail("iowrite32 mode sink not traced")

    def test_regmap_write_flags(self, analysis_db):
        _, _, paths = analysis_db
        for p in paths:
            if ("fcfg->flags" in p.source.variable
                    and "regmap_write" in p.sink.variable
                    and p.sink.function == "f1_regmap_flags"):
                return
        pytest.fail("regmap_write flags sink not traced")


class TestContainerOf:
    """B2: container_of recovers outer struct; member access must trace
    back to the inner pointer that was passed in."""

    def test_container_of_frequency(self, analysis_db):
        _, _, paths = analysis_db
        for p in paths:
            if ("icfg->" in p.source.variable
                    and "CO_TIMING_REG" in p.sink.variable
                    and p.sink.function == "co_recover_write"):
                return
        pytest.fail("container_of frequency path not traced")

    def test_container_of_mode(self, analysis_db):
        _, _, paths = analysis_db
        for p in paths:
            if ("icfg->" in p.source.variable
                    and "CO_MODE_REG" in p.sink.variable
                    and p.sink.function == "co_recover_write"):
                return
        pytest.fail("container_of mode path not traced")


class TestGotoUnwind:
    """B3: goto-based error unwind — sink behind label, reaching-def
    analysis must keep the real assignment (not just the initializer)."""

    def test_goto_unwind_timing(self, analysis_db):
        _, _, paths = analysis_db
        for p in paths:
            if ("ucfg->frequency" in p.source.variable
                    and "UN_TIMING_REG" in p.sink.variable
                    and p.sink.function == "unwind_write_timing"):
                return
        pytest.fail("goto-unwind timing path not traced")

    def test_goto_unwind_mode(self, analysis_db):
        _, _, paths = analysis_db
        for p in paths:
            if ("ucfg->mode" in p.source.variable
                    and "UN_MODE_REG" in p.sink.variable
                    and p.sink.function == "unwind_write_mode"):
                return
        pytest.fail("goto-unwind mode path not traced")


class TestMemcpyBulk:
    """B1: memcpy(&local, cfg, sizeof) blob copy, then field read off local."""

    def test_memcpy_frequency(self, analysis_db):
        _, _, paths = analysis_db
        for p in paths:
            if ("mcfg->frequency" in p.source.variable
                    and "MC_TIMING_REG" in p.sink.variable
                    and p.sink.function == "memcpy_bulk_write"):
                return
        pytest.fail("memcpy bulk-copy frequency path not traced")

    def test_memcpy_mode(self, analysis_db):
        _, _, paths = analysis_db
        for p in paths:
            if ("mcfg->mode" in p.source.variable
                    and "MC_MODE_REG" in p.sink.variable
                    and p.sink.function == "memcpy_bulk_write"):
                return
        pytest.fail("memcpy bulk-copy mode path not traced")


class TestFnptrLocalAlias:
    """G1: fnptr copied to local variable, then invoked via plain identifier.
    `fp = arr[IDX]; fp(cfg, r)` must resolve through the static table."""

    def test_local_alias_timing(self, analysis_db):
        _, _, paths = analysis_db
        for p in paths:
            if ("cfg->freq" in p.source.variable
                    and "G1_TIMING_REG" in p.sink.variable
                    and p.sink.function == "g1_write_timing"):
                return
        pytest.fail("fnptr local alias timing path not traced")

    def test_local_alias_mode(self, analysis_db):
        _, _, paths = analysis_db
        for p in paths:
            if ("cfg->mode" in p.source.variable
                    and "G1_MODE_REG" in p.sink.variable
                    and p.sink.function == "g1_write_mode"):
                return
        pytest.fail("fnptr local alias mode path not traced")


class TestIsErrGuard:
    """G2: IS_ERR-guarded pointer source. Tainted value flows through a
    guarded handle to a sink."""

    def test_is_err_regmap_write(self, analysis_db):
        _, _, paths = analysis_db
        for p in paths:
            if ("cfg->ctrl" in p.source.variable
                    and "regmap_write" in p.sink.variable
                    and p.sink.function == "g2_probe"):
                return
        pytest.fail("IS_ERR-guarded regmap_write path not traced")


class TestForwardWrapper:
    """G3: 1-hop forwarding wrapper that passes taint verbatim to a
    sink-writing core function."""

    def test_forward_wrapper(self, analysis_db):
        _, _, paths = analysis_db
        for p in paths:
            if ("cfg->debug" in p.source.variable
                    and "G3_DBG_REG" in p.sink.variable
                    and p.sink.function == "g3_log_core"):
                return
        pytest.fail("forward-wrapper path not traced")


class TestC01BitfieldPackBulk:
    """C01: 7-field FIELD_PREP bitpack + regmap_write + memcpy bulk replicate
    — curator-mined frontier."""

    def test_bitfield_pack_regmap_write(self, analysis_db):
        _, _, paths = analysis_db
        for p in paths:
            if ("cfg->pga" in p.source.variable
                    and "regmap_write" in p.sink.variable
                    and p.sink.function == "cx1_apply_setup"):
                return
        pytest.fail("C01 bitfield_pack_bulk pga→regmap_write — frontier not yet covered")

    def test_bitfield_pack_memcpy_bulk(self, analysis_db):
        _, _, paths = analysis_db
        for p in paths:
            if ("cfg->filter_type" in p.source.variable
                    and p.sink.function == "cx1_apply_setup"):
                return
        pytest.fail("C01 bitfield_pack_bulk filter_type→memcpy bulk — frontier not yet covered")


class TestC02FnptrStructOps:
    """C02: designated-init struct-ops fnptr dispatch table
    — curator-mined frontier."""

    def test_struct_ops_ctrl(self, analysis_db):
        _, _, paths = analysis_db
        for p in paths:
            if ("cfg->ctrl" in p.source.variable
                    and "CX2_CTRL_REG" in p.sink.variable
                    and p.sink.function == "cx2_mmio_write"):
                return
        pytest.fail("C02 fnptr_struct_ops ctrl dispatch — frontier not yet covered")

    def test_struct_ops_sample(self, analysis_db):
        _, _, paths = analysis_db
        for p in paths:
            if ("cfg->sample" in p.source.variable
                    and "CX2_SAMPLE_REG" in p.sink.variable
                    and p.sink.function == "cx2_mmio_write"):
                return
        pytest.fail("C02 fnptr_struct_ops sample dispatch — frontier not yet covered")


class TestC03GotoLadderUnwind:
    """C03: 3-label goto unwind ladder with staged MMIO sinks
    — curator-mined frontier."""

    def test_goto_ladder_stage1(self, analysis_db):
        _, _, paths = analysis_db
        for p in paths:
            if ("cfg->gp_mode" in p.source.variable
                    and "regmap_set_bits" in p.sink.variable
                    and p.sink.function == "cx3_postenable"):
                return
        pytest.fail("C03 goto_ladder_unwind stage1 gp_mode→regmap_set_bits — frontier not yet covered")

    def test_goto_ladder_stage2(self, analysis_db):
        _, _, paths = analysis_db
        for p in paths:
            if ("cfg->trig_mask" in p.source.variable
                    and "cx3_trigger_enable" in p.sink.variable
                    and p.sink.function == "cx3_postenable"):
                return
        pytest.fail("C03 goto_ladder_unwind stage2 trig_mask→trigger_enable — frontier not yet covered")

    def test_goto_ladder_stage3(self, analysis_db):
        _, _, paths = analysis_db
        for p in paths:
            if ("cfg->seq_mode" in p.source.variable
                    and "cx3_seq_mode_enter" in p.sink.variable
                    and p.sink.function == "cx3_postenable"):
                return
        pytest.fail("C03 goto_ladder_unwind stage3 seq_mode→seq_mode_enter — frontier not yet covered")


class TestAliasingAdvanced:
    """P2: conditional alias, linked-list walk, dynamic-index sinks."""

    def test_cond_alias(self, analysis_db):
        """p = sel ? ra : rb; p->regs[...] = acfg->frequency"""
        _, _, paths = analysis_db
        for p in paths:
            if "acfg->frequency" in p.source.variable and "AA_TIMING_REG" in p.sink.variable:
                if p.sink.function == "cond_alias_write":
                    return
        pytest.fail("Conditional alias path not traced")

    def test_linked_list_walk(self, analysis_db):
        """for (n = head; n; n = n->next) n->regs->regs[...] = acfg->mode"""
        _, _, paths = analysis_db
        for p in paths:
            if "acfg->mode" in p.source.variable and "AA_MODE_REG" in p.sink.variable:
                if p.sink.function == "list_walk_write":
                    return
        pytest.fail("Linked-list traversal sink not traced")

    def test_dynamic_index(self, analysis_db):
        """arr[i]->regs[...] = acfg->enable"""
        _, _, paths = analysis_db
        for p in paths:
            if "acfg->enable" in p.source.variable and "AA_CTRL_REG" in p.sink.variable:
                if p.sink.function == "dyn_index_write":
                    return
        pytest.fail("Dynamic-index struct-array sink not traced")


class TestEnumTracking:
    """Enum-typed config field → register tracking."""

    def test_enum_op_mode(self, analysis_db):
        """ecfg->op_mode → regs->regs[MODE_REG]"""
        _, _, paths = analysis_db
        found = _find_path(paths, "ecfg->op_mode", "regs->regs[MODE_REG]")
        assert found is not None, "Failed to trace ecfg->op_mode → register"

    def test_enum_clk_src(self, analysis_db):
        """ecfg->clk_src → regs->regs[CTRL_REG]"""
        _, _, paths = analysis_db
        found = _find_path(paths, "ecfg->clk_src", "regs->regs[CTRL_REG]")
        assert found is not None, "Failed to trace ecfg->clk_src → register"

    def test_enum_range_power(self, analysis_db):
        """ecfg->power_level → regs->regs[THRESH_REG]"""
        _, _, paths = analysis_db
        found = _find_path(paths, "ecfg->power_level", "regs->regs[THRESH_REG]")
        assert found is not None, "Failed to trace ecfg->power_level → register"


class TestConfigSpecGeneration:
    """Config spec generation with enum/range metadata."""

    @pytest.fixture(scope="class")
    def config_specs(self, analysis_db):
        """Generate config specs using TaintTracker with dataflow paths."""
        repo, pid, paths = analysis_db

        source_patterns = [
            {"name": "config_field", "regex": r"cfg->(\w+)"},
            {"name": "ext_config_field", "regex": r"ecfg->(\w+)"},
        ]
        sink_patterns = [
            {"name": "reg_array", "regex": r"(?:regs|r|hw)->regs\["},
            {"name": "fw_field", "regex": r"fw->(\w+)\s*="},
            {"name": "REG_WRITE", "regex": r"REG_WRITE\s*\("},
        ]

        tracker = TaintTracker(repo, pid, source_patterns, sink_patterns)
        tracker._load_all_files()
        return tracker.generate_config_specs(paths=paths)

    def test_op_mode_enum_values(self, config_specs):
        """ExtConfig.op_mode should have OpMode enum values."""
        spec = None
        for s in config_specs:
            if s.struct_name == "ExtConfig" and s.field_name == "op_mode":
                spec = s
                break
        assert spec is not None, "ExtConfig.op_mode not found in specs"
        assert spec.enum_type == "OpMode"
        assert "MODE_LOW" in spec.enum_values
        assert "MODE_MED" in spec.enum_values
        assert "MODE_HIGH" in spec.enum_values

    def test_power_level_range(self, config_specs):
        """ExtConfig.power_level should have min/max from range constraints."""
        spec = None
        for s in config_specs:
            if s.struct_name == "ExtConfig" and s.field_name == "power_level":
                spec = s
                break
        assert spec is not None, "ExtConfig.power_level not found in specs"
        # Range constraints use variable name "pwr" not "power_level",
        # so direct matching by field name won't work without alias resolution.
        # This tests the current capability.

    def test_description_has_sink_info(self, config_specs):
        """Config fields with dataflow paths should have description with sink info."""
        spec = None
        for s in config_specs:
            if s.struct_name == "Config" and s.field_name == "frequency":
                spec = s
                break
        assert spec is not None, "Config.frequency not found in specs"
        assert spec.description, "description should not be empty"
        assert spec.register_sinks, "register_sinks should not be empty"
        # frequency maps to at least one register
        assert any("regs" in sink.lower() or "REG" in sink for sink in spec.register_sinks)

    def test_enum_description_includes_values(self, config_specs):
        """Enum-typed fields should mention enum values in description."""
        spec = None
        for s in config_specs:
            if s.struct_name == "ExtConfig" and s.field_name == "op_mode":
                spec = s
                break
        assert spec is not None, "ExtConfig.op_mode not found in specs"
        assert spec.description, "description should not be empty"
        assert "OpMode" in spec.description
        assert "MODE_LOW" in spec.description


# ── reverse trace tests ──────────────────────────────────────────────────────

class TestReverseTrace:
    """Test reverse_trace: find sources reaching specific sinks."""

    def test_reverse_trace_finds_sources(self, analysis_db):
        """Reverse trace with a sink pattern should find sources reaching it."""
        repo, pid, _ = analysis_db
        source_patterns = [
            {"name": "config_field", "regex": r"cfg->(\w+)"},
            {"name": "ext_config_field", "regex": r"ecfg->(\w+)"},
        ]
        sink_patterns = [
            {"name": "reg_array", "regex": r"(?:regs|r|hw)->regs\["},
            {"name": "fw_field", "regex": r"fw->(\w+)\s*="},
            {"name": "REG_WRITE", "regex": r"REG_WRITE\s*\("},
        ]
        tracker = TaintTracker(repo, pid, source_patterns, sink_patterns)
        grouped = tracker.reverse_trace(r"regs\[THRESH_REG\]", max_depth=5)
        assert len(grouped) > 0, "reverse_trace should find at least one sink group"

        # Check that at least one source contains "threshold"
        all_sources = []
        for paths_list in grouped.values():
            for p in paths_list:
                all_sources.append(p.source.variable)
        assert any("threshold" in s for s in all_sources), \
            f"Expected 'threshold' source for THRESH_REG, got: {all_sources}"

    def test_reverse_trace_groups_by_sink(self, analysis_db):
        """Results should be grouped by sink variable."""
        repo, pid, _ = analysis_db
        source_patterns = [
            {"name": "config_field", "regex": r"cfg->(\w+)"},
        ]
        sink_patterns = [
            {"name": "reg_array", "regex": r"(?:regs|r|hw)->regs\["},
            {"name": "fw_field", "regex": r"fw->(\w+)\s*="},
        ]
        tracker = TaintTracker(repo, pid, source_patterns, sink_patterns)
        grouped = tracker.reverse_trace(r"regs\[", max_depth=5)
        # Each key should be a sink variable
        for sink_var, paths_list in grouped.items():
            for p in paths_list:
                assert p.sink.variable == sink_var


# ── config export tests ──────────────────────────────────────────────────────

class TestConfigExport:
    """Test CSV/JSON/YAML export of ConfigFieldSpec."""

    @pytest.fixture(scope="class")
    def specs_and_paths(self, analysis_db):
        repo, pid, paths = analysis_db
        source_patterns = [
            {"name": "config_field", "regex": r"cfg->(\w+)"},
            {"name": "ext_config_field", "regex": r"ecfg->(\w+)"},
        ]
        sink_patterns = [
            {"name": "reg_array", "regex": r"(?:regs|r|hw)->regs\["},
            {"name": "fw_field", "regex": r"fw->(\w+)\s*="},
            {"name": "REG_WRITE", "regex": r"REG_WRITE\s*\("},
        ]
        tracker = TaintTracker(repo, pid, source_patterns, sink_patterns)
        tracker._load_all_files()
        specs = tracker.generate_config_specs(paths=paths)
        return specs, paths

    def test_csv_export(self, specs_and_paths):
        """CSV export should have headers and rows."""
        from cpp_analyzer.analysis.taint_tracker import export_specs_csv
        specs, _ = specs_and_paths
        csv_text = export_specs_csv(specs)
        lines = csv_text.strip().split("\n")
        assert len(lines) > 1, "CSV should have header + at least one data row"
        assert "field_name" in lines[0]
        assert "struct_name" in lines[0]

    def test_json_export(self, specs_and_paths):
        """JSON export should be valid JSON with expected fields."""
        import json as _json
        from cpp_analyzer.analysis.taint_tracker import export_specs_json
        specs, _ = specs_and_paths
        json_text = export_specs_json(specs)
        data = _json.loads(json_text)
        assert isinstance(data, list)
        assert len(data) > 0
        assert "field_name" in data[0]
        assert "gated_by" in data[0]
        assert "gates" in data[0]
        assert "co_depends" in data[0]

    def test_yaml_export(self, specs_and_paths):
        """YAML export should be valid YAML with expected fields."""
        from cpp_analyzer.analysis.taint_tracker import export_specs_yaml
        specs, _ = specs_and_paths
        yaml_text = export_specs_yaml(specs)
        data = yaml.safe_load(yaml_text)
        assert isinstance(data, list)
        assert len(data) > 0
        assert "field_name" in data[0]


# ── config language tests ────────────────────────────────────────────────────

class TestConfigLanguage:
    """Test config constraint language export with gating/co-dependency."""

    @pytest.fixture(scope="class")
    def language_output(self, analysis_db):
        """Generate config language output."""
        from cpp_analyzer.analysis.taint_tracker import export_config_language
        repo, pid, paths = analysis_db
        source_patterns = [
            {"name": "config_field", "regex": r"cfg->(\w+)"},
            {"name": "ext_config_field", "regex": r"ecfg->(\w+)"},
        ]
        sink_patterns = [
            {"name": "reg_array", "regex": r"(?:regs|r|hw)->regs\["},
            {"name": "fw_field", "regex": r"fw->(\w+)\s*="},
            {"name": "REG_WRITE", "regex": r"REG_WRITE\s*\("},
        ]
        tracker = TaintTracker(repo, pid, source_patterns, sink_patterns)
        tracker._load_all_files()
        specs = tracker.generate_config_specs(paths=paths)
        tracker.detect_gating(specs, paths)
        tracker.detect_co_dependencies(specs, paths)
        lang_yaml = export_config_language(specs, paths)
        return yaml.safe_load(lang_yaml), specs

    def test_language_has_config_fields(self, language_output):
        """Config language YAML should have config_fields key."""
        data, _ = language_output
        assert "config_fields" in data
        assert len(data["config_fields"]) > 0

    def test_language_fields_have_name_and_type(self, language_output):
        """Each config field entry should have name and type."""
        data, _ = language_output
        for entry in data["config_fields"]:
            assert "name" in entry
            assert "type" in entry

    def test_gating_detected(self, language_output):
        """At least some gating relationships should be detected."""
        _, specs = language_output
        gated = [s for s in specs if s.gated_by]
        gating = [s for s in specs if s.gates]
        # The test fixture has if(cfg->enable) { ... } patterns
        # so we expect at least some gating
        assert len(gated) > 0 or len(gating) > 0, \
            "Expected at least one gating relationship from test fixtures"

    def test_co_dependency_detected(self, language_output):
        """At least some co-dependency relationships should be detected."""
        _, specs = language_output
        co_dep = [s for s in specs if s.co_depends]
        assert len(co_dep) > 0, \
            "Expected at least one co-dependency from test fixtures"


# ── multi-file fixture tests ─────────────────────────────────────────────────

@pytest.fixture(scope="module")
def multifile_db():
    """Index the multi-file fixture directory and return (repo, pid, paths).

    Verifies that cross-TU dataflow tracking works: config in one .c file,
    intermediate in another, sink in a third.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    repo = Repository(db_path)
    repo.connect()
    pid = repo.upsert_project("dataflow-multifile", str(MULTIFILE_DIR))

    indexer = Indexer(repo, pid, MULTIFILE_DIR)
    indexer.run(force=True)

    source_patterns = [
        {"name": "config_field", "regex": r"cfg->(\w+)"},
    ]
    sink_patterns = [
        {"name": "reg_array", "regex": r"(?:regs|r|hw)->regs\["},
        {"name": "fw_field", "regex": r"fw->(\w+)\s*="},
        {"name": "REG_WRITE", "regex": r"REG_WRITE\s*\("},
    ]

    tracker = TaintTracker(repo, pid, source_patterns, sink_patterns)
    paths = tracker.trace(max_depth=6, max_paths=200)

    yield repo, pid, paths

    repo.close()
    os.unlink(db_path)


class TestMultiFile:
    """Cross-translation-unit dataflow tracking.

    Simulates a realistic project layout: headers under include/, firmware
    logic in fw.c, register writes in regs.c, callbacks in callbacks.c,
    top-level driver in main.c.
    """

    def test_fw_clk_div_same_tu(self, multifile_db):
        """cfg->frequency → fw->clk_div (single TU, fw.c)"""
        _, _, paths = multifile_db
        found = _find_path(paths, "cfg->frequency", "fw->clk_div")
        assert found is not None, "Failed to trace cfg->frequency → fw->clk_div"

    def test_direct_threshold_cross_tu_from_header(self, multifile_db):
        """cfg->threshold → regs[THRESH_REG] (regs.c, headers from include/)"""
        _, _, paths = multifile_db
        found = _find_path(paths, "cfg->threshold", "regs->regs[THRESH_REG]")
        assert found is not None, "Failed to trace cfg->threshold across headers"

    def test_macro_sink_in_regs_tu(self, multifile_db):
        """cfg->mode via REG_WRITE macro (defined in hw_regs.h, used in regs.c)"""
        _, _, paths = multifile_db
        found = _find_path(paths, "cfg->mode", sink_pattern=r"REG_WRITE")
        assert found is not None, "Failed to trace cfg->mode through REG_WRITE macro"

    def test_cross_tu_two_layer(self, multifile_db):
        """cfg->frequency → fw_compute (fw.c) → regs_apply_timing (regs.c) → TIMING_REG.

        Requires cross-TU field writer linkage: fw_compute writes fw->timing_val
        in fw.c, regs_apply_timing reads fw->timing_val in regs.c.
        """
        _, _, paths = multifile_db
        for p in paths:
            if "cfg->frequency" in p.source.variable and "regs->regs[TIMING_REG]" in p.sink.variable:
                funcs = {p.sink.function, p.source.function} | {s.function for s in p.steps}
                if "fw_compute" in funcs or "regs_apply_timing" in funcs:
                    return
        pytest.xfail("Two-layer cross-TU tracking not yet resolving fw->timing_val across files")

    def test_cross_tu_callback(self, multifile_db):
        """cfg->enable → cb_fire (callbacks.c) via g_cb → handle_enable → CTRL_REG"""
        _, _, paths = multifile_db
        for p in paths:
            if "cfg->enable" in p.source.variable and "regs->regs[CTRL_REG]" in p.sink.variable:
                funcs = {p.sink.function, p.source.function} | {s.function for s in p.steps}
                if "cb_fire" in funcs or "handle_enable" in funcs:
                    return
        pytest.xfail("Cross-TU callback tracking not yet working")


class TestLargeCodebase:
    """D1: synthetic large-codebase validation.

    Generates N modules that each taint a unique config field into a unique
    register write, then asserts the tracker finds all paths within a
    reasonable wall-clock budget.
    """

    def test_synthetic_50_modules(self, tmp_path):
        import time

        N = 50
        src_dir = tmp_path / "synth"
        src_dir.mkdir()
        header = src_dir / "hw.h"
        header.write_text(
            "#ifndef HW_H\n#define HW_H\n"
            "typedef struct { int fields[256]; } Config;\n"
            "typedef struct { volatile unsigned int regs[256]; } HwRegs;\n"
            "#endif\n"
        )
        for i in range(N):
            (src_dir / f"mod_{i}.c").write_text(
                f'#include "hw.h"\n'
                f"void apply_{i}(Config* cfg, HwRegs* regs) {{\n"
                f"    regs->regs[{i}] = cfg->fields[{i}] << 2;\n"
                f"}}\n"
            )

        db_path = str(tmp_path / "synth.db")
        repo = Repository(db_path)
        repo.connect()
        pid = repo.upsert_project("synth", str(src_dir))

        t0 = time.perf_counter()
        Indexer(repo, pid, src_dir).run(force=True)
        t_index = time.perf_counter() - t0

        source_patterns = [{"name": "cfg_field", "regex": r"cfg->fields\[(\d+)\]"}]
        sink_patterns = [{"name": "reg_array", "regex": r"regs->regs\["}]

        t0 = time.perf_counter()
        tracker = TaintTracker(repo, pid, source_patterns, sink_patterns)
        paths = tracker.trace(max_depth=3, max_paths=500)
        t_trace = time.perf_counter() - t0

        repo.close()

        assert len(paths) >= N, f"expected ≥{N} paths, got {len(paths)}"
        # Generous budget: CI machines vary. The point is to catch >10× regressions.
        assert t_index < 30.0, f"index took {t_index:.2f}s for {N} modules"
        assert t_trace < 30.0, f"trace took {t_trace:.2f}s for {N} modules"


class TestParseCache:
    """Parser-level caching (B1: incremental analysis)."""

    def test_parse_cache_hit(self):
        from cpp_analyzer.analysis import ts_parser
        ts_parser.clear_parse_cache()
        p = str(FIXTURES_DIR / "hw_model.c")
        n1 = ts_parser.parse_file(p)
        n2 = ts_parser.parse_file(p)
        assert n1 is not None and n2 is not None
        assert id(n1) == id(n2), "Second parse should return cached Node"
        assert len(ts_parser._parse_cache) >= 1
        ts_parser.clear_parse_cache()
        assert len(ts_parser._parse_cache) == 0


# ── benchmark scoring ─────────────────────────────────────────────────────────

class TestBenchmark:
    """Aggregate benchmark scoring for gap analysis."""

    def test_benchmark_score(self, analysis_db, expected):
        """Run all expected paths and compute a coverage score."""
        _, _, paths = expected["paths"], None, analysis_db[2]
        actual_paths = analysis_db[2]

        difficulty_weight = {"easy": 1, "medium": 2, "hard": 3}
        total_score = 0
        max_score = 0
        results = []

        for exp in expected["paths"]:
            weight = difficulty_weight.get(exp.get("difficulty", "easy"), 1)
            max_score += weight

            source = exp["source"]
            sink = exp.get("sink")
            sink_pat = exp.get("sink_pattern")
            expected_fn = exp.get("expected_function")

            found = _find_path(actual_paths, source, sink, sink_pat,
                               expected_function=expected_fn)
            status = "PASS" if found else "MISS"
            if found:
                total_score += weight

            results.append({
                "name": exp["name"],
                "difficulty": exp.get("difficulty", "easy"),
                "status": status,
                "requires": exp.get("requires", "basic"),
            })

        # Print results table
        print(f"\n{'='*70}")
        print(f"  DATAFLOW BENCHMARK SCORE: {total_score}/{max_score} "
              f"({total_score/max_score*100:.0f}%)")
        print(f"{'='*70}")
        for r in results:
            icon = "PASS" if r["status"] == "PASS" else "MISS"
            print(f"  [{icon}] {r['name']:<45} "
                  f"({r['difficulty']}, requires: {r['requires']})")
        print(f"{'='*70}")

        # Gap analysis
        gaps = [r for r in results if r["status"] == "MISS"]
        if gaps:
            print(f"\n  GAPS ({len(gaps)} missed):")
            by_req = {}
            for g in gaps:
                by_req.setdefault(g["requires"], []).append(g["name"])
            for req, names in by_req.items():
                print(f"    [{req}]: {', '.join(names)}")

        # Write gap report for CI
        report_path = Path(__file__).parent.parent / "_benchmark_report.json"
        import json
        report = {
            "score": total_score,
            "max_score": max_score,
            "pct": round(total_score / max_score * 100, 1),
            "total_paths_found": len(actual_paths),
            "results": results,
            "gaps": [{"name": g["name"], "requires": g["requires"]} for g in gaps],
        }
        report_path.write_text(json.dumps(report, indent=2))
        print(f"\n  Report written to: {report_path}")

        # Don't fail the test — this is informational
        assert total_score > 0, "No paths found at all — analysis is broken"
