# 系统回归测试
import base64
import copy
import hashlib
import http.client
import json
import math
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from demo_client import ApiError, request, rounded_image, run
from images import normalize_image
from model import BatchCalibration, simulate
from repository import Repository, content_digest
from runtime import running_server
from validation import ConflictError
from wire import decode, encode
class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='residue-test-')
        cls.runtime = running_server(cls.directory.name)
        try:
            cls.base = cls.runtime.__enter__()
            cls.payload, cls.capture, cls.report, cls.summary = run(cls.base, 1001)
        except Exception:
            cls.runtime.__exit__(None, None, None)
            cls.directory.cleanup()
            raise
    @classmethod
    def tearDownClass(cls):
        cls.runtime.__exit__(None, None, None)
        cls.directory.cleanup()
    def assert_api_error(self, status, path, payload):
        with self.assertRaises(ApiError) as caught:
            request(self.base, path, payload)
        self.assertEqual(caught.exception.status, status)
        return str(caught.exception)
    def raw_post(self, body):
        port = int(self.base.rsplit(':', 1)[-1])
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        try:
            connection.request('POST', '/v1/captures', body, {'Content-Type': 'application/json'})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()
    def test_report_and_idempotency(self):
        self.assertEqual(self.report['status'], 'valid')
        self.assertLess(abs(self.report['concentration'] - 1.5), 0.08)
        self.assertEqual(self.capture['packet_bytes'], 76)
        self.assertEqual(request(self.base, '/v1/packets', {'packet_base64': self.capture['packet_base64']}), self.report)
        self.assertEqual(request(self.base, '/v1/analyze', self.payload), self.report)
        content = dict(self.report)
        digest = content.pop('content_sha256')
        serialized = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        self.assertEqual(hashlib.sha256(serialized.encode()).hexdigest(), digest)
        reconstructed = base64.b64decode(self.report['reconstruction']['base64'], validate=True)
        self.assertEqual(len(reconstructed), len(b'P6\n48 6\n255\n') + 48 * 6 * 3)
    def test_crc_and_capture_conflict(self):
        damaged = bytearray(base64.b64decode(self.capture['packet_base64']))
        damaged[35] ^= 1
        message = self.assert_api_error(400, '/v1/packets', {'packet_base64': base64.b64encode(damaged).decode()})
        self.assertIn('CRC', message)
        changed = dict(self.payload, image=[[[0, 0, 0]]])
        self.assert_api_error(409, '/v1/captures', changed)
    def test_bad_image_and_unknown_batch(self):
        dark = dict(self.payload, sample_id=1002, image=[[[5, 5, 5] for _ in range(48)] for _ in range(6)])
        rejected = request(self.base, '/v1/analyze', dark)
        self.assertEqual(rejected['status'], 'invalid')
        self.assertIsNone(rejected['concentration'])
        self.assertIn('model_mismatch', rejected['solver']['reasons'])
        self.assert_api_error(404, '/v1/analyze', dict(self.payload, sample_id=1003, batch_id='UNKNOWN'))
    def test_calibration_range(self):
        batch = BatchCalibration('DEMO0001', 'model-v1', demo=True, gain=1.05, background=242.0)
        for index, concentration in enumerate((0.0, 0.2, 2.5)):
            payload = dict(self.payload, sample_id=1100 + index, image=rounded_image(batch, concentration))
            result = request(self.base, '/v1/analyze', payload)
            self.assertEqual(result['status'], 'valid')
            self.assertLess(abs(result['concentration'] - concentration), max(0.08, concentration * 0.08))
        payload = dict(self.payload, sample_id=1110, image=rounded_image(batch, 8.0))
        result = request(self.base, '/v1/analyze', payload)
        self.assertIsNone(result['concentration'])
        self.assertIn('calibration_range_limit', result['solver']['reasons'])
        self.assertEqual(result['calibration_range'], [0.0, 3.0])
    def test_packet_before_capture(self):
        packet = decode(self.capture['packet_base64'])
        packet['sample_id'] = 1200
        encoded, _ = encode(packet['sample_id'], packet['timestamp'], packet['device_id'], packet['batch_id'], packet['points'])
        report = request(self.base, '/v1/packets', {'packet_base64': encoded})
        self.assertIsNone(report['location'])
        changed = dict(self.payload, sample_id=1200, image=[[[5, 5, 5] for _ in range(48)] for _ in range(6)])
        self.assert_api_error(409, '/v1/captures', changed)
        matching = dict(self.payload, sample_id=1200)
        capture = request(self.base, '/v1/captures', matching)
        self.assertEqual(capture['packet_base64'], encoded)
        self.assertEqual(request(self.base, '/v1/packets', {'packet_base64': encoded}), report)
    def test_malformed_json(self):
        for raw in (b'{"sample_id":1,"sample_id":2}', b'{"timestamp":NaN}', b'[]', b'{}x'):
            status, _ = self.raw_post(raw)
            self.assertEqual(status, 400)
    def test_parallel_retries(self):
        payload = dict(self.payload, sample_id=1300)
        with ThreadPoolExecutor(max_workers=4) as executor:
            reports = list(executor.map(lambda _: request(self.base, '/v1/analyze', payload), range(4)))
        self.assertTrue(all(report == reports[0] for report in reports))
    def test_database_restart(self):
        with running_server(self.directory.name) as base:
            report = request(base, '/v1/packets', {'packet_base64': self.capture['packet_base64']})
        self.assertEqual(report, self.report)
    def test_changed_calibration_is_rejected(self):
        batch = BatchCalibration('DEMO0001', 'model-v1', demo=True, gain=1.05, background=242.0)
        standards = [{'concentration': value, 'image': rounded_image(batch, value)} for value in (0.0, 1.0, 3.0)]
        standards[0]['image'][0][0][0] -= 1
        self.assert_api_error(409, '/v1/batches', {'batch_id': batch.batch_id, 'demo': True, 'standards': standards})
