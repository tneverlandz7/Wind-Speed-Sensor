"""The firmware's one-parameter model, including its baseline noise deadband.

Density deliberately uses the firmware's fixed 101325 Pa convention. Reference
speeds may use actual ambient pressure; beta absorbs that constant at calibration.
"""
import numpy as np


def density(temp):
    temp = np.asarray(temp, dtype=float)
    if not np.isfinite(temp).all() or ((temp < -40) | (temp > 125)).any():
        raise ValueError('Temperature must be finite and within -40..125 C')
    return 101325.0 / (287.05 * (temp + 273.15))


def predict(delta, rho, beta, sign, zero_sigma=0.):
    delta, rho = np.broadcast_arrays(np.asarray(delta, dtype=float), np.asarray(rho, dtype=float))
    if (not np.isfinite(delta).all() or not np.isfinite(rho).all() or (rho <= 0).any()
            or not np.isfinite(beta) or beta <= 0 or sign not in (-1, 1)
            or not np.isfinite(zero_sigma) or zero_sigma < 0):
        raise ValueError('Invalid model parameters or nonfinite signal/density')
    signed = sign * delta
    return np.where(signed <= 3 * zero_sigma, 0., beta * np.sqrt(np.maximum(0., signed / rho)))


def validate_reference_range(min_reference_mps, max_reference_mps):
    if (not np.isfinite([min_reference_mps, max_reference_mps]).all()
            or not 0 < min_reference_mps < max_reference_mps):
        raise ValueError('Reference limits must be finite, positive, with minimum below maximum')


def fit_model(delta, rho, reference, zero_sigma, *, min_reference_mps=2., max_reference_mps=10.):
    validate_reference_range(min_reference_mps, max_reference_mps)
    delta, rho, reference = (np.asarray(a, dtype=float) for a in (delta, rho, reference))
    if (delta.ndim != 1 or delta.shape != rho.shape or delta.shape != reference.shape
            or len(delta) < 2 or not all(np.isfinite(a).all() for a in (delta, rho, reference))
            or (rho <= 0).any() or (reference < min_reference_mps).any() or (reference > max_reference_mps).any()
            or not np.isfinite(zero_sigma) or zero_sigma < 0):
        raise ValueError(f'Need >=2 finite calibration points within {min_reference_mps:g}..{max_reference_mps:g} m/s and valid density/noise')
    sign = 1 if delta[np.argmax(np.abs(delta))] >= 0 else -1
    useful = sign * delta > 3 * zero_sigma
    if useful.sum() < 2:
        raise ValueError('Need >=2 calibration points above baseline noise')
    x = np.sqrt(sign * delta[useful] / rho[useful])
    beta = float(np.dot(x, reference[useful]) / np.dot(x, x))
    if not np.isfinite(beta) or beta <= 0:
        raise ValueError('Fitting failed: invalid beta')
    return beta, sign, useful


def score(reference, predicted):
    error = np.asarray(predicted) - np.asarray(reference)
    return {'n': int(len(error)), 'MSE_m2_s2': float(np.mean(error**2)),
            'RMSE_m_s': float(np.sqrt(np.mean(error**2))),
            'MAE_m_s': float(np.mean(np.abs(error))), 'bias_m_s': float(np.mean(error))}
