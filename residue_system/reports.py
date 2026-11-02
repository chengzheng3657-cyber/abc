# 检测报告
import base64
import datetime
from model import HEIGHT, WIDTH, simulate
from repository import content_digest
def build_report(batch, packet, result, location=None):
    image, _ = simulate(batch, result['concentration'])
    pixels = bytes(max(0, min(255, round(value))) for row in image for pixel in row for value in pixel)
    ppm = ('P6\n%d %d\n255\n' % (WIDTH, HEIGHT)).encode('ascii') + pixels
    concentration = None
    if result['status'] == 'valid':
        concentration = round(result['concentration'] * batch.recovery_factor, 4)
    report = {
        'system': '组织残留快检系统',
        'sample_id': packet['sample_id'],
        'device_id': packet['device_id'],
        'batch_id': batch.batch_id,
        'model_version': batch.version,
        'calibration_range': [batch.min_concentration, batch.max_concentration],
        'data_mode': 'simulation' if batch.demo else 'external_calibration',
        'method': 'transport_binding_1d',
        'sample_time': datetime.datetime.fromtimestamp(packet['timestamp'], datetime.timezone.utc).isoformat(),
        'generated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'location': location,
        'status': result['status'],
        'concentration': concentration,
        'unit': 'ng/mL',
        'raw_concentration': round(result['concentration'], 6),
        'recovery_factor': batch.recovery_factor,
        'packet_bytes': packet['packet_bytes'],
        'core_count': len(packet['points']),
        'solver': result,
        'fixed_parameters': {
            'diffusion': batch.diffusion,
            'binding_rate': batch.binding_rate,
            'dissociation_rate': batch.dissociation_rate
        },
        'reconstruction': {
            'label': '模型重构图像',
            'mime': 'image/x-portable-pixmap',
            'width': WIDTH,
            'height': HEIGHT,
            'base64': base64.b64encode(ppm).decode('ascii')
        },
        'limitations': [
            '一维简化响应模型，扩散和反应速率按批次固定',
            '未完成实际试剂定量方法验证，报告不含数字签名',
            '重构图像不是原始照片，浓度尚未换算为组织质量残留量'
        ]
    }
    report['content_sha256'] = content_digest(report)
    return report
