/**
 * Test fixture — application implementation.
 * Includes: app.h, network.h
 */
#include "app.h"
#include "network.h"

void App::run() {
    Network net(cfg_.server_addr);
    net.connect();
    log_message("app running");
}
