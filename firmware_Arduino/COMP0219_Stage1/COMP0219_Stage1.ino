#include <stdint.h>
#include <Arduino.h>
#include <Wire.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "calibration_config.h"

// UCL wind-tunnel test: STM32 Nucleo-F411RE + Weight-I2C HX711 bridge + MCP9808
// Vertical load cell -> printed mounter -> 100 x 100 mm acrylic plate.
// WIND DIRECTION must remain identical for all calibration and test runs.
// This sketch calibrates ADC directly against REFERENCE WIND SPEED,
// so it does NOT require a horizontal pulley/weight force calibration.
// Values are stored in RAM and are lost on reset/power-off.

const uint8_t WEIGHT_ADDR = 0x26;
const uint8_t WEIGHT_RAW_REG = 0x00;

const uint8_t TEMP_ADDR = 0x18;
const uint8_t TEMP_REGISTER = 0x05;
const float PLATE_AREA_M2 = 0.01f; // informational; direct model absorbs Cd, area & mounting
const float ASSUMED_PRESSURE_PA = 101325.0f;
const float DRY_AIR_R = 287.05f;
const float EMA_ALPHA = 0.25f;
const unsigned long CAPTURE_MS = 5000UL;
const unsigned long SETTLE_MS = 500UL;
const unsigned long PRINT_PERIOD_MS = 200UL;
const unsigned long DATA_TIMEOUT_MS = 1000UL;
const int MAX_CAL = 16;
const int MAX_VAL = 16;
const float NOISE_MULTIPLIER = 3.0f;

struct Sample {
  float referenceMps;
  float meanADC;
  float stdADC;
  float temperatureC;
  float rho;
  float deltaADC;
};

struct Capture {
  float meanADC;
  float stdADC;
  float tempC;
  int samples;
};

Sample cal[MAX_CAL];
Sample val[MAX_VAL];
int nCal = 0;
int nVal = 0;

bool zeroValid = false;
float zeroADC = 0.0f;
float zeroSigmaADC = 0.0f;
float zeroTempC = 0.0f;

bool modelValid = false;
int windSign = 1;
float beta = 0.0f; // speed [m/s] = beta * sqrt(signedDeltaADC / density)
float calibrationMSE = NAN;

bool emaValid = false;
float emaADC = 0.0f;
unsigned long lastPrint = 0;

// Output-only mode for the required 200 Hz evaluator.
// While streaming, serial output is ONE float per line (m/s), no diagnostics.
// HX711 hardware can internally update slower than 200 Hz: output cadence != independent sample cadence.
const uint32_t STREAM_PERIOD_US = 5000UL;
const uint32_t ADC_POLL_US = 12500UL; // up to 80 polls/s; bridge may deliver fewer distinct HX711 conversions
const uint32_t TEMP_POLL_US = 500000UL;
bool stream200 = false;
bool streamDebugSequence = false;
uint32_t nextStreamUs = 0;
uint32_t nextAdcPollUs = 0;
uint32_t nextTempPollUs = 0;
uint32_t streamSequence = 0;
uint32_t missedStreamSlots = 0;
float streamTempC = 20.0f;
bool streamTempOK = false;
uint32_t adcSuccessfulPolls = 0;
uint32_t adcReadErrors = 0;
uint32_t adcValueChanges = 0; // not a verified HX711 conversion rate
uint32_t lastADCValue = 0;
bool lastADCValueValid = false;
uint32_t maxStreamLateUs = 0;
uint32_t maxI2cReadUs = 0;
uint32_t tempReadErrors = 0;


bool present(uint8_t addr) {
  Wire.beginTransmission(addr);
  return Wire.endTransmission() == 0;
}

void scanBus() {
  Serial.println("I2C scan:");
  for (uint8_t a = 1; a < 127; ++a) {
    if (present(a)) {
      Serial.print("  0x");
      if (a < 16) Serial.print('0');
      Serial.println(a, HEX);
    }
  }
}

bool readTempC(float &out) {
  Wire.beginTransmission(TEMP_ADDR);
  Wire.write(TEMP_REGISTER);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(TEMP_ADDR, (uint8_t)2) != 2) return false;
  uint16_t raw = ((uint16_t)Wire.read() << 8) | Wire.read();
  float t = (float)(raw & 0x0FFF) / 16.0f;
  if (raw & 0x1000) t -= 256.0f;
  if (!isfinite(t) || t < -40.0f || t > 125.0f) return false;
  out = t;
  return true;
}

