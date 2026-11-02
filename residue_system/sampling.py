# 像素采样
import hashlib
import json
import math
import random
from model import HEIGHT, WIDTH, simulate
TARGET_SAMPLE_COUNT = 4
CONTROL_POINT = (36, 2)
BACKGROUND_POINT = (4, 2)
def reference_concentration(batch):
    return min(batch.max_concentration, max(batch.min_concentration, 1.0))
def sample_pixels(image, batch):
    reference_image, derivative = simulate(batch, reference_concentration(batch))
    sensitivity = {(x, y): math.sqrt(sum(value * value for value in derivative[y][x])) for y in range(HEIGHT) for x in range(WIDTH)}
    peak = max(sensitivity.values())
    if peak <= 1e-8:
        raise ValueError('当前批次在采样参考浓度下没有足够响应')
    candidates = []
    sampled_levels = set()
    for point in sorted(sensitivity, key=sensitivity.get, reverse=True):
        if point in (CONTROL_POINT, BACKGROUND_POINT):
            continue
        x, y = point
        signal = tuple(round(value) for value in reference_image[y][x])
        if signal in sampled_levels:
            continue
        sampled_levels.add(signal)
        candidates.append(point)
        if len(candidates) == 80:
            break
    if len(candidates) < TARGET_SAMPLE_COUNT:
        raise ValueError('有效响应等级不足，无法选择采样点')
    seed_data = json.dumps(batch.to_dict(), sort_keys=True).encode('utf-8')
    seed = int.from_bytes(hashlib.sha256(seed_data).digest()[:8], 'big')
    rng = random.Random(seed)
    def score(points):
        distance = min(math.dist(point, other) for index, point in enumerate(points) for other in points[index + 1:])
        return sum(sensitivity[point] / peak for point in points) + 0.15 * distance
    population = [rng.sample(candidates, TARGET_SAMPLE_COUNT) for _ in range(24)]
    for _ in range(30):
        population.sort(key=score, reverse=True)
        next_population = population[:4]
        while len(next_population) < 24:
            parent_a, parent_b = rng.sample(population[:12], 2)
            split = rng.randrange(1, TARGET_SAMPLE_COUNT)
            offspring = list(dict.fromkeys(parent_a[:split] + parent_b[split:]))
            while len(offspring) < TARGET_SAMPLE_COUNT:
                point = rng.choice(candidates)
                if point not in offspring:
                    offspring.append(point)
            if rng.random() < 0.25:
                index = rng.randrange(TARGET_SAMPLE_COUNT)
                offspring[index] = rng.choice([point for point in candidates if point not in offspring])
            next_population.append(offspring)
        population = next_population
    selected = max(population, key=score) + [CONTROL_POINT, BACKGROUND_POINT]
    return [(x, y, *(round(value) for value in image[y][x])) for x, y in selected]
def sample_weights(batch, points):
    _, derivative = simulate(batch, reference_concentration(batch))
    values = [max(1.0, math.sqrt(sum(value * value for value in derivative[y][x]))) for x, y, *_ in points]
    total = sum(values)
    return [value / total for value in values]
