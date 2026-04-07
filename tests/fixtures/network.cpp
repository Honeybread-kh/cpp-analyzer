/**
 * Test fixture — network module implementation.
 * Includes: network.h
 */
#include "network.h"
#include <iostream>

Network::Network(const std::string& addr) : addr_(addr) {}

void Network::connect() {
    log_message("connecting to " + addr_);
}

void Network::send(const std::string& data) {
    log_message("sending " + std::to_string(data.size()) + " bytes");
}