float airDensity(float tempC) {
  return ASSUMED_PRESSURE_PA / (DRY_AIR_R * (tempC + 273.15f));
}

// Matches the register access verified in the working combined sensor test.
// This is for the I2C WEIGHT MODULE at 0x26, not a bare HX711 chip.
bool readADC(int32_t &out, unsigned long timeoutMs = DATA_TIMEOUT_MS) {
  unsigned long start = millis();
  do {
    Wire.beginTransmission(WEIGHT_ADDR);
    Wire.write(WEIGHT_RAW_REG);
    if (Wire.endTransmission(false) == 0) {
      if (Wire.requestFrom(WEIGHT_ADDR, (uint8_t)4) == 4) {
        uint32_t b0 = (uint8_t)Wire.read();
        uint32_t b1 = (uint8_t)Wire.read();
        uint32_t b2 = (uint8_t)Wire.read();
        uint32_t b3 = (uint8_t)Wire.read();
        uint32_t packed = b0 | (b1 << 8) | (b2 << 16) | (b3 << 24);
        memcpy(&out, &packed, sizeof(out));
        return true;
      }
      while (Wire.available()) Wire.read();
    }
    delay(10);
  } while ((unsigned long)(millis() - start) < timeoutMs);
  return false;
}

// Collect periodic samples from the bridge over the capture window.
// The bridge can return the same internally filtered conversion on successive
// reads, so we pace I2C polls at 100 ms rather than treating each as fresh.
bool capture(Capture &out, unsigned long durationMs = CAPTURE_MS) {
  delay(SETTLE_MS);
  unsigned long start = millis();
  unsigned long lastTempMs = 0;
  double avg = 0.0, m2 = 0.0, tempSum = 0.0;
  int n = 0, nt = 0;

  while ((unsigned long)(millis() - start) < durationMs) {
    int32_t adc;
    if (readADC(adc, 120)) {
      ++n;
      double x = (double)adc;
      double d = x - avg;
      avg += d / n;
      m2 += d * (x - avg);
    }
    if (nt == 0 || (unsigned long)(millis() - lastTempMs) >= 500UL) {
      float t;
      if (readTempC(t)) {
        tempSum += t;
        ++nt;
      }
      lastTempMs = millis();
    }
    delay(100);
  }

  if (n < 10 || nt < 1) {
    Serial.print("ERROR: Capture failed (ADC samples=");
    Serial.print(n);
    Serial.print(", temperature samples=");
    Serial.print(nt);
    Serial.println("). Check I2C/power.");
    return false;
  }
  out.meanADC = (float)avg;
  out.stdADC = (n > 1) ? sqrtf((float)(m2 / (n - 1))) : 0.0f;
  out.tempC = (float)(tempSum / nt);
  out.samples = n;
  return true;
}

float feature(float deltaADC, float rho) {
  float signedADC = windSign * deltaADC;
  if (signedADC <= 0.0f || rho <= 0.0f) return 0.0f;
  return sqrtf(signedADC / rho);
}

float predict(float deltaADC, float rho) {
  if (!modelValid) return NAN;
  float signedADC = windSign * deltaADC;
  if (signedADC <= 3.0f * zeroSigmaADC) return 0.0f;
  return beta * feature(deltaADC, rho);
}

