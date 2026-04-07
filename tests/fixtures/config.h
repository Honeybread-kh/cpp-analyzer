/**
 * Test fixture — configuration.
 * No project includes (only system).
 */
#pragma once
#include <string>

struct AppConfig {
    int port = 8080;
    std::string server_addr = "localhost";
    bool debug = false;
};
