/**
 * Test fixture — application header.
 * Includes: config.h, utils.h
 */
#pragma once
#include "config.h"
#include "utils.h"

class App {
public:
    void run();
private:
    AppConfig cfg_;
};
