#include <Arduino.h>
#include <Wire.h>
#include <stdint.h>
#include <math.h>
#include <string.h>

// Standalone Nucleo-F411RE sketch: one speed in m/s per line, 115200 baud.
// Starts automatically; no commands, prompts, headers, units or diagnostics.
// Wiring matches Stage1: PB9 SDA, PB8 SCL; Weight-I2C 0x26; MCP9808 0x18.
// Calibration source: outputs/lab_run03/calibration_restore.txt, 2026-11-04.
// k 8840017 28.57 -1 0.0297896702
// TEST CALIBRATION: held-out reference 2.926 m/s -> predicted 4.674 m/s.
// Keep the same plate/mounting/direction. Accuracy needs investigation.
// 200 Hz is the output cadence, not 200 independent load measurements/second.

// FOR Wooden
// const float ZERO_ADC = 8840017.0f;
// const float ZERO_SIGMA_ADC = 28.57f;
// const int WIND_SIGN = -1;
// const float BETA = 0.0297896702f;


// FOR Real!
const float ZERO_ADC = 8837482.0f;
const float ZERO_SIGMA_ADC = 29.83f;
const int WIND_SIGN = -1;
const float BETA = 0.03077113727f;

const uint8_t WEIGHT_ADDR = 0x26;
const uint8_t TEMP_ADDR = 0x18;
const float EMA_ALPHA = 0.25f;
const uint32_t OUTPUT_PERIOD_US = 5000UL;
const uint32_t ADC_PERIOD_US = 12500UL;
const uint32_t TEMP_PERIOD_US = 500000UL;

float filteredADC = 0.0f;
float temperatureC = 20.0f;
bool adcValid = false;
bool temperatureValid = false;
uint32_t nextOutputUs = 0;
uint32_t nextADCUs = 0;
uint32_t nextTempUs = 0;

bool readADCOnce(int32_t &out) {
  Wire.beginTransmission(WEIGHT_ADDR);
  Wire.write((uint8_t)0x00);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(WEIGHT_ADDR, (uint8_t)4) != 4) {
    while (Wire.available()) Wire.read();
    return false;
  }
  uint32_t b0 = (uint8_t)Wire.read();
  uint32_t b1 = (uint8_t)Wire.read();
  uint32_t b2 = (uint8_t)Wire.read();
  uint32_t b3 = (uint8_t)Wire.read();
  uint32_t packed = b0 | (b1 << 8) | (b2 << 16) | (b3 << 24);
  memcpy(&out, &packed, sizeof(out));
  return true;
}

bool readTemperature(float &out) {
  Wire.beginTransmission(TEMP_ADDR);
  Wire.write((uint8_t)0x05);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(TEMP_ADDR, (uint8_t)2) != 2) return false;
  uint16_t raw = ((uint16_t)Wire.read() << 8) | Wire.read();
  float value = (float)(raw & 0x0FFF) / 16.0f;
  if (raw & 0x1000) value -= 256.0f;
  if (!isfinite(value) || value < -40.0f || value > 125.0f) return false;
  out = value;
  return true;
}

float predictWindSpeed(float adc, float tempC) {
  float signedDelta = WIND_SIGN * (adc - ZERO_ADC);
  if (signedDelta <= 3.0f * ZERO_SIGMA_ADC) return 0.0f;
  float rho = 101325.0f / (287.05f * (tempC + 273.15f));
  float speed = BETA * sqrtf(signedDelta / rho);
  return isfinite(speed) && speed >= 0.0f ? speed : 0.0f;
}

void setup() {
  Serial.begin(115200);
  delay(1200);
  Wire.setSDA(PB9);
  Wire.setSCL(PB8);
  Wire.begin();
  Wire.setClock(100000);

  // Prime the latest readings before scheduling the first numeric output.
  int32_t raw;
  if (readADCOnce(raw)) {
    filteredADC = (float)raw;
    adcValid = true;
  }
  temperatureValid = readTemperature(temperatureC);
  uint32_t now = micros();
  nextOutputUs = now + OUTPUT_PERIOD_US;
  nextADCUs = now + ADC_PERIOD_US;
  nextTempUs = now + TEMP_PERIOD_US;
}

void loop() {
  uint32_t now = micros();
  if ((int32_t)(now - nextOutputUs) >= 0) {
    // Skip missed slots rather than send a burst of late lines.
    uint32_t skipped = (now - nextOutputUs) / OUTPUT_PERIOD_US;
    nextOutputUs += (skipped + 1UL) * OUTPUT_PERIOD_US;
    float speed = 0.0f;
    if (adcValid && temperatureValid)
      speed = predictWindSpeed(filteredADC, temperatureC);
    Serial.println(speed, 3);
    return;
  }

  // Same scheduling/filtering as Stage1: output takes priority over I2C polls.
  if ((int32_t)(nextOutputUs - now) < 2200) return;
  if ((int32_t)(now - nextADCUs) >= 0) {
    int32_t raw;
    if (readADCOnce(raw)) {
      if (!adcValid) {
        filteredADC = (float)raw;
        adcValid = true;
      } else {
        filteredADC += EMA_ALPHA * ((float)raw - filteredADC);
      }
    }
    // As in Stage1, a failed read holds the last successful measurement.
    nextADCUs += ADC_PERIOD_US;
    if ((int32_t)(micros() - nextADCUs) >= 0)
      nextADCUs = micros() + ADC_PERIOD_US;
    return;
  }
  if ((int32_t)(now - nextTempUs) >= 0) {
    float candidate;
    if (readTemperature(candidate)) {
      temperatureC = candidate;
      temperatureValid = true;
    }
    nextTempUs = micros() + TEMP_PERIOD_US;
  }
}
