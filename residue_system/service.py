# 检测业务服务
import threading
import time
from images import normalize_image
from model import BatchCalibration, calibrate
from sampling import sample_pixels
from wire import decode, encode
from fitting import fit_concentration
from reports import build_report
from repository import content_digest
from validation import ConflictError, RequestError, finite_number, identifier, uint32
class DetectionService:
    def __init__(self, repository):
        self.repository = repository
        self.lock = threading.Lock()
    def register_batch(self, payload):
        batch_id = identifier(payload.get('batch_id'), 'batch_id')
        version = payload.get('version', 'model-v1')
        if not isinstance(version, str) or not 1 <= len(version) <= 64:
            raise RequestError('version须为1至64字符')
        demo = payload.get('demo', False)
        if not isinstance(demo, bool):
            raise RequestError('demo须为布尔值')
        fields = {'batch_id': batch_id, 'version': version, 'demo': demo}
        limits = {'diffusion': (0.01, 1), 'velocity': (0.1, 1), 'binding_rate': (0.01, 1), 'dissociation_rate': (0.001, 0.5), 'capacity': (0.1, 1), 'recovery_factor': (0.01, 10), 'max_concentration': (0.1, 10)}
        parameters = payload.get('parameters', {})
        if not isinstance(parameters, dict) or set(parameters) - set(limits):
            raise RequestError('存在不支持的批次参数')
        for name, value in parameters.items():
            fields[name] = finite_number(value, name, *limits[name])
        batch = BatchCalibration(**fields)
        standards = payload.get('standards')
        if not isinstance(standards, list) or not 3 <= len(standards) <= 8:
            raise RequestError('standards须包含3至8份标准品')
        normalized = []
        for item in standards:
            if not isinstance(item, dict):
                raise RequestError('标准品格式无效')
            concentration = finite_number(item.get('concentration'), '标准品浓度', 0, batch.max_concentration)
            normalized.append((concentration, normalize_image(item)))
        print('calibration_started batch_id=' + batch_id, flush=True)
        batch, rmse = calibrate(batch, normalized)
        if rmse > 2:
            raise RequestError('标定RMSE超过2，当前模型不适配输入标准品')
        self.repository.add_batch(batch, {'standards': standards, 'rmse': rmse, 'parameters': parameters})
        return {'batch': batch.to_dict(), 'calibration_rmse': round(rmse, 6), 'status': 'calibrated'}
    def create_capture(self, payload):
        device_id = identifier(payload.get('device_id'), 'device_id')
        sample_id = uint32(payload.get('sample_id'), 'sample_id', 1)
        batch = self.repository.batch(identifier(payload.get('batch_id'), 'batch_id'))
        timestamp = uint32(payload.get('timestamp', int(time.time())), 'timestamp')
        location = payload.get('location')
        if location is not None:
            if not isinstance(location, dict) or set(location) != {'latitude', 'longitude'}:
                raise RequestError('location须含latitude和longitude')
            finite_number(location['latitude'], 'latitude', -90, 90)
            finite_number(location['longitude'], 'longitude', -180, 180)
        source_digest = content_digest(payload)
        existing = self.repository.get('captures', device_id, sample_id, source_digest)
        if existing is not None:
            return existing['response']
        image = normalize_image(payload)
        points = sample_pixels(image, batch)
        packet_base64, packet_size = encode(sample_id, timestamp, device_id, batch.batch_id, points)
        response = {'sample_id': sample_id, 'device_id': device_id, 'packet_base64': packet_base64, 'packet_bytes': packet_size, 'core_count': len(points), 'transport': 'binary_payload_for_beidou_adapter'}
        capture = {'response': response, 'source': payload, 'normalized_image': image, 'location': location, 'model_version': batch.version}
        saved = self.repository.save('captures', device_id, sample_id, source_digest, capture)
        print('capture_saved device_id=%s sample_id=%s packet_bytes=%s' % (device_id, sample_id, packet_size), flush=True)
        return saved['response']
    def process_packet(self, payload):
        encoded = payload.get('packet_base64')
        packet = decode(encoded)
        device_id, sample_id = packet['device_id'], packet['sample_id']
        digest = content_digest(encoded)
        existing = self.repository.get('reports', device_id, sample_id, digest)
        if existing is not None:
            return existing
        batch = self.repository.batch(packet['batch_id'])
        capture = self.repository.get('captures', device_id, sample_id)
        location = None
        if capture is not None:
            if capture['response']['packet_base64'] != encoded:
                raise ConflictError('报文与已有采集记录不一致')
            location = capture['location']
        result = fit_concentration(batch, packet['points'])
        report = build_report(batch, packet, result, location)
        saved = self.repository.save('reports', device_id, sample_id, digest, report)
        print('report_saved device_id=%s sample_id=%s status=%s' % (device_id, sample_id, result['status']), flush=True)
        return saved
    def dispatch(self, path, payload):
        with self.lock:
            routes = {'/v1/batches': self.register_batch, '/v1/captures': self.create_capture, '/v1/packets': self.process_packet}
            if path in routes:
                return routes[path](payload)
            if path == '/v1/analyze':
                response = self.create_capture(payload)
                return self.process_packet({'packet_base64': response['packet_base64']})
            raise RequestError('接口不存在')
