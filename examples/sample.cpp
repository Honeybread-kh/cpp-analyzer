/**
 * sample.cpp — example C++ file that uses several configuration patterns.
 * Use this to test the analyzer:
 *
 *   cd cpp_analyzer
 *   cpp-analyzer index ./examples --db test.db
 *   cpp-analyzer stats --db test.db
 *   cpp-analyzer query config --list --db test.db
 *   cpp-analyzer trace config "max_threads" --db test.db
 */

#include <iostream>
#include <string>
#include <map>
#include <vector>
#include <cstdlib>   // getenv

// ── Preprocessor feature flags ────────────────────────────────────────────
#define ENABLE_COMPRESSION 1
#define ENABLE_METRICS     1

// ── Config struct loaded from a config file ───────────────────────────────
struct AppConfig {
    int         max_threads  = 4;
    bool        debug_mode   = false;
    std::string log_level    = "info";
    std::string output_dir   = "/tmp";
    bool        enable_cache = true;
};

// ── Simulated config map (e.g. parsed from YAML/JSON) ─────────────────────
std::map<std::string, std::string> config;

// Forward declarations
class Worker;
void processRequest(const std::string& data, const AppConfig& cfg);
void compress(const std::string& data);
void logEvent(const std::string& msg, const std::string& level);

// ── Config loader ─────────────────────────────────────────────────────────
AppConfig loadConfig(int argc, char** argv) {
    AppConfig cfg;

    // ENV VAR pattern
    const char* debug_env = getenv("DEBUG_MODE");
    if (debug_env && std::string(debug_env) == "true") {
        cfg.debug_mode = true;
    }

    const char* threads_env = getenv("MAX_THREADS");
    if (threads_env) {
        cfg.max_threads = std::stoi(threads_env);
    }

    // Map-based config pattern
    cfg.log_level  = config["log_level"];
    cfg.output_dir = config.get("output_dir") != nullptr
                     ? *config.get("output_dir")
                     : "/tmp";

    return cfg;
}

// ── Logger ────────────────────────────────────────────────────────────────
void logEvent(const std::string& msg, const std::string& level) {
    if (level == "debug" || level == "trace") {
        std::cout << "[DEBUG] " << msg << std::endl;
    } else {
        std::cout << "[" << level << "] " << msg << std::endl;
    }
}

// ── Compression module ────────────────────────────────────────────────────
void compress(const std::string& data) {
#ifdef ENABLE_COMPRESSION
    logEvent("Compressing " + std::to_string(data.size()) + " bytes", "debug");
    // ... compression logic ...
#endif
}

// ── Metrics ───────────────────────────────────────────────────────────────
class MetricsCollector {
public:
    void record(const std::string& key, double value) {
#ifdef ENABLE_METRICS
        metrics_[key] = value;
#endif
    }

    void flush() {
        const char* endpoint = getenv("METRICS_ENDPOINT");
        if (!endpoint) return;
        for (auto& [k, v] : metrics_) {
            logEvent("metric " + k + "=" + std::to_string(v), "info");
        }
    }

private:
    std::map<std::string, double> metrics_;
};

// ── Worker ────────────────────────────────────────────────────────────────
class Worker {
public:
    explicit Worker(const AppConfig& cfg) : cfg_(cfg) {}

    void run(const std::string& data) {
        if (cfg_.debug_mode) {
            logEvent("Worker::run called with " + std::to_string(data.size()) + " bytes", "debug");
        }
        processRequest(data, cfg_);
    }

    void runBatch(const std::vector<std::string>& items) {
        for (const auto& item : items) {
            run(item);
        }
    }

private:
    const AppConfig& cfg_;
};

// ── Core request processor ────────────────────────────────────────────────
void processRequest(const std::string& data, const AppConfig& cfg) {
    logEvent("Processing request", cfg.log_level);

    if (cfg.enable_cache) {
        // cache lookup
        logEvent("Cache enabled, checking cache", "debug");
    }

    compress(data);

    MetricsCollector mc;
    mc.record("request.size", data.size());
    mc.flush();
}

// ── Thread pool ───────────────────────────────────────────────────────────
class ThreadPool {
public:
    explicit ThreadPool(int thread_count) : count_(thread_count) {
        logEvent("ThreadPool created with " + std::to_string(thread_count) + " threads", "info");
    }

    void dispatch(const std::string& task) {
        logEvent("Dispatching task", "debug");
        // dispatch logic
    }

private:
    int count_;
};

// ── Main ──────────────────────────────────────────────────────────────────
int main(int argc, char** argv) {
    AppConfig cfg = loadConfig(argc, argv);

    // config-driven branching
    if (cfg.debug_mode) {
        logEvent("Debug mode is ON", "info");
    }

    // config drives concurrency
    ThreadPool pool(cfg.max_threads);

    Worker worker(cfg);
    worker.run("hello world");

    std::vector<std::string> batch = {"a", "b", "c"};
    worker.runBatch(batch);

    return 0;
}
