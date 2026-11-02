# 图像校正
from model import HEIGHT, WIDTH
from validation import finite_number
def normalize_image(payload):
    image = payload.get('image')
    if not isinstance(image, list) or not 2 <= len(image) <= 256:
        raise ValueError('image应为高度2至256的RGB数组')
    height = len(image)
    if not isinstance(image[0], list) or not 2 <= len(image[0]) <= 256:
        raise ValueError('图像宽度须为2至256')
    width = len(image[0])
    for row in image:
        if not isinstance(row, list) or len(row) != width:
            raise ValueError('图像各行宽度不一致')
        for pixel in row:
            if not isinstance(pixel, list) or len(pixel) != 3:
                raise ValueError('每个像素须包含三个RGB通道')
            for value in pixel:
                finite_number(value, 'RGB', 0, 255)
    roi = payload.get('roi', [0, 0, width, height])
    if not isinstance(roi, list) or len(roi) != 4:
        raise ValueError('roi须为[x,y,width,height]')
    ox, oy, rw, rh = [finite_number(v, 'roi', 0, 256) for v in roi]
    if rw < 2 or rh < 2 or ox + rw > width or oy + rh > height:
        raise ValueError('roi超出图像范围')
    affine = payload.get('inverse_affine', [1, 0, 0, 0, 1, 0])
    if not isinstance(affine, list) or len(affine) != 6:
        raise ValueError('inverse_affine须含六个数值')
    a, b, c, d, e, f = [finite_number(v, 'inverse_affine', -10000, 10000) for v in affine]
    if abs(a * e - b * d) < 1e-9:
        raise ValueError('仿射矩阵不可逆')
    result = []
    for y in range(HEIGHT):
        row = []
        for x in range(WIDTH):
            px = ox + x * (rw - 1) / (WIDTH - 1)
            py = oy + y * (rh - 1) / (HEIGHT - 1)
            sx, sy = a * px + b * py + c, d * px + e * py + f
            if sx < -1e-8 or sy < -1e-8 or sx > width - 1 + 1e-8 or sy > height - 1 + 1e-8:
                raise ValueError('仿射变换采样坐标超出原图')
            sx, sy = max(0, min(width - 1, sx)), max(0, min(height - 1, sy))
            x0, y0 = int(sx), int(sy)
            x1, y1 = min(x0 + 1, width - 1), min(y0 + 1, height - 1)
            fx, fy = sx - x0, sy - y0
            row.append([(1 - fy) * ((1 - fx) * image[y0][x0][k] + fx * image[y0][x1][k]) + fy * ((1 - fx) * image[y1][x0][k] + fx * image[y1][x1][k]) for k in range(3)])
        result.append(row)
    return result
