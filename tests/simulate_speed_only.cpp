// Native logic check; sensor timing and USB hardware are not simulated.
#include <iostream>
#include <iomanip>
#include <vector>
#include "Arduino.h"
#include "Wire.h"
unsigned long fakeUs = 0;
FakeWire Wire;
struct NumericSerial {
    int baud = 0;
    std::vector<float> values;
    void begin(int value) { baud = value; }
    // Deliberately supports only numeric output: text diagnostics fail compilation.
    void println(float value, int digits) {
        if (digits != 3) std::abort();
        values.push_back(value);
    }
} speedSerial;
#define Serial speedSerial
#include "../firmware_Arduino/COMP0219_SpeedOnly_Lab03/COMP0219_SpeedOnly_Lab03.ino"
#undef Serial

int main() {
    setup();
    if (speedSerial.baud != 115200 || !speedSerial.values.empty()) return 1;
    if (predictWindSpeed(ZERO_ADC, 20.0f) != 0.0f) return 2;
    if (predictWindSpeed(ZERO_ADC - WIND_SIGN * 1000.0f, 20.0f) != 0.0f) return 3;
    if (predictWindSpeed(ZERO_ADC + WIND_SIGN * 2.5f * ZERO_SIGMA_ADC, 20.0f) != 0.0f) return 4;
    float check = predictWindSpeed(8810423.9036f, 20.46024f);
    // Read constants from the compiled sketch, so changing calibration does not
    // leave the Python comparison pinned to a previous run's beta/baseline.
    std::cout << std::setprecision(9) << ZERO_ADC << ',' << ZERO_SIGMA_ADC << ','
              << WIND_SIGN << ',' << BETA << '\n';
    std::cout << std::setprecision(9) << check << '\n';
    for (int i = 0; i < 10000; ++i) {
        fakeUs += 100;
        loop();
    }
    if (speedSerial.values.size() != 200) return 5;
    for (float value : speedSerial.values)
        if (!std::isfinite(value) || value < 0) return 6;
    // Missing temperature in the mock must safely emit numeric zero.
    for (float value : speedSerial.values)
        if (value != 0.0f) return 7;
    filteredADC = 8810423.9036f;
    temperatureC = 20.46024f;
    adcValid = temperatureValid = true;
    fakeUs += 5000;
    loop();
    if (speedSerial.values.size() != 201 || std::fabs(speedSerial.values.back() - check) > 0.0001f)
        return 8;
    std::cout << "PASS: 200 numeric lines in simulated second; no startup text.\n";
}
