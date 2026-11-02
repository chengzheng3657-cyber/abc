# 模拟采集客户端
import argparse
import json
import time
import urllib.error
import urllib.request
import urllib.parse
from model import BatchCalibration, simulate
class ApiError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
def request(base, path, payload=None):
    body = None if payload is None else json.dumps(payload, allow_nan=False).encode('utf-8')
    req = urllib.request.Request(base + path, data=body, headers={'Content-Type': 'application/json'})
    host = urllib.parse.urlsplit(base).hostname
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if host in ('127.0.0.1', 'localhost', '::1') else urllib.request.build_opener()
    try:
        with opener.open(req, timeout=120) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        with exc:
            message = exc.read().decode('utf-8', errors='replace')
        raise ApiError(exc.code, message) from exc
def rounded_image(batch, concentration):
    image, _ = simulate(batch, concentration)
    return [[[round(v) for v in pixel] for pixel in row] for row in image]
def run(base, sample_id, concentration=1.5):
    batch = BatchCalibration('DEMO0001', 'model-v1', demo=True, gain=1.05, background=242.0)
    print('simulation_calibration_started', flush=True)
    calibration = request(base, '/v1/batches', {'batch_id': batch.batch_id, 'version': batch.version, 'demo': True, 'standards': [{'concentration': c, 'image': rounded_image(batch, c)} for c in (0.0, 1.0, 3.0)]})
    payload = {'sample_id': sample_id, 'device_id': 'DEV00001', 'batch_id': batch.batch_id, 'timestamp': int(time.time()), 'location': {'latitude': 31.2304, 'longitude': 121.4737}, 'image': rounded_image(batch, concentration)}
    capture = request(base, '/v1/captures', payload)
    print('simulation_packet_received bytes=%s' % capture['packet_bytes'], flush=True)
    report = request(base, '/v1/packets', {'packet_base64': capture['packet_base64']})
    summary = {'system': report['system'], 'sample_id': sample_id, 'data_mode': report['data_mode'], 'known_concentration': concentration, 'estimated_concentration': report['concentration'], 'unit': report['unit'], 'status': report['status'], 'packet_bytes': report['packet_bytes'], 'core_count': report['core_count'], 'calibration_range': report['calibration_range'], 'calibration_rmse': calibration['calibration_rmse'], 'core_rmse': round(report['solver']['core_rmse'], 6), 'iterations': report['solver']['iterations'], 'content_sha256': report['content_sha256']}
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return payload, capture, report, summary
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8765')
    parser.add_argument('--sample-id', type=int, default=int(time.time()) & 4294967295)
    parser.add_argument('--concentration', type=float, default=1.5)
    args = parser.parse_args()
    run(args.base_url.rstrip('/'), args.sample_id, args.concentration)
if __name__ == '__main__':
    main()
