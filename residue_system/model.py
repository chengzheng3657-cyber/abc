# 试纸条响应模型
import math
from dataclasses import asdict, dataclass
from validation import finite_number, identifier
@dataclass(frozen=True)
class BatchCalibration:
    batch_id: str
    version: str
    demo: bool = False
    diffusion: float = 0.18
    velocity: float = 0.8
    binding_rate: float = 0.7
    dissociation_rate: float = 0.04
    capacity: float = 1.0
    gain: float = 0.9
    background: float = 240.0
    recovery_factor: float = 1.0
    max_concentration: float = 10.0
    min_concentration: float = 0.0
    def __post_init__(self):
        identifier(self.batch_id, 'batch_id')
        if not isinstance(self.version, str) or not 1 <= len(self.version) <= 64:
            raise ValueError('模型版本无效')
        if not isinstance(self.demo, bool):
            raise ValueError('demo必须为布尔值')
        limits = {
            'diffusion': (0.01, 1), 'velocity': (0.1, 1),
            'binding_rate': (0.01, 1), 'dissociation_rate': (0.001, 0.5),
            'capacity': (0.1, 1), 'gain': (0.01, 4),
            'background': (1, 255), 'recovery_factor': (0.01, 10),
            'max_concentration': (0.1, 10), 'min_concentration': (0, 10)
        }
        for name, bounds in limits.items():
            finite_number(getattr(self, name), name, *bounds)
        if self.min_concentration >= self.max_concentration:
            raise ValueError('标定浓度上下界无效')
    def to_dict(self):
        return asdict(self)
WIDTH = 48
HEIGHT = 6
CHANNELS = (0.28, 1.0, 0.85)
def simulate(batch, concentration):
    concentration = finite_number(concentration, 'concentration', 0, batch.max_concentration)
    free = [0.0] * WIDTH
    free_sensitivity = [0.0] * WIDTH
    bound = [0.0] * WIDTH
    bound_sensitivity = [0.0] * WIDTH
    dt = 0.1
    sites = [batch.capacity * math.exp(-0.5 * ((x - 20) / 1.8) ** 2) for x in range(WIDTH)]
    for _ in range(500):
        updated = [0.0] * WIDTH
        updated_sensitivity = [0.0] * WIDTH
        for x in range(WIDTH):
            left = concentration if x == 0 else free[x - 1]
            left_d = 1.0 if x == 0 else free_sensitivity[x - 1]
            right = free[x + 1] if x < WIDTH - 1 else free[x]
            right_d = free_sensitivity[x + 1] if x < WIDTH - 1 else free_sensitivity[x]
            site = sites[x]
            reaction = batch.binding_rate * free[x] * (site - bound[x]) - batch.dissociation_rate * bound[x]
            reaction_d = batch.binding_rate * (free_sensitivity[x] * (site - bound[x]) - free[x] * bound_sensitivity[x]) - batch.dissociation_rate * bound_sensitivity[x]
            transport = batch.diffusion * (right - 2 * free[x] + left) - batch.velocity * (free[x] - left)
            transport_d = batch.diffusion * (right_d - 2 * free_sensitivity[x] + left_d) - batch.velocity * (free_sensitivity[x] - left_d)
            updated[x] = free[x] + dt * (transport - reaction)
            updated_sensitivity[x] = free_sensitivity[x] + dt * (transport_d - reaction_d)
            bound[x] += dt * reaction
            bound_sensitivity[x] += dt * reaction_d
        free, free_sensitivity = updated, updated_sensitivity
    image, derivative = [], []
    for y in range(HEIGHT):
        row, gradient = [], []
        profile = 0.9 + 0.1 * math.cos((y - 2.5) / 3.0)
        for x in range(WIDTH):
            control = 0.65 * math.exp(-0.5 * ((x - 36) / 1.6) ** 2)
            amount = profile * (bound[x] + control)
            pixel = [batch.background * math.exp(-batch.gain * channel * amount) for channel in CHANNELS]
            row.append(pixel)
            gradient.append([-value * batch.gain * channel * profile * bound_sensitivity[x] for value, channel in zip(pixel, CHANNELS)])
        image.append(row)
        derivative.append(gradient)
    return image, derivative
def calibrate(batch, standards):
    if len(standards) < 3 or len({item[0] for item in standards}) < 3:
        raise ValueError('标定至少需要三个不同浓度的标准品')
    observations = []
    for concentration, actual in standards:
        predicted, _ = simulate(batch, concentration)
        for y in range(HEIGHT):
            for x in range(WIDTH):
                for channel in range(3):
                    value = actual[y][x][channel]
                    if value <= 0:
                        raise ValueError('标定像素必须大于零')
                    optical = -math.log(predicted[y][x][channel] / batch.background) / batch.gain
                    observations.append((optical, math.log(value)))
    count = len(observations)
    mean_x = sum(x for x, _ in observations) / count
    mean_y = sum(y for _, y in observations) / count
    variance = sum((x - mean_x) ** 2 for x, _ in observations)
    if variance < 1e-10:
        raise ValueError('标定图像信息不足')
    slope = sum((x - mean_x) * (y - mean_y) for x, y in observations) / variance
    gain = -slope
    background = math.exp(mean_y - slope * mean_x)
    if not 0.01 <= gain <= 4 or not 1 <= background <= 255:
        raise ValueError('标定参数超出物理范围')
    samples = [(optical, math.exp(log_value)) for optical, log_value in observations]
    for _ in range(12):
        aa = ab = bb = residual_a = residual_b = 0.0
        current_error = 0.0
        for optical, actual in samples:
            attenuation = math.exp(-gain * optical)
            predicted = background * attenuation
            gain_derivative = -optical * predicted
            residual = actual - predicted
            aa += attenuation * attenuation
            ab += attenuation * gain_derivative
            bb += gain_derivative * gain_derivative
            residual_a += attenuation * residual
            residual_b += gain_derivative * residual
            current_error += residual * residual
        determinant = aa * bb - ab * ab
        if determinant <= 1e-12:
            raise ValueError('标定参数不可辨识')
        background_step = (bb * residual_a - ab * residual_b) / determinant
        gain_step = (aa * residual_b - ab * residual_a) / determinant
        accepted = False
        for attempt in range(12):
            scale = 0.5 ** attempt
            next_background = background + scale * background_step
            next_gain = gain + scale * gain_step
            if not 1 <= next_background <= 255 or not 0.01 <= next_gain <= 4:
                continue
            error = sum((next_background * math.exp(-next_gain * optical) - actual) ** 2 for optical, actual in samples)
            if error <= current_error:
                background, gain = next_background, next_gain
                accepted = True
                break
        if not accepted or max(abs(background_step), abs(gain_step)) < 1e-8:
            break
    config = batch.to_dict()
    config.update(gain=gain, background=background, min_concentration=min(c for c, _ in standards), max_concentration=max(c for c, _ in standards))
    fitted = BatchCalibration(**config)
    error, total = 0.0, 0
    for concentration, actual in standards:
        predicted, _ = simulate(fitted, concentration)
        for y in range(HEIGHT):
            for x in range(WIDTH):
                error += sum((a - b) ** 2 for a, b in zip(actual[y][x], predicted[y][x]))
                total += 3
    return fitted, math.sqrt(error / total)
