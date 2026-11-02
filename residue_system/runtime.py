# 本地服务运行器
import threading
from contextlib import contextmanager
from server import create_server
@contextmanager
def running_server(data_dir):
    with create_server(data_dir) as server:
        worker = threading.Thread(target=server.serve_forever, name='residue-http')
        worker.start()
        try:
            yield 'http://127.0.0.1:%s' % server.server_port
        finally:
            server.shutdown()
            worker.join(timeout=15)
            if worker.is_alive():
                raise RuntimeError('HTTP服务未能正常关闭')