void fitModel() {
  modelValid = false;
  beta = 0.0f;
  calibrationMSE = NAN;
  if (!zeroValid || nCal < 2) return;

  // Choose the sign based on the largest signal, not the noisiest low-speed point.
  int best = 0;
  for (int i = 1; i < nCal; ++i)
    if (fabsf(cal[i].deltaADC) > fabsf(cal[best].deltaADC)) best = i;
  windSign = (cal[best].deltaADC >= 0.0f) ? 1 : -1;

  // Fit wind speed (not wind speed squared) by least squares.
  // This directly minimises speed MSE on calibration points, with a
  // zero-intercept physically-motivated one-parameter model.
  double numerator = 0.0, denominator = 0.0;
  int useful = 0;
  for (int i = 0; i < nCal; ++i) {
    float signedADC = windSign * cal[i].deltaADC;
    if (signedADC <= 3.0f * zeroSigmaADC) continue;
    float x = feature(cal[i].deltaADC, cal[i].rho);
    numerator += (double)x * cal[i].referenceMps;
    denominator += (double)x * x;
    ++useful;
  }
  if (useful < 2 || denominator <= 0.0) {
    Serial.println("MODEL: Need >=2 calibration points clearly above baseline noise.");
    return;
  }

  beta = (float)(numerator / denominator);
  modelValid = isfinite(beta) && beta > 0.0f;
  if (!modelValid) return;

  double sse = 0.0;
  for (int i = 0; i < nCal; ++i) {
    float estimate = predict(cal[i].deltaADC, cal[i].rho);
    double e = estimate - cal[i].referenceMps;
    sse += e * e;
  }
  calibrationMSE = (float)(sse / nCal);
  Serial.print("MODEL READY | direction=");
  Serial.print(windSign > 0 ? "+ADC" : "-ADC");
  Serial.print(" | beta=");
  Serial.print(beta, 6);
  Serial.print(" | calibration MSE=");
  Serial.print(calibrationMSE, 5);
  Serial.println(" (m/s)^2");
}

void zeroAndClear() {
  Serial.println("ZERO: Fan OFF. Wait for the complete plate assembly to settle.");
  Capture cap;
  if (!capture(cap)) return;
  zeroADC = cap.meanADC;
  zeroSigmaADC = cap.stdADC;
  zeroTempC = cap.tempC;
  zeroValid = true;
  nCal = nVal = 0;
  modelValid = false;
  emaValid = false;
  Serial.print("ZERO,ADC="); Serial.print(zeroADC, 2);
  Serial.print(",SIGMA="); Serial.print(zeroSigmaADC, 2);
  Serial.print(",TEMP_C="); Serial.print(zeroTempC, 2);
  Serial.print(",N="); Serial.println(cap.samples);
  Serial.println("Previous calibration/validation cleared. Start p <reference_mps>.");
}

void capturePoint(bool isValidation, float referenceMps) {
  if (!zeroValid) {
    Serial.println("ERROR: First run z in still air.");
    return;
  }
  if (referenceMps < 2.0f || referenceMps > 10.0f) {
    Serial.println("ERROR: Reference speed must be between 2 and 10 m/s.");
    return;
  }
  if (!isValidation && nCal >= MAX_CAL) {
    Serial.println("ERROR: Calibration point storage full."); return;
  }
  if (isValidation && nVal >= MAX_VAL) {
    Serial.println("ERROR: Validation point storage full."); return;
  }
  if (isValidation && !modelValid) {
    Serial.println("ERROR: Calibrate with >=2 valid p points first."); return;
  }
  Serial.print(isValidation ? "VALIDATION" : "CALIBRATION");
  Serial.print(" CAPTURE at reference ");
  Serial.print(referenceMps, 2);
  Serial.println(" m/s. Keep airflow stable throughout capture.");
  Capture cap;
  if (!capture(cap)) return;

  Sample p;
  p.referenceMps = referenceMps;
  p.meanADC = cap.meanADC;
  p.stdADC = cap.stdADC;
  p.temperatureC = cap.tempC;
  p.rho = airDensity(cap.tempC);
  p.deltaADC = cap.meanADC - zeroADC;

  if (isValidation) val[nVal++] = p;
  else cal[nCal++] = p;

  Serial.print("POINT,REF_MPS="); Serial.print(referenceMps, 3);
  Serial.print(",MEAN_ADC="); Serial.print(p.meanADC, 2);
  Serial.print(",DELTA_ADC="); Serial.print(p.deltaADC, 2);
  Serial.print(",STD_ADC="); Serial.print(p.stdADC, 2);
  Serial.print(",TEMP_C="); Serial.print(p.temperatureC, 2);
  Serial.print(",N="); Serial.println(cap.samples);

  if (!isValidation) fitModel();
  if (modelValid) {
    float pred = predict(p.deltaADC, p.rho);
    Serial.print("PREDICTED="); Serial.print(pred, 3);
    Serial.print(" m/s, ERROR="); Serial.print(pred - referenceMps, 3);
    Serial.println(" m/s");
  }
}

