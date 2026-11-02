# HTTP接口
import argparse
import json
import logging
import os
import sqlite3
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from service import DetectionService
from repository import Repository
from validation import RequestError, load_json
MAX_BODY_BYTES = 4 * 1024 * 1024
ROUTES = {'/v1/batches', '/v1/captures', '/v1/packets', '/v1/analyze'}
LOGGER = logging.getLogger(__name__)
class RequestHandler(BaseHTTPRequestHandler):
    server_version = 'ResidueHTTP/2.0'
    def log_message(self, message, *args):
        return
    def respond(self, status, data):
        content = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(content)
        self.close_connection = True
    def do_GET(self):
        if self.path in ('/', '/index.html'):
            content = Path(__file__).with_name('index.html').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(content)
        elif self.path == '/health':
            self.respond(200, {'status': 'ok', 'system': '组织残留快检系统', 'api_version': 1})
        else:
            self.respond(404, {'error': '接口不存在'})
    def do_POST(self):
        try:
            if self.path not in ROUTES:
                self.respond(404, {'error': '接口不存在'})
                return
            if self.headers.get('Transfer-Encoding'):
                raise RequestError('不支持分块请求')
            if self.headers.get_content_type() != 'application/json':
                self.respond(415, {'error': '仅支持application/json'})
                return
            lengths = self.headers.get_all('Content-Length', [])
            if len(lengths) != 1 or not lengths[0].isdigit():
                raise RequestError('必须提供唯一且有效的Content-Length')
            length = int(lengths[0])
            if not 1 <= length <= MAX_BODY_BYTES:
                self.respond(413, {'error': '请求数据长度超出允许范围'})
                return
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise RequestError('请求数据不完整')
            payload = load_json(raw)
            if not isinstance(payload, dict):
                raise RequestError('请求必须为JSON对象')
            self.respond(200, self.server.service.dispatch(self.path, payload))
        except RequestError as exc:
            self.respond(exc.status, {'error': str(exc)})
        except (ValueError, UnicodeError, RecursionError) as exc:
            self.respond(400, {'error': str(exc)})
        except TimeoutError:
            self.respond(408, {'error': '请求读取超时'})
        except sqlite3.Error:
            LOGGER.exception('database_request_failed path=%s', self.path)
            self.respond(503, {'error': '数据存储暂不可用'})
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            LOGGER.exception('request_failed path=%s', self.path)
            self.respond(500, {'error': '内部处理异常'})
class DetectionServer(ThreadingHTTPServer):
    daemon_threads = False
    def __init__(self, address, service):
        self.service = service
        self.worker_slots = threading.BoundedSemaphore(8)
        super().__init__(address, RequestHandler)
    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(10)
        return connection, address
    def process_request(self, connection, address):
        if not self.worker_slots.acquire(blocking=False):
            try:
                connection.sendall(b'HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            finally:
                self.shutdown_request(connection)
            return
        try:
            super().process_request(connection, address)
        except Exception:
            self.worker_slots.release()
            raise
    def process_request_thread(self, connection, address):
        try:
            super().process_request_thread(connection, address)
        finally:
            self.worker_slots.release()
def create_server(data_dir, host='127.0.0.1', port=0):
    directory = Path(data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    repository = Repository(directory / 'residue.sqlite3')
    return DetectionServer((host, port), DetectionService(repository))
def main():
    parser = argparse.ArgumentParser(description='组织残留快检系统')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--data-dir', default=os.environ.get('RESIDUE_DATA_DIR', str(Path(tempfile.gettempdir()) / 'residue-system-v2')))
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error('port须为0至65535')
    with create_server(args.data_dir, args.host, args.port) as server:
        print('http_started host=%s port=%s' % server.server_address, flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
if __name__ == '__main__':
    main()
