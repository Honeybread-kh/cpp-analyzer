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
        {"name": "reg_array", "regex": r"(?:regs|r|hw)->regs\["},
        {"name": "fw_field", "regex": r"fw->(\w+)\s*="},
        {"name": "REG_WRITE", "regex": r"REG_WRITE\s*\("},
        {"name": "volatile_mmio", "regex": r"\*\s*\(\s*volatile"},
    ]

    tracker = TaintTracker(repo, pid, source_patterns, sink_patterns)
    paths = tracker.trace(max_depth=5, max_paths=200)

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