void report() {
  Serial.println("===== STATUS =====");
  Serial.print("Zero valid: "); Serial.println(zeroValid ? "YES" : "NO");
  Serial.print("Zero ADC: "); Serial.println(zeroADC, 2);
  Serial.print("Zero sigma ADC: "); Serial.println(zeroSigmaADC, 2);
  Serial.print("Calibration points: "); Serial.println(nCal);
  Serial.print("Validation points: "); Serial.println(nVal);
  Serial.print("Model valid: "); Serial.println(modelValid ? "YES" : "NO");
  if (modelValid) {
    Serial.print("Wind response sign: "); Serial.println(windSign);
    Serial.print("Beta: "); Serial.println(beta, 7);
    Serial.print("Training MSE (m/s)^2: "); Serial.println(calibrationMSE, 6);
  }
  if (modelValid) {
    // Save this command to a text file to restore model after reset.
    // Zero must be rechecked whenever mechanical mounting changes.
    Serial.print("RESTORE_CMD,k ");
    Serial.print(zeroADC, 2); Serial.print(' ');
    Serial.print(zeroSigmaADC, 2); Serial.print(' ');
    Serial.print(windSign); Serial.print(' ');
    Serial.println(beta, 8);
  }
  Serial.print("Last stream lines="); Serial.print(streamSequence);
  Serial.print(", missed_slots="); Serial.print(missedStreamSlots);
  Serial.print(", adc_poll_success="); Serial.print(adcSuccessfulPolls);
  Serial.print(", adc_value_changes="); Serial.print(adcValueChanges);
  Serial.print(", adc_read_errors="); Serial.println(adcReadErrors);
  Serial.print("Max scheduled output lateness (us)="); Serial.println(maxStreamLateUs);
  Serial.print("Max I2C ADC transaction (us)="); Serial.println(maxI2cReadUs);
  if (modelValid && nVal > 0) {
    double sse = 0.0, sae = 0.0, bias = 0.0;
    for (int i = 0; i < nVal; ++i) {
      float err = predict(val[i].deltaADC, val[i].rho) - val[i].referenceMps;
      sse += (double)err * err;
      sae += fabsf(err);
      bias += err;
    }
    Serial.print("VALIDATION MSE (m/s)^2: "); Serial.println(sse / nVal, 6);
    Serial.print("VALIDATION RMSE (m/s): "); Serial.println(sqrt(sse / nVal), 4);
    Serial.print("VALIDATION MAE (m/s): "); Serial.println(sae / nVal, 4);
    Serial.print("VALIDATION bias (m/s): "); Serial.println(bias / nVal, 4);
  }
}

void dumpCSV() {
  Serial.println("CSV_BEGIN");
  Serial.println("type,reference_mps,mean_adc,delta_adc,sigma_adc,temperature_c,air_density,predicted_mps,error_mps");
  for (int group = 0; group < 2; ++group) {
    int n = group == 0 ? nCal : nVal;
    Sample *p = group == 0 ? cal : val;
    for (int i = 0; i < n; ++i) {
      Serial.print(group == 0 ? "CAL" : "VAL"); Serial.print(',');
      Serial.print(p[i].referenceMps, 4); Serial.print(',');
      Serial.print(p[i].meanADC, 2); Serial.print(',');
      Serial.print(p[i].deltaADC, 2); Serial.print(',');
      Serial.print(p[i].stdADC, 2); Serial.print(',');
      Serial.print(p[i].temperatureC, 3); Serial.print(',');
      Serial.print(p[i].rho, 5); Serial.print(',');
      if (modelValid) {
        float pred = predict(p[i].deltaADC, p[i].rho);
        Serial.print(pred, 4); Serial.print(',');
        Serial.println(pred - p[i].referenceMps, 4);
      } else Serial.println(",");
    }
  }
  Serial.println("CSV_END");
  if (modelValid) {
    Serial.print("RESTORE_CMD,k "); Serial.print(zeroADC, 2); Serial.print(' ');
    Serial.print(zeroSigmaADC, 2); Serial.print(' ');
    Serial.print(windSign); Serial.print(' '); Serial.println(beta, 8);
  }
}

void checkZeroDrift() {
  if (!zeroValid) { Serial.println("First run z."); return; }
  Serial.println("ZERO CHECK: fan OFF, structure stationary.");
  Capture cap;
  if (!capture(cap)) return;
  float drift = cap.meanADC - zeroADC;
  Serial.print("ZERO_CHECK,DELTA_ADC="); Serial.print(drift, 2);
  Serial.print(",SIGMA_ADC="); Serial.println(cap.stdADC, 2);
  Serial.println("If drift is significant relative to low-speed signals, restart with z and recollect data.");
}

