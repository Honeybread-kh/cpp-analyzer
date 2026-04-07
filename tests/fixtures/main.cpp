/**
 * Test fixture — entry point.
 * Includes: app.h, utils.h
 */
#include "app.h"
#include "utils.h"
#include <iostream>

int main() {
    App app;
    app.run();
    log_message("done");
    return 0;
}
