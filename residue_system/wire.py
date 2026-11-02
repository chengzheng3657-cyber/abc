# 短报文编解码
import base64
import binascii
import struct
import zlib
from model import HEIGHT, WIDTH
from validation import RequestError, identifier, uint32
HEADER = struct.Struct('!4sBII8s8sB')
POINT = struct.Struct('!HHBBB')
CRC = struct.Struct('!I')
MAX_PACKET_BYTES = 80
MAX_POINTS = (MAX_PACKET_BYTES - HEADER.size - CRC.size) // POINT.size
def validate_points(points):
    if not isinstance(points, (list, tuple)) or not 2 <= len(points) <= MAX_POINTS:
        raise RequestError('采样点数量无效')
    coordinates = set()
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) != 5:
            raise RequestError('采样点格式无效')
        if any(isinstance(value, bool) or not isinstance(value, int) for value in point):
            raise RequestError('采样点必须使用整数')
        x, y, red, green, blue = point
        if not 0 <= x < WIDTH or not 0 <= y < HEIGHT or any(not 0 <= value <= 255 for value in (red, green, blue)):
            raise RequestError('采样点坐标或像素值越界')
        if (x, y) in coordinates:
            raise RequestError('采样点坐标重复')
        coordinates.add((x, y))
def encode(sample_id, timestamp, device_id, batch_id, points):
    uint32(sample_id, 'sample_id', 1)
    uint32(timestamp, 'timestamp')
    identifier(device_id, 'device_id')
    identifier(batch_id, 'batch_id')
    validate_points(points)
    header = HEADER.pack(b'ORQS', 1, sample_id, timestamp, device_id.encode('ascii'), batch_id.encode('ascii'), len(points))
    content = header + b''.join(POINT.pack(*point) for point in points)
    packet = content + CRC.pack(zlib.crc32(content))
    return base64.b64encode(packet).decode('ascii'), len(packet)
def decode(encoded):
    if not isinstance(encoded, str) or len(encoded) > 108:
        raise RequestError('报文编码无效')
    try:
        packet = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise RequestError('报文Base64格式错误') from exc
    if not HEADER.size + 2 * POINT.size + CRC.size <= len(packet) <= MAX_PACKET_BYTES:
        raise RequestError('报文长度无效')
    if base64.b64encode(packet).decode('ascii') != encoded:
        raise RequestError('报文必须使用规范Base64编码')
    content = packet[:-CRC.size]
    if zlib.crc32(content) != CRC.unpack(packet[-CRC.size:])[0]:
        raise RequestError('报文CRC校验失败')
    magic, version, sample_id, timestamp, device, batch_id, count = HEADER.unpack(content[:HEADER.size])
    if magic != b'ORQS' or version != 1 or len(content) != HEADER.size + count * POINT.size:
        raise RequestError('报文协议或采样点数量无效')
    try:
        device_id = device.rstrip(b'\0').decode('ascii')
        batch_id = batch_id.rstrip(b'\0').decode('ascii')
    except UnicodeDecodeError as exc:
        raise RequestError('报文标识编码无效') from exc
    identifier(device_id, 'device_id')
    identifier(batch_id, 'batch_id')
    uint32(sample_id, 'sample_id', 1)
    points = [POINT.unpack_from(content, HEADER.size + index * POINT.size) for index in range(count)]
    validate_points(points)
    return {'sample_id': sample_id, 'timestamp': timestamp, 'device_id': device_id, 'batch_id': batch_id, 'points': points, 'packet_bytes': len(packet)}
