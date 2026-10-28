#pragma once
// All four constants are placeholders until a REAL wind-tunnel calibration is complete.
// Leave AUTOSTART=0 for calibration and debug sessions.
// To create this file automatically after a successful lab calibration:
// python python/make_embedded_config.py --model-file data/lab_run01_calibration_restore.txt
#define COMP0219_AUTOSTART 0
#define COMP0219_SAVED_ZERO_ADC 0.0f
#define COMP0219_SAVED_ZERO_SIGMA 0.0f
#define COMP0219_SAVED_SIGN 1
#define COMP0219_SAVED_BETA 0.0f
