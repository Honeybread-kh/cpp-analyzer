/**
 * Test fixture — utility implementation.
 * Includes: utils.h
 */
#include "utils.h"
#include <iostream>
#include <cstdlib>

void log_message(const std::string& msg) {
    std::cout << "[LOG] " << msg << std::endl;
}

int parse_int(const std::string& s) {
    return std::stoi(s);
}
