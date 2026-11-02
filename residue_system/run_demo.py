# 本地模拟检测
import argparse
import base64
import json
import tempfile
import time
from pathlib import Path
from demo_client import run
from runtime import running_server
def main():
    parser = argparse.ArgumentParser(description='通过HTTP端口执行模拟检测')
    parser.add_argument('--output-dir', default=str(Path(tempfile.gettempdir()) / 'residue-demo-v2'))
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    # 接收报告后由客户端保存，服务端不直接写客户端输出文件
    with running_server(output / 'data') as base:
        _, _, report, summary = run(base, int(time.time()) & 0xFFFFFFFF)
        if report['status'] != 'valid':
            raise RuntimeError('模拟样本未通过质量检查')
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        (output / 'reconstruction.ppm').write_bytes(base64.b64decode(report['reconstruction']['base64'], validate=True))
    print('simulation_completed output_dir=' + str(output), flush=True)
if __name__ == '__main__':
    main()
