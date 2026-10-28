// Native logic-only harness. NOT a real STM32 timing test.
#include <sstream>
#include <iostream>
#include <string>
#include <cstdlib>
#include "Arduino.h"
#include "Wire.h"
unsigned long fakeUs = 0;
FakeSerial Serial;
FakeWire Wire;
#include "../firmware/src/main.cpp"
int main() {
    // j is the only mode that requires no calibration.
    startStreaming200(true);
    for (int i = 0; i < 10000; ++i) {
        fakeUs += 100;
        updateStreamMode();
    }
    // 1000ms elapsed: should have exactly 200 lines at 200Hz.
    if (streamSequence != 200 || missedStreamSlots != 0) {
        std::cerr << "FAIL stream: " << streamSequence << ", missed " << missedStreamSlots << "\n";
        return 1;
    }
    // Simulate restoring calibration from file and starting numeric mode.
    stream200 = false;
    bool ok = restoreCalibration(String("k 8836559.00 27.17 -1 0.21848438"));
    if (!ok || !modelValid || windSign != -1 || beta < 0.218f) {
        std::cerr << "FAIL restore\n";
        return 2;
    }
    startStreaming200(false);
    for (int i=0; i<10000; ++i) {
        fakeUs += 100;
        updateStreamMode();
    }
    if (streamSequence != 200 || missedStreamSlots != 0) {
        std::cerr << "FAIL numeric stream\n";return 3;
    }
    std::cout << "PASS native logic: 200 slots/s, zero missed in simulated clock; restore accepted.\n";
    std::cout << "This does not prove hardware real-time performance.\n";
    return 0;
}