void help() {
  Serial.println();
  Serial.println("=== COMMANDS (Serial Monitor: Newline, 115200) ===");
  Serial.println("z       : zero in no wind; clears calibration and validation");
  Serial.println("p 2.0   : record a CALIBRATION point at reference 2.0 m/s");
  Serial.println("v 5.0   : record an independent VALIDATION point at 5.0 m/s");
  Serial.println("r       : report calibration and validation MSE/RMSE/MAE");
  Serial.println("d       : dump all collected data as CSV");
  Serial.println("q       : measure no-wind baseline drift without changing model");
  Serial.println("s       : scan I2C");
  Serial.println("g       : START 200Hz FLOAT-ONLY output for evaluator (x stops)");
  Serial.println("j       : START 200Hz seq,float diagnostic mode (x stops)");
  Serial.println("k Z SIG SIGN BETA : restore prior calibration, 4 numeric parameters");
  Serial.println("  Example: k 8836559 27.17 -1 0.218484");
  Serial.println("h       : this help");
  Serial.println("Note: ALL values in RAM; reset loses model and captures.");
  Serial.println("LIVE rows contain Device_ms for time-series logging.");
}

// Non-blocking single-attempt I2C read: a failed transaction does not wait 1 second.
bool readADCOnce(int32_t &out) {
  Wire.beginTransmission(WEIGHT_ADDR);
  Wire.write(WEIGHT_RAW_REG);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(WEIGHT_ADDR, (uint8_t)4) != 4) {
    while (Wire.available()) Wire.read();
    return false;
  }
  uint32_t p0=(uint8_t)Wire.read(), p1=(uint8_t)Wire.read();
  uint32_t p2=(uint8_t)Wire.read(), p3=(uint8_t)Wire.read();
  uint32_t packed=p0 | (p1<<8) | (p2<<16) | (p3<<24);
  memcpy(&out,&packed,sizeof(out));
  return true;
}

// Restore model from a saved export line. No PC-side speed inference is used.
// The model remains in STM32 RAM; export after calibration, restore after reset.
bool restoreCalibration(String line) {
  line.trim();
  if (!line.startsWith("k ") && !line.startsWith("K ")) return false;
  char temp[112];
  if (line.length() >= (int)sizeof(temp)) return false;
  line.toCharArray(temp, sizeof(temp));
  char *p = temp + 1;
  float values[4];
  for (int i = 0; i < 4; ++i) {
    while (*p == ' ' || *p == '\t') ++p;
    if (!*p) return false;
    char *end;
    values[i] = strtof(p, &end);
    if (end == p || !isfinite(values[i])) return false;
    p = end;
  }
  while (*p == ' ' || *p == '\t') ++p;
  if (*p != '\0' || values[1] < 0.0f || values[1] > 1e7f ||
      (values[2] != 1.0f && values[2] != -1.0f) ||
      values[3] <= 0.0f || values[3] > 1e7f) return false;
  zeroADC = values[0]; zeroSigmaADC = values[1];
  windSign = (int)values[2]; beta = values[3];
  zeroValid = modelValid = true;
  nCal = nVal = 0; // only coefficients are restored, not history
  emaValid = false;
  Serial.println("RESTORE_OK: model active on STM32. Verify with fan OFF and known speed before assessment.");
  report();
  return true;
}

void startStreaming200(bool debugSequence) {
  if (!debugSequence && (!zeroValid || !modelValid)) {
    Serial.println("ERROR: Need valid calibration, or restore it via k, before assessment output.");
    return;
  }
  streamDebugSequence = debugSequence;
  stream200 = true;
  streamSequence = missedStreamSlots = 0;
  adcSuccessfulPolls = adcReadErrors = adcValueChanges = 0;
  lastADCValueValid = false;
  maxStreamLateUs = maxI2cReadUs = tempReadErrors = 0;
  emaValid = false;
  // Prime sensor values before the first timed output, avoiding a spurious
  // startup zero when possible. This happens BEFORE scheduling the first slot.
  int32_t firstRaw;
  if (readADCOnce(firstRaw)) {
    emaADC = (float)firstRaw;
    emaValid = true;
    adcSuccessfulPolls++;
    lastADCValue = (uint32_t)firstRaw;
    lastADCValueValid = true;
  } else adcReadErrors++;
  streamTempOK = readTempC(streamTempC);
  if (!streamTempOK) ++tempReadErrors;
  nextStreamUs = micros() + STREAM_PERIOD_US;
  nextAdcPollUs = micros() + ADC_POLL_US;
  nextTempPollUs = micros() + TEMP_POLL_US;
  // No header: official reader expects one ASCII float per line in g mode.
}

