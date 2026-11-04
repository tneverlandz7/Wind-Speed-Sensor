// Native firmware math fixture. Does not exercise real hardware or I2C.
#include <iostream>
#include <iomanip>
#include "Arduino.h"
#include "Wire.h"
unsigned long fakeUs = 0;
FakeSerial Serial;
FakeWire Wire;
#include "../firmware/src/main.cpp"

int main() {
    std::cout << std::setprecision(9);
    for (int direction : {1, -1}) {
        windSign = direction;
        zeroSigmaADC = 1.0f;
        zeroValid = true;
        nCal = 3;
        const float deltas[] = {1.0f, 100.0f, 400.0f};
        const float speeds[] = {9.0f, 2.0f, 4.0f};
        for (int i = 0; i < nCal; ++i) {
            cal[i].deltaADC = direction * deltas[i];
            cal[i].rho = 1.0f;
            cal[i].referenceMps = speeds[i];
        }
        fitModel();
        if (!modelValid) return 1;
        for (float delta : {-1.0f, 3.0f, 100.0f, 400.0f}) {
            std::cout << direction << ',' << delta << ',' << beta << ','
                      << predict(direction * delta, 1.0f) << '\n';
        }
    }
}
