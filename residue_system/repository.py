# 检测数据存储
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from model import BatchCalibration
from validation import ConflictError, NotFoundError
def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
def content_digest(value):
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()
class Repository:
    def __init__(self, path):
        self.path = str(path)
        with self.connection() as database:
            legacy = database.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='batches'").fetchone()
            versioned = database.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'").fetchone()
            if legacy is not None and versioned is None:
                raise RuntimeError('旧版数据库不可直接加载，请保留原库并指定新的数据目录')
            database.execute('PRAGMA journal_mode=WAL')
            database.execute('CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)')
            row = database.execute('SELECT version FROM schema_version').fetchone()
            if row is not None and row[0] != 2:
                raise RuntimeError('数据库版本不兼容')
            database.execute('INSERT OR IGNORE INTO schema_version VALUES (2)')
            database.execute('CREATE TABLE IF NOT EXISTS batches (batch_id TEXT PRIMARY KEY, config TEXT NOT NULL, evidence TEXT NOT NULL)')
            database.execute('CREATE TABLE IF NOT EXISTS captures (device TEXT, sample INTEGER, fingerprint TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(device,sample))')
            database.execute('CREATE TABLE IF NOT EXISTS reports (device TEXT, sample INTEGER, fingerprint TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(device,sample))')
    @contextmanager
    def connection(self):
        database = sqlite3.connect(self.path, timeout=10)
        try:
            with database:
                yield database
        finally:
            database.close()
    def batch(self, batch_id):
        with self.connection() as database:
            row = database.execute('SELECT config FROM batches WHERE batch_id=?', (batch_id,)).fetchone()
        if row is None:
            raise NotFoundError('批次不存在，请先上传标定数据')
        return BatchCalibration(**json.loads(row[0]))
    def add_batch(self, batch, evidence):
        config = canonical_json(batch.to_dict())
        evidence_json = canonical_json(evidence)
        with self.connection() as database:
            database.execute('BEGIN IMMEDIATE')
            existing = database.execute('SELECT config,evidence FROM batches WHERE batch_id=?', (batch.batch_id,)).fetchone()
            if existing is not None and existing != (config, evidence_json):
                raise ConflictError('批次已锁定，请使用新的批次标识')
            database.execute('INSERT OR IGNORE INTO batches VALUES (?,?,?)', (batch.batch_id, config, evidence_json))
    def get(self, table, device, sample, digest=None):
        if table not in ('captures', 'reports'):
            raise ValueError('未知数据表')
        with self.connection() as database:
            row = database.execute('SELECT fingerprint,data FROM ' + table + ' WHERE device=? AND sample=?', (device, sample)).fetchone()
        if row is None:
            return None
        if digest is not None and row[0] != digest:
            raise ConflictError('同一设备和样本编号已关联不同数据')
        return json.loads(row[1])
    def save(self, table, device, sample, digest, data):
        if table not in ('captures', 'reports'):
            raise ValueError('未知数据表')
        with self.connection() as database:
            database.execute('BEGIN IMMEDIATE')
            existing = database.execute('SELECT fingerprint,data FROM ' + table + ' WHERE device=? AND sample=?', (device, sample)).fetchone()
            if existing is not None:
                if existing[0] != digest:
                    raise ConflictError('同一设备和样本编号已关联不同数据')
                return json.loads(existing[1])
            if table == 'captures':
                report_row = database.execute('SELECT fingerprint FROM reports WHERE device=? AND sample=?', (device, sample)).fetchone()
                packet_digest = content_digest(data['response']['packet_base64'])
                if report_row is not None and report_row[0] != packet_digest:
                    raise ConflictError('已有报告对应其他报文，无法关联采集数据')
            else:
                capture_row = database.execute('SELECT data FROM captures WHERE device=? AND sample=?', (device, sample)).fetchone()
                if capture_row is not None:
                    capture = json.loads(capture_row[0])
                    if content_digest(capture['response']['packet_base64']) != digest:
                        raise ConflictError('报文与已有采集数据不一致')
            database.execute('INSERT INTO ' + table + ' VALUES (?,?,?,?)', (device, sample, digest, canonical_json(data)))
        return data