void updateStreamMode() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == 'x' || c == 'X') {
      stream200 = false;
      Serial.print("STREAM_EXIT,lines="); Serial.print(streamSequence);
      Serial.print(",missed_slots="); Serial.print(missedStreamSlots);
      Serial.print(",adc_poll_success="); Serial.print(adcSuccessfulPolls);
      Serial.print(",adc_value_changes="); Serial.print(adcValueChanges);
      Serial.print(",adc_read_errors="); Serial.print(adcReadErrors);
      Serial.print(",max_late_us="); Serial.println(maxStreamLateUs);
      return;
    }
  }

  // Output first: slow I2C transactions should not routinely delay UART slots.
  uint32_t nowUs = micros();
  if ((int32_t)(nowUs - nextStreamUs) >= 0) {
    uint32_t lateUs = nowUs - nextStreamUs;
    if (lateUs > maxStreamLateUs) maxStreamLateUs = lateUs;
    uint32_t skipped = lateUs / STREAM_PERIOD_US;
    missedStreamSlots += skipped;
    streamSequence += skipped;
    nextStreamUs += (skipped + 1UL) * STREAM_PERIOD_US;

    // Use the most recently available (filtered) measurement at 200 Hz.
    float speed = 0.0f;
    if (emaValid && streamTempOK && modelValid) {
      speed = predict(emaADC - zeroADC, airDensity(streamTempC));
      if (!isfinite(speed) || speed < 0.0f) speed = 0.0f;
    }
    ++streamSequence;
    if (streamDebugSequence) {
      Serial.print(streamSequence);
      Serial.print(',');
    }
    Serial.println(speed, 3);
    return;
  }

  // Run I2C only if there is slack until the next 5ms output deadline.
  // At 100kHz, transactions are usually <2ms; test actual max time on hardware.
  if ((int32_t)(nextStreamUs - nowUs) < 2200) return;
  if ((int32_t)(nowUs - nextAdcPollUs) >= 0) {
    uint32_t start = micros();
    int32_t raw;
    if (readADCOnce(raw)) {
      ++adcSuccessfulPolls;
      if (lastADCValueValid && (uint32_t)raw != lastADCValue) ++adcValueChanges;
      lastADCValue = (uint32_t)raw;
      lastADCValueValid = true;
      if (!emaValid) { emaADC = (float)raw; emaValid = true; }
      else emaADC += EMA_ALPHA * ((float)raw - emaADC);
    } else ++adcReadErrors;
    uint32_t duration = micros() - start;
    if (duration > maxI2cReadUs) maxI2cReadUs = duration;
    nextAdcPollUs += ADC_POLL_US;
    if ((int32_t)(micros() - nextAdcPollUs) >= 0)
      nextAdcPollUs = micros() + ADC_POLL_US;
    return;
  }
  if ((int32_t)(nowUs - nextTempPollUs) >= 0) {
    float candidate;
    if (readTempC(candidate)) { streamTempC = candidate; streamTempOK = true; }
    else ++tempReadErrors; // hold last good temperature reading
    nextTempPollUs = micros() + TEMP_POLL_US;
  }
}

void processCommand(String line) {
  line.trim();
  if (line.length() == 0) return;
  char cmd = line.charAt(0);
  if (cmd == 'z' || cmd == 'Z') zeroAndClear();
  else if (cmd == 'g' || cmd == 'G') startStreaming200(false);
  else if (cmd == 'k' || cmd == 'K') { if (!restoreCalibration(line)) Serial.println("ERROR: use k <zero_ADC> <noise_sigma> <sign> <beta>"); }
  else if (cmd == 'j' || cmd == 'J') startStreaming200(true);
  else if (cmd == 'r' || cmd == 'R') report();
  else if (cmd == 'd' || cmd == 'D') dumpCSV();
  else if (cmd == 'q' || cmd == 'Q') checkZeroDrift();
  else if (cmd == 's' || cmd == 'S') scanBus();
  else if (cmd == 'h' || cmd == 'H') help();
  else if (cmd == 'p' || cmd == 'P' || cmd == 'v' || cmd == 'V') {
    float ref = 0.0f;
    String number = line.substring(1);
    number.trim();
    ref = number.toFloat();
    if (ref > 0.0f) capturePoint((cmd == 'v' || cmd == 'V'), ref);
    else Serial.println("ERROR: use e.g. 'p 3.0' or 'v 2.5'.");
  } else Serial.println("Unknown command. Send h.");
}

