# 输入校验
import json
import math
class RequestError(ValueError):
    status = 400
class ConflictError(RequestError):
    status = 409
class NotFoundError(RequestError):
    status = 404
def finite_number(value, name, lower, upper):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise RequestError(name + '必须是数值')
    try:
        valid = math.isfinite(value) and lower <= value <= upper
    except OverflowError:
        valid = False
    if not valid:
        raise RequestError(name + '超出允许范围')
    return float(value)
def uint32(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= 0xFFFFFFFF:
        raise RequestError(name + '必须是有效的32位整数')
    return value
def identifier(value, name):
    if not isinstance(value, str) or not 1 <= len(value) <= 8 or not value.isascii():
        raise RequestError(name + '须为1至8位ASCII标识')
    if not all(character.isalnum() or character in '_-' for character in value):
        raise RequestError(name + '包含无效字符')
    return value
def reject_constant(value):
    raise RequestError('JSON不允许非有限数值：' + value)
def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RequestError('JSON包含重复字段：' + key)
        result[key] = value
    return result
def load_json(data):
    return json.loads(data, parse_constant=reject_constant, object_pairs_hook=unique_object)
