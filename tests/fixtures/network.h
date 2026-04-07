/**
 * Test fixture — network module header.
 * Includes: config.h, utils.h
 */
#pragma once
#include "config.h"
#include "utils.h"

class Network {
public:
    explicit Network(const std::string& addr);
    void connect();
    void send(const std::string& data);
private:
    std::string addr_;
};