void setup() {
  Serial.begin(115200);
  delay(1200);
  Serial.setTimeout(120);

  Wire.setSDA(PB9);
  Wire.setSCL(PB8);
  Wire.begin();
  Wire.setClock(100000);
#if COMP0219_AUTOSTART
  // Assessment deployment with real calibration embedded in firmware.
  // Startup writes ONLY float lines; no prompts, headers, or PC-side inference.
  zeroADC = COMP0219_SAVED_ZERO_ADC;
  zeroSigmaADC = COMP0219_SAVED_ZERO_SIGMA;
  windSign = COMP0219_SAVED_SIGN;
  beta = COMP0219_SAVED_BETA;
  zeroValid = modelValid = (beta > 0.0f &&
                            (windSign == 1 || windSign == -1));
  if (modelValid) startStreaming200(false);
  return;
#endif
  Serial.println("STM32 wind tunnel multipoint speed calibration");
  scanBus();

  if (!present(WEIGHT_ADDR)) {
    Serial.println("FATAL: Weight-I2C 0x26 missing. Check power, GND, PB9 SDA, PB8 SCL.");
    while (true) delay(1000);
  }
  int32_t firstADC;
  if (!readADC(firstADC, 1500)) {
    Serial.println("FATAL: Weight-I2C detected but ADC register cannot be read.");
    while (true) delay(1000);
  }
  Serial.print("Weight-I2C ready. First ADC=");
  Serial.println(firstADC);
  if (!present(TEMP_ADDR))
    Serial.println("WARNING: MCP9808 not detected; captures require temperature.");
  else
    Serial.println("MCP9808 ready.");

  Serial.print("Plate area = "); Serial.print(PLATE_AREA_M2, 4);
  Serial.println(" m2. Direct calibration absorbs Cd and mounting effects.");
  Serial.println("Assumed pressure = 101325 Pa; use same setting for testing.");
  help();
  Serial.println("START: fan OFF, send z. Then record p 2.0, p 3.0, ... p 10.0; validate with v 5.0 etc.");
}

void loop() {
  if (stream200) { updateStreamMode(); return; }
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    processCommand(line);
  }
  if ((unsigned long)(millis() - lastPrint) < PRINT_PERIOD_MS) return;
  lastPrint = millis();

  int32_t raw;
  if (!readADC(raw, 500)) {
    Serial.println("LIVE,ADC_TIMEOUT");
    return;
  }
  float tempC;                                                                                                                                                                                                                      
  bool tempOK = readTempC(tempC);
  if (!emaValid) { emaADC = (float)raw; emaValid = true; }
  else emaADC += EMA_ALPHA * ((float)raw - emaADC);

  Serial.print("LIVE,Device_ms="); Serial.print(millis()); Serial.print(",Temp_C=");
  if (tempOK) Serial.print(tempC, 2);
  else Serial.print("ERROR");
  Serial.print(",Raw_ADC="); Serial.print(raw);

  if (!zeroValid) {
    Serial.println(",Wind=ZERO_REQUIRED"); return;
  }
  Serial.print(",Delta_ADC="); Serial.print(emaADC - zeroADC, 2);
  if (!modelValid || !tempOK) {
    Serial.println(",Wind=NOT_READY"); return;
  }

  float signedDelta = windSign * (emaADC - zeroADC);
  float rho = airDensity(tempC);
  float windMps = predict(emaADC - zeroADC, rho);
  Serial.print(",Density_kgm3="); Serial.print(rho, 4);
  Serial.print(",Wind_mps="); Serial.print(windMps, 3);
  Serial.print(",Wind_kmh="); Serial.print(windMps * 3.6f, 3);
  if (signedDelta <= 3.0f * zeroSigmaADC)
    Serial.println(",Status=BELOW_NOISE_OR_OPPOSITE");
  else
    Serial.println(",Status=ESTIMATED");
}
