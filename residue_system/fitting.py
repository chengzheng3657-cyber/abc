# 浓度拟合
import math
from sampling import sample_weights
from model import simulate
from wire import validate_points
MAX_ITERATIONS = 80
INTERVAL_TOLERANCE = 1e-5
MAX_WEIGHTED_MSE = 0.12
MAX_PIXEL_RMSE = 2.0
def fit_concentration(batch, points):
    validate_points(points)
    weights = sample_weights(batch, points)
    history = []
    best_loss = math.inf
    best_concentration = batch.min_concentration
    def evaluate(concentration):
        nonlocal best_loss, best_concentration
        image, _ = simulate(batch, concentration)
        loss = sum(weight * sum((image[y][x][channel] - rgb[channel]) ** 2 for channel in range(3)) / 3 for (x, y, *rgb), weight in zip(points, weights))
        history.append({'evaluation': len(history) + 1, 'loss': round(loss, 8), 'concentration': round(concentration, 8)})
        if loss < best_loss:
            best_loss, best_concentration = loss, concentration
        return loss
    lower, upper = batch.min_concentration, batch.max_concentration
    ratio = (math.sqrt(5) - 1) / 2
    left = upper - ratio * (upper - lower)
    right = lower + ratio * (upper - lower)
    left_loss, right_loss = evaluate(left), evaluate(right)
    iterations = 0
    # 单变量有界求解，边界取自实际标定浓度范围
    while upper - lower > INTERVAL_TOLERANCE and iterations < MAX_ITERATIONS:
        if left_loss < right_loss:
            upper, right, right_loss = right, left, left_loss
            left = upper - ratio * (upper - lower)
            left_loss = evaluate(left)
        else:
            lower, left, left_loss = left, right, right_loss
            right = lower + ratio * (upper - lower)
            right_loss = evaluate(right)
        iterations += 1
    evaluate(batch.min_concentration)
    evaluate(batch.max_concentration)
    converged = upper - lower <= INTERVAL_TOLERANCE
    image, derivative = simulate(batch, best_concentration)
    pixel_rmse = math.sqrt(sum((image[y][x][channel] - rgb[channel]) ** 2 for x, y, *rgb in points for channel in range(3)) / (len(points) * 3))
    control_valid = any(34 <= x <= 38 and green < batch.background - 20 for x, _, _, green, _ in points)
    background_valid = any(x <= 8 and max(abs(value - batch.background) for value in rgb) <= 10 for x, _, *rgb in points)
    target_observed = any(17 <= x <= 23 for x, *_ in points)
    boundary_margin = 10 * INTERVAL_TOLERANCE
    at_upper_limit = best_concentration >= batch.max_concentration - boundary_margin
    at_lower_limit = batch.min_concentration > 0 and best_concentration <= batch.min_concentration + boundary_margin
    reasons = []
    checks = [('not_converged', converged), ('model_mismatch', best_loss <= MAX_WEIGHTED_MSE and pixel_rmse <= MAX_PIXEL_RMSE), ('control_missing', control_valid), ('background_mismatch', background_valid), ('target_missing', target_observed), ('calibration_range_limit', not at_upper_limit and not at_lower_limit)]
    for reason, passed in checks:
        if not passed:
            reasons.append(reason)
    gradient = sum(weight * 2 * sum((image[y][x][channel] - rgb[channel]) * derivative[y][x][channel] for channel in range(3)) / 3 for (x, y, *rgb), weight in zip(points, weights))
    return {'status': 'invalid' if reasons else 'valid', 'reasons': reasons, 'converged': converged, 'stop_reason': 'interval_tolerance' if converged else 'iteration_limit', 'method': 'bounded_scalar', 'concentration': best_concentration, 'weighted_mse': best_loss, 'core_rmse': pixel_rmse, 'loss_gradient': gradient, 'control_valid': control_valid, 'background_valid': background_valid, 'target_observed': target_observed, 'calibration_range': [batch.min_concentration, batch.max_concentration], 'iterations': iterations, 'evaluations': len(history), 'history': history}