class ModelTests(unittest.TestCase):
    def test_concentration_derivative(self):
        batch = BatchCalibration('TEST', 'v1')
        image, gradient = simulate(batch, 1.5)
        upper, _ = simulate(batch, 1.50001)
        for x in (18, 20, 22):
            finite = (upper[2][x][1] - image[2][x][1]) / 0.00001
            self.assertTrue(math.isclose(finite, gradient[2][x][1], rel_tol=0.001, abs_tol=0.001))
    def test_image_alignment(self):
        image = [[[x, y, x + y] for x in range(48)] for y in range(6)]
        aligned = normalize_image({'image': image})
        self.assertEqual(aligned, image)
        with self.assertRaises(ValueError):
            normalize_image({'image': image, 'inverse_affine': [1, 0, 2, 0, 1, 0]})
        broken = copy.deepcopy(image)
        broken[0][0][0] = True
        with self.assertRaises(ValueError):
            normalize_image({'image': broken})
    def test_packet_round_trip(self):
        points = [(20, 2, 120, 80, 90), (36, 2, 200, 150, 160)]
        encoded, size = encode(1, 1000, 'DEVICE01', 'BATCH001', points)
        result = decode(encoded)
        self.assertEqual(result['points'], points)
        self.assertEqual(size, 48)
        with self.assertRaises(ValueError):
            encode(0, 1000, 'DEVICE01', 'BATCH001', points)
        with self.assertRaises(ValueError):
            encode(1, 1000, 'DEVICE01', 'BATCH001', [points[0], points[0]])
    def test_legacy_database_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'legacy.sqlite3'
            database = sqlite3.connect(path)
            try:
                database.execute('CREATE TABLE batches (batch_id TEXT)')
                database.execute("INSERT INTO batches VALUES ('EXISTING')")
                database.commit()
                with self.assertRaisesRegex(RuntimeError, '旧版数据库'):
                    Repository(path)
                self.assertEqual(database.execute('SELECT batch_id FROM batches').fetchall(), [('EXISTING',)])
            finally:
                database.close()
    def test_batch_parameter_validation(self):
        for changes in ({'diffusion': -1}, {'max_concentration': float('nan')}, {'demo': 'false'}):
            with self.assertRaises(ValueError):
                BatchCalibration('TEST', 'v1', **changes)
    def test_repository_conflict_is_atomic(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Repository(Path(directory) / 'test.sqlite3')
            repository.save('reports', 'DEVICE01', 1, content_digest('packet-a'), {'status': 'valid'})
            capture = {'response': {'packet_base64': 'packet-b'}}
            with self.assertRaises(ConflictError):
                repository.save('captures', 'DEVICE01', 1, content_digest(capture), capture)
            self.assertIsNone(repository.get('captures', 'DEVICE01', 1))
if __name__ == '__main__':
    unittest.main(verbosity=2)
