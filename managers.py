import os
import pickle
import hashlib
import cv2
import numpy as np
from sklearn.neighbors import NearestNeighbors
import configparser
import asyncio
import concurrent.futures
import sqlite3
from datetime import datetime
import threading
import uuid
import json
import time
import logging
import requests
import base64
try:
    import pymysql
except ImportError:
    pymysql = None
    raise ImportError("缺失pymysql库，请使用pip install pymysql安装库，再次运行程序")

try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet = None
    raise ImportError("缺失cryptography库，请使用pip install cryptography安装库，再次运行程序")
try:
    import psutil
    import platform
    import socket
    import uuid
except ImportError:
    psutil = None
    raise ImportError("缺失psutil库，请使用pip install psutil安装库，再次运行程序")

# Configure basic logging to console first
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DatabaseLogHandler(logging.Handler):
    """Custom logging handler to write logs to database"""
    def __init__(self, db_manager):
        super().__init__()
        self.db_manager = db_manager

    def emit(self, record):
        try:
            # Format message
            msg = self.format(record)
            
            # Avoid recursion: don't log if the message comes from within db_manager's logging
            # This is tricky.
            # We should probably filter out logs from 'managers' if they are about DB operations?
            # Or just catch exceptions in add_system_log and not log them?
            
            # Use module name as module
            module = record.name
            
            self.db_manager.add_system_log(
                level=record.levelname,
                message=msg,
                module=module
            )
        except Exception:
            self.handleError(record)

def mkdir_if_not_exists(path):
    if not os.path.exists(path):
        os.makedirs(path)

class ConfigManager:
    def __init__(self, config_path="config.ini"):
        # Use absolute path relative to the script
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_path = os.path.join(base_dir, config_path)
        self.config = configparser.ConfigParser()
        if not os.path.exists(self.config_path):
            self.create_default_config()
        self.config.read(self.config_path, encoding='utf-8')

    def create_default_config(self):
        self.config['General'] = {'Mode': 'Test', 'StartMode': 'Sync'}
        with open(self.config_path, 'w', encoding='utf-8') as f:
            self.config.write(f)

    def get_sync_interval(self):
        self.config.read(self.config_path, encoding='utf-8')
        return self.config.getint('General', 'SyncInterval', fallback=30)
        
    def set_sync_interval(self, interval):
        if 'General' not in self.config:
            self.config['General'] = {}
        self.config['General']['SyncInterval'] = str(interval)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            self.config.write(f)

    def get_templates(self):
        """Get parsed template definitions"""
        self.config.read(self.config_path, encoding='utf-8')
        if 'Templates' not in self.config:
            return {}
        
        templates = {}
        for key, value in self.config['Templates'].items():
            fields = []
            # Format: field_name:type:label:required, ...
            for field_def in value.split(','):
                parts = field_def.strip().split(':')
                if len(parts) >= 3:
                    field = {
                        'name': parts[0].strip(),
                        'type': parts[1].strip(),
                        'label': parts[2].strip(),
                        'required': parts[3].strip().lower() == 'true' if len(parts) > 3 else False
                    }
                    fields.append(field)
            templates[key] = fields
        return templates

    def get_enums(self):
        """Get enum definitions"""
        self.config.read(self.config_path, encoding='utf-8')
        if 'Enums' not in self.config:
            return {}
        
        enums = {}
        for key, value in self.config['Enums'].items():
            enums[key] = [v.strip() for v in value.split(',')]
        return enums

    def update_enum(self, key, values):
        """Update enum values"""
        if 'Enums' not in self.config:
            self.config['Enums'] = {}
        
        if isinstance(values, list):
            self.config['Enums'][key] = ','.join(values)
        else:
            self.config['Enums'][key] = str(values)
            
        with open(self.config_path, 'w', encoding='utf-8') as f:
            self.config.write(f)

    def get_mode(self):
        self.config.read(self.config_path, encoding='utf-8')
        return self.config.get('General', 'Mode', fallback='Test')

    def set_mode(self, mode):
        if 'General' not in self.config:
            self.config['General'] = {}
        self.config['General']['Mode'] = mode
        self.config['General']['ConfigUpdatedAt'] = str(datetime.now().timestamp())
        with open(self.config_path, 'w', encoding='utf-8') as f:
            self.config.write(f)

    def get_network_mode(self):
        self.config.read(self.config_path, encoding='utf-8')
        return self.config.get('General', 'NetworkMode', fallback='Online')

    def set_network_mode(self, mode):
        if 'General' not in self.config:
            self.config['General'] = {}
        self.config['General']['NetworkMode'] = mode
        self.config['General']['ConfigUpdatedAt'] = str(datetime.now().timestamp())
        with open(self.config_path, 'w', encoding='utf-8') as f:
            self.config.write(f)

    def get_start_mode(self):
        self.config.read(self.config_path, encoding='utf-8')
        return self.config.get('General', 'StartMode', fallback='Sync')

    def set_start_mode(self, mode):
        if 'General' not in self.config:
            self.config['General'] = {}
        self.config['General']['StartMode'] = mode
        self.config['General']['ConfigUpdatedAt'] = str(datetime.now().timestamp())
        with open(self.config_path, 'w', encoding='utf-8') as f:
            self.config.write(f)

    def get_config_updated_at(self):
        self.config.read(self.config_path, encoding='utf-8')
        return float(self.config.get('General', 'ConfigUpdatedAt', fallback='0'))
    
    def set_config_updated_at(self, timestamp):
        if 'General' not in self.config:
            self.config['General'] = {}
        self.config['General']['ConfigUpdatedAt'] = str(timestamp)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            self.config.write(f)

    def get_mysql_config(self):
        self.config.read(self.config_path, encoding='utf-8')
        return {
            'host': self.config.get('MySQL', 'Host', fallback='localhost'),
            'user': self.config.get('MySQL', 'User', fallback='root'),
            'password': self.config.get('MySQL', 'Password', fallback=''),
            'database': self.config.get('MySQL', 'Database', fallback='face_recognition'),
            'port': self.config.getint('MySQL', 'Port', fallback=3306)
        }

    def set_mysql_config(self, host, user, password, database, port=3306):
        if 'MySQL' not in self.config:
            self.config['MySQL'] = {}
        self.config['MySQL']['Host'] = host
        self.config['MySQL']['User'] = user
        self.config['MySQL']['Password'] = password
        self.config['MySQL']['Database'] = database
        self.config['MySQL']['Port'] = str(port)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            self.config.write(f)

    def get_web_admin_config(self):
        self.config.read(self.config_path, encoding='utf-8')
        return {
            'host': self.config.get('WebAdmin', 'Host', fallback='localhost'),
            'port': self.config.getint('WebAdmin', 'Port', fallback=5000),
            'token': self.config.get('WebAdmin', 'Token', fallback=''),
            'salt': self.config.get('WebAdmin', 'Salt', fallback='')
        }

    def set_web_admin_config(self, host, port=5000, token=None, salt=None):
        if 'WebAdmin' not in self.config:
            self.config['WebAdmin'] = {}
        self.config['WebAdmin']['Host'] = host
        self.config['WebAdmin']['Port'] = str(port)
        if token:
            self.config['WebAdmin']['Token'] = token
        if salt:
            self.config['WebAdmin']['Salt'] = salt
        with open(self.config_path, 'w', encoding='utf-8') as f:
            self.config.write(f)

    def get_encryption_key(self):
        self.config.read(self.config_path, encoding='utf-8')
        key = self.config.get('Security', 'EncryptionKey', fallback=None)
        if not key:
            if Fernet:
                key = Fernet.generate_key().decode()
                if 'Security' not in self.config:
                    self.config['Security'] = {}
                self.config['Security']['EncryptionKey'] = key
                with open(self.config_path, 'w', encoding='utf-8') as f:
                    self.config.write(f)
            else:
                logger.warning("Cryptography not installed, using plain text fallback")
                return None
        return key.encode() if key else None

class DatabaseManagerBase:
    def __init__(self, database_path="./dd/face_database.pkl", sqlite_path="./dd/records.db"):
        self.database_path = database_path
        self.sqlite_path = sqlite_path
        self.config_manager = ConfigManager()
        mkdir_if_not_exists("./picture")
        mkdir_if_not_exists("./face_images")
        self.face_images_dir = "./face_images"
        
        # Initialize SQLite database
        self.init_sqlite_db()
        
        # Initialize MySQL database (if configured)
        try:
            self.init_mysql_db()
        except Exception as e:
            logger.error(f"MySQL initialization failed: {e}")

    def init_sqlite_db(self):
        """Initialize SQLite database tables and add new columns if missing"""
        conn = sqlite3.connect(self.sqlite_path)
        cursor = conn.cursor()
        
        # Helper to add column if not exists
        def add_column_if_not_exists(table, column, definition):
            try:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                logger.info(f"Added column {column} to {table}")
            except sqlite3.OperationalError:
                pass  # Column already exists

        # Check if device_info is compatible, if not drop it
        cursor.execute("PRAGMA table_info(device_info)")
        columns = [info[1] for info in cursor.fetchall()]
        if columns and 'device_id' not in columns:
            logger.warning("Incompatible device_info table found, dropping it...")
            cursor.execute("DROP TABLE device_info")

        # Device Info Table (Extended)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS device_info (
            device_id TEXT PRIMARY KEY,
            machine_code TEXT UNIQUE,
            model TEXT,
            location TEXT,
            registered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            
            -- Basic Info
            serial_number TEXT,
            manufacturer TEXT,
            production_date TEXT,
            
            -- Network
            ip_address TEXT,
            mac_address TEXT,
            network_interface TEXT,
            
            -- Detailed Location
            geo_coords TEXT,
            deployment_location TEXT,
            site_name TEXT,
            install_address TEXT,
            
            -- Hardware
            processor_info TEXT,
            memory_capacity TEXT,
            storage_info TEXT,
            expansion_slots TEXT,
            
            -- Status
            firmware_version TEXT,
            power_status TEXT,
            sensor_data TEXT,
            battery_status TEXT,
            
            -- Other
            device_type TEXT,
            department TEXT,
            maintenance_record TEXT,
            protocol_type TEXT,
            
            -- Software Metadata
            software_name TEXT,
            software_version TEXT,
            software_uuid TEXT,
            software_description TEXT,
            software_vendor TEXT,
            os_compatibility TEXT,
            arch TEXT,
            license_type TEXT,
            copyright_info TEXT,
            eula_url TEXT,
            build_time TEXT,
            repo_url TEXT,
            checksum TEXT,
            install_path TEXT,
            pid TEXT,
            start_time TEXT,
            runtime_duration TEXT,
            resource_usage TEXT,
            run_status TEXT,
            vuln_scan_result TEXT,
            patch_level TEXT,
            digital_signature TEXT
        )
        ''')
        
        # Add new columns if missing (for migration)
        new_columns = [
            'serial_number', 'manufacturer', 'production_date',
            'ip_address', 'mac_address', 'network_interface',
            'geo_coords', 'deployment_location', 'site_name', 'install_address',
            'processor_info', 'memory_capacity', 'storage_info', 'expansion_slots',
            'firmware_version', 'power_status', 'sensor_data', 'battery_status',
            'device_type', 'department', 'maintenance_record', 'protocol_type',
            'software_name', 'software_version', 'software_uuid', 'software_description', 'software_vendor',
            'os_compatibility', 'arch', 'license_type', 'copyright_info', 'eula_url',
            'build_time', 'repo_url', 'checksum', 'install_path',
            'pid', 'start_time', 'runtime_duration', 'resource_usage', 'run_status',
            'vuln_scan_result', 'patch_level', 'digital_signature'
        ]
        
        for col in new_columns:
            add_column_if_not_exists('device_info', col, 'TEXT')

        # Initialize Device ID
        self.device_id = self.get_or_create_device_id(cursor)

        # Attendance Record Table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT,
            remarks TEXT,
            device_id TEXT,
            sync_status TEXT DEFAULT 'pending',
            sync_timestamp DATETIME
        )
        ''')
        add_column_if_not_exists('attendance_records', 'device_id', 'TEXT')
        add_column_if_not_exists('attendance_records', 'sync_status', "TEXT DEFAULT 'pending'")
        add_column_if_not_exists('attendance_records', 'sync_timestamp', 'DATETIME')
        add_column_if_not_exists('attendance_records', 'remarks', 'TEXT')

        # Access Control Record Table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS access_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            direction TEXT,
            status TEXT,
            remarks TEXT,
            device_id TEXT,
            sync_status TEXT DEFAULT 'pending',
            sync_timestamp DATETIME
        )
        ''')
        add_column_if_not_exists('access_records', 'device_id', 'TEXT')
        add_column_if_not_exists('access_records', 'sync_status', "TEXT DEFAULT 'pending'")
        add_column_if_not_exists('access_records', 'sync_timestamp', 'DATETIME')
        add_column_if_not_exists('access_records', 'remarks', 'TEXT')
        
        # System Log Table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS system_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            level TEXT,
            message TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            module TEXT,
            device_id TEXT,
            sync_status TEXT DEFAULT 'pending',
            sync_timestamp DATETIME
        )
        ''')
        add_column_if_not_exists('system_logs', 'device_id', 'TEXT')
        add_column_if_not_exists('system_logs', 'sync_status', "TEXT DEFAULT 'pending'")
        add_column_if_not_exists('system_logs', 'sync_timestamp', 'DATETIME')

        # Admin Log Table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_name TEXT,
            action TEXT,
            target TEXT,
            details TEXT,
            sensitivity TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            device_id TEXT,
            sync_status TEXT DEFAULT 'pending',
            sync_timestamp DATETIME
        )
        ''')
        add_column_if_not_exists('admin_logs', 'device_id', 'TEXT')
        add_column_if_not_exists('admin_logs', 'sync_status', "TEXT DEFAULT 'pending'")
        add_column_if_not_exists('admin_logs', 'sync_timestamp', 'DATETIME')

        # Faces Table (Encrypted)
        cursor.execute("PRAGMA table_info(faces)")
        columns = [info[1] for info in cursor.fetchall()]
        if columns and 'id' not in columns:
            logger.info("Migrating faces table to support multi-device per user...")
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS faces_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_name TEXT,
                embedding BLOB,
                groups TEXT DEFAULT 'all',
                list_type TEXT DEFAULT 'white',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT DEFAULT '{}',
                sync_status TEXT DEFAULT 'pending',
                device_id TEXT DEFAULT 'admin',
                UNIQUE(user_name, device_id)
            )
            ''')
            cursor.execute("INSERT OR IGNORE INTO faces_new (user_name, embedding, groups, list_type, created_at, metadata, sync_status, device_id) SELECT user_name, embedding, groups, list_type, created_at, metadata, sync_status, device_id FROM faces")
            cursor.execute("DROP TABLE faces")
            cursor.execute("ALTER TABLE faces_new RENAME TO faces")
            
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS faces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name TEXT,
            embedding BLOB,
            groups TEXT DEFAULT 'all',
            list_type TEXT DEFAULT 'white',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            metadata TEXT DEFAULT '{}',
            sync_status TEXT DEFAULT 'pending',
            device_id TEXT DEFAULT 'admin',
            UNIQUE(user_name, device_id)
        )
        ''')
        add_column_if_not_exists('faces', 'groups', "TEXT DEFAULT 'all'")
        add_column_if_not_exists('faces', 'list_type', "TEXT DEFAULT 'white'")
        add_column_if_not_exists('faces', 'metadata', "TEXT DEFAULT '{}'")
        add_column_if_not_exists('faces', 'sync_status', "TEXT DEFAULT 'pending'")
        add_column_if_not_exists('faces', 'device_id', "TEXT DEFAULT 'admin'")

        # Admins Table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            user_name TEXT PRIMARY KEY,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        conn.commit()
        conn.close()

    def get_or_create_device_id(self, cursor):
        cursor.execute("SELECT device_id FROM device_info LIMIT 1")
        row = cursor.fetchone()
        if row:
            return row[0]
        else:
            new_id = str(uuid.uuid4())
            machine_code = str(uuid.uuid1()) # MAC address based
            cursor.execute("INSERT INTO device_info (device_id, machine_code) VALUES (?, ?)", (new_id, machine_code))
            return new_id

    def get_device_info(self):
        """Get device information (id, machine_code, registered_at)"""
        with sqlite3.connect(self.sqlite_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT device_id, machine_code, registered_at FROM device_info LIMIT 1")
            row = cursor.fetchone()
            if row:
                return {
                    'device_id': row[0],
                    'machine_code': row[1],
                    'registered_at': row[2]
                }
            return None

    def init_mysql_db(self):
        """Initialize MySQL database tables"""
        if not pymysql:
            logger.warning("pymysql not installed, skipping MySQL init")
            return
            
        if self.config_manager.get_network_mode() == 'Offline':
            logger.info("Network mode is Offline, skipping MySQL init")
            return

        config = self.config_manager.get_mysql_config()
        try:
            # Connect to MySQL Server (without DB first) to create DB
            conn = pymysql.connect(
                host=config['host'],
                user=config['user'],
                password=config['password'],
                port=config['port'],
                connect_timeout=3
            )
            cursor = conn.cursor()
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {config['database']}")
            conn.close()

            # Connect to specific DB
            conn = self.get_mysql_connection()
            if not conn:
                return
            cursor = conn.cursor()

            # Device Info Table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS device_info (
                device_id VARCHAR(36) PRIMARY KEY,
                machine_code VARCHAR(36) UNIQUE,
                model VARCHAR(100),
                location VARCHAR(100),
                registered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                
                -- Extended Metadata (Using JSON for flexibility or separate columns)
                -- Let's use columns to match SQLite structure
                serial_number VARCHAR(100), manufacturer VARCHAR(100), production_date VARCHAR(50),
                ip_address VARCHAR(50), mac_address VARCHAR(50), network_interface VARCHAR(50),
                geo_coords VARCHAR(100), deployment_location VARCHAR(100), site_name VARCHAR(100), install_address TEXT,
                processor_info VARCHAR(200), memory_capacity VARCHAR(50), storage_info VARCHAR(200), expansion_slots VARCHAR(200),
                firmware_version VARCHAR(255), power_status VARCHAR(50), sensor_data TEXT, battery_status VARCHAR(100),
                device_type VARCHAR(50), department VARCHAR(100), maintenance_record TEXT, protocol_type VARCHAR(50),
                
                software_name VARCHAR(100), software_version VARCHAR(50), software_uuid VARCHAR(100), 
                software_description TEXT, software_vendor VARCHAR(100), os_compatibility VARCHAR(100), arch VARCHAR(20),
                license_type VARCHAR(50), copyright_info VARCHAR(200), eula_url VARCHAR(255),
                build_time VARCHAR(50), repo_url VARCHAR(255), checksum VARCHAR(100), install_path VARCHAR(255),
                pid VARCHAR(20), start_time VARCHAR(50), runtime_duration VARCHAR(50), resource_usage TEXT, run_status VARCHAR(50),
                vuln_scan_result TEXT, patch_level VARCHAR(50), digital_signature TEXT
            )
            ''')
            
            # Add columns if missing in MySQL (Simple check)
            try:
                cursor.execute("SHOW COLUMNS FROM device_info LIKE 'serial_number'")
                if not cursor.fetchone():
                    alter_sql = """
                    ALTER TABLE device_info
                    ADD COLUMN serial_number VARCHAR(100), ADD COLUMN manufacturer VARCHAR(100), ADD COLUMN production_date VARCHAR(50),
                    ADD COLUMN ip_address VARCHAR(50), ADD COLUMN mac_address VARCHAR(50), ADD COLUMN network_interface VARCHAR(50),
                    ADD COLUMN geo_coords VARCHAR(100), ADD COLUMN deployment_location VARCHAR(100), ADD COLUMN site_name VARCHAR(100), ADD COLUMN install_address TEXT,
                    ADD COLUMN processor_info VARCHAR(200), ADD COLUMN memory_capacity VARCHAR(50), ADD COLUMN storage_info VARCHAR(200), ADD COLUMN expansion_slots VARCHAR(200),
                    ADD COLUMN firmware_version VARCHAR(255), ADD COLUMN power_status VARCHAR(50), ADD COLUMN sensor_data TEXT, ADD COLUMN battery_status VARCHAR(100),
                    ADD COLUMN device_type VARCHAR(50), ADD COLUMN department VARCHAR(100), ADD COLUMN maintenance_record TEXT, ADD COLUMN protocol_type VARCHAR(50),
                    ADD COLUMN software_name VARCHAR(100), ADD COLUMN software_version VARCHAR(50), ADD COLUMN software_uuid VARCHAR(100),
                    ADD COLUMN software_description TEXT, ADD COLUMN software_vendor VARCHAR(100), ADD COLUMN os_compatibility VARCHAR(100), ADD COLUMN arch VARCHAR(20),
                    ADD COLUMN license_type VARCHAR(50), ADD COLUMN copyright_info VARCHAR(200), ADD COLUMN eula_url VARCHAR(255),
                    ADD COLUMN build_time VARCHAR(50), ADD COLUMN repo_url VARCHAR(255), ADD COLUMN checksum VARCHAR(100), ADD COLUMN install_path VARCHAR(255),
                    ADD COLUMN pid VARCHAR(20), ADD COLUMN start_time VARCHAR(50), ADD COLUMN runtime_duration VARCHAR(50), ADD COLUMN resource_usage TEXT, ADD COLUMN run_status VARCHAR(50),
                    ADD COLUMN vuln_scan_result TEXT, ADD COLUMN patch_level VARCHAR(50), ADD COLUMN digital_signature TEXT
                    """
                    cursor.execute(alter_sql)
                    
                # Check for business_mode and startup_mode
                cursor.execute("SHOW COLUMNS FROM device_info LIKE 'business_mode'")
                if not cursor.fetchone():
                    cursor.execute("ALTER TABLE device_info ADD COLUMN business_mode VARCHAR(50) DEFAULT 'Test', ADD COLUMN startup_mode VARCHAR(50) DEFAULT 'Sync', ADD COLUMN config_updated_at DOUBLE DEFAULT 0")

                # Ensure firmware_version is large enough
                cursor.execute("ALTER TABLE device_info MODIFY COLUMN firmware_version VARCHAR(255)")

            except Exception as e:
                logger.warning(f"Failed to alter MySQL table: {e}")

            # Register current device if not exists
            try:
                cursor.execute("INSERT IGNORE INTO device_info (device_id, machine_code, registered_at) VALUES (%s, %s, %s)",
                               (self.device_id, str(uuid.uuid1()), datetime.now()))
                conn.commit()
            except Exception as e:
                logger.error(f"Failed to register device in MySQL: {e}")

            # Attendance Record Table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS attendance_records (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_name VARCHAR(100) NOT NULL,
                timestamp DATETIME,
                status VARCHAR(50),
                remark TEXT,
                device_id VARCHAR(36),
                sync_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY unique_record (device_id, timestamp, user_name)
            )
            ''')

            # Access Control Record Table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS access_records (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_name VARCHAR(100) NOT NULL,
                timestamp DATETIME,
                direction VARCHAR(10),
                status VARCHAR(50),
                remark TEXT,
                device_id VARCHAR(36),
                sync_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY unique_access (device_id, timestamp, user_name)
            )
            ''')

            # System Log Table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_logs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                level VARCHAR(20),
                message TEXT,
                timestamp DATETIME,
                module VARCHAR(50),
                device_id VARCHAR(36),
                sync_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            ''')

            # Admin Log Table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                admin_name VARCHAR(100),
                action VARCHAR(100),
                target VARCHAR(100),
                details TEXT,
                sensitivity VARCHAR(20),
                timestamp DATETIME,
                device_id VARCHAR(36),
                sync_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            ''')

            conn.commit()
            conn.close()
            logger.info("MySQL database initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize MySQL: {e}")

    def get_mysql_connection(self):
        if not pymysql:
            return None
        if self.config_manager.get_network_mode() == 'Offline':
            return None
            
        config = self.config_manager.get_mysql_config()
        try:
            return pymysql.connect(
                host=config['host'],
                user=config['user'],
                password=config['password'],
                database=config['database'],
                port=config['port'],
                connect_timeout=3, # 短超时防止阻塞
                cursorclass=pymysql.cursors.DictCursor
            )
        except Exception as e:
            logger.error(f"Failed to connect to MySQL: {e}")
            return None

    def get_all_devices(self):
        """Get all registered devices from MySQL"""
        if not pymysql:
            return []
        conn = self.get_mysql_connection()
        if not conn:
            return []
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT device_id, machine_code, last_seen, registered_at FROM device_info ORDER BY last_seen DESC")
                devices = cursor.fetchall()
            
            # Format as dict
            result = []
            now = datetime.now()
            for dev in devices:
                last_seen = dev.get('last_seen')
                is_online = False
                if last_seen:
                    # If last seen within 90 seconds (allowing 60s sync interval + margin), consider online
                    diff = now - last_seen
                    if diff.total_seconds() < 90:
                        is_online = True
                        
                result.append({
                    'device_id': dev.get('device_id'),
                    'machine_code': dev.get('machine_code'),
                    'last_seen': last_seen,
                    'registered_at': dev.get('registered_at'),
                    'is_online': is_online
                })
            return result
        except Exception as e:
            logger.error(f"Failed to get devices from MySQL: {e}")
            return []
        finally:
            conn.close()

    def get_statistics(self, start_date=None, end_date=None, device_id=None):
        """Aggregate statistics for dashboard with optional date and device filtering"""
        from datetime import datetime, timedelta
        
        # Default to today if no date provided for trend charts, 
        # but for totals we usually count everything unless specified.
        # Actually, user stats are current state (snapshot), record stats are historical.
        
        stats = {
            'user': {},
            'attendance': {},
            'access': {},
            'system': {}
        }
        
        # User Stats (Snapshot, not affected by date range usually, unless we track registration date)
        # But user requested to fix the counting logic for 'all' groups.
        all_users = getattr(self, 'database', {})
        
        # If device_id is provided, filter all_users
        if device_id and device_id != 'all':
            filtered_users = {}
            for name, faces in all_users.items():
                if not isinstance(faces, list):
                    faces = [faces]
                # Check if any face belongs to the device
                if any(f.get('device_id') == device_id for f in faces):
                    filtered_users[name] = faces
            all_users = filtered_users

        stats['user']['total'] = len(all_users)
        
        # Fix: 'all' means both attendance and access
        def check_group(user_data, group_name):
            if not isinstance(user_data, dict):
                # If it's a list (from filtered_users or newer schema), check all faces
                if isinstance(user_data, list):
                    return any(f.get('groups', 'all') == 'all' or group_name in f.get('groups', 'all').split(',') for f in user_data)
                return True # Legacy data is 'all'
            groups = user_data.get('groups', 'all')
            return groups == 'all' or group_name in groups.split(',')

        stats['user']['attendance'] = sum(1 for u in all_users.values() if check_group(u, 'attendance'))
        stats['user']['access'] = sum(1 for u in all_users.values() if check_group(u, 'access'))
        
        # For has_image, we need to pass device_id if it's set
        if device_id and device_id != 'all':
            has_image_count = sum(1 for n in all_users.keys() if self.check_face_image_exists(n, device_id))
        else:
            has_image_count = sum(1 for n in all_users.keys() if self.check_face_image_exists(n))
            
        stats['user']['has_image'] = has_image_count
        stats['user']['missing_image'] = stats['user']['total'] - has_image_count
        
        # Helper for date filtering in SQL
        date_filter_sql = ""
        params = []
        
        use_mysql = False
        if pymysql:
            conn = self.get_mysql_connection()
            if conn:
                use_mysql = True
                
        if not use_mysql:
            conn = sqlite3.connect(self.sqlite_path)
            
        cursor = conn.cursor()
        
        conditions = []
        if start_date and end_date:
            conditions.append("timestamp BETWEEN %s AND %s" if use_mysql else "timestamp BETWEEN ? AND ?")
            params.extend([start_date, end_date])
        elif start_date:
            conditions.append("timestamp >= %s" if use_mysql else "timestamp >= ?")
            params.append(start_date)
            
        if device_id and device_id != 'all':
            conditions.append("device_id = %s" if use_mysql else "device_id = ?")
            params.append(device_id)
            
        if conditions:
            date_filter_sql = " WHERE " + " AND ".join(conditions)

        # Helper for trend date filtering
        def get_trend_where_clause(date_condition, date_val):
            trend_conditions = [date_condition]
            trend_params = [date_val]
            if device_id and device_id != 'all':
                trend_conditions.append("device_id = %s" if use_mysql else "device_id = ?")
                trend_params.append(device_id)
            return " WHERE " + " AND ".join(trend_conditions), trend_params

        # Attendance Stats
        try:
            
            # Daily Attendance Count (Trend)
            # If date range provided, use it. Else default to last 7 days.
            if start_date and end_date:
                 # Generate list of dates in range
                 s = datetime.strptime(start_date, '%Y-%m-%d %H:%M:%S')
                 e = datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S')
                 delta = e - s
                 
                 # If range > 31 days (like a year), group by month
                 if delta.days > 31:
                     # Generate months list
                     dates = []
                     curr = s
                     while curr <= e:
                         dates.append(curr.strftime('%Y-%m'))
                         # Move to next month
                         if curr.month == 12:
                             curr = curr.replace(year=curr.year + 1, month=1, day=1)
                         else:
                             curr = curr.replace(month=curr.month + 1, day=1)
                             
                     daily_counts = []
                     for date_str in dates:
                         if use_mysql:
                             where_sql, trend_params = get_trend_where_clause("DATE_FORMAT(timestamp, '%%Y-%%m') = %s", date_str)
                             cursor.execute(f"SELECT COUNT(*) FROM attendance_records {where_sql}", trend_params)
                         else:
                             where_sql, trend_params = get_trend_where_clause("strftime('%Y-%m', timestamp) = ?", date_str)
                             cursor.execute(f"SELECT COUNT(*) FROM attendance_records {where_sql}", trend_params)
                         row = cursor.fetchone()
                         val = list(row.values())[0] if use_mysql and isinstance(row, dict) and row else (row[0] if row else 0)
                         daily_counts.append(val)
                     stats['attendance']['daily_trend'] = {'dates': dates, 'counts': daily_counts}
                     
                 else:
                     dates = [(s + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(delta.days + 1)]
                     daily_counts = []
                     for date in dates:
                         if use_mysql:
                             where_sql, trend_params = get_trend_where_clause("DATE(timestamp) = %s", date)
                             cursor.execute(f"SELECT COUNT(*) FROM attendance_records {where_sql}", trend_params)
                         else:
                             where_sql, trend_params = get_trend_where_clause("date(timestamp) = ?", date)
                             cursor.execute(f"SELECT COUNT(*) FROM attendance_records {where_sql}", trend_params)
                         row = cursor.fetchone()
                         val = list(row.values())[0] if use_mysql and isinstance(row, dict) and row else (row[0] if row else 0)
                         daily_counts.append(val)
                     stats['attendance']['daily_trend'] = {'dates': dates, 'counts': daily_counts}
            else:
                 today = datetime.now().date()
                 dates = [(today - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(6, -1, -1)]
                 
                 daily_counts = []
                 for date in dates:
                     if use_mysql:
                         where_sql, trend_params = get_trend_where_clause("DATE(timestamp) = %s", date)
                         cursor.execute(f"SELECT COUNT(*) FROM attendance_records {where_sql}", trend_params)
                     else:
                         where_sql, trend_params = get_trend_where_clause("date(timestamp) = ?", date)
                         cursor.execute(f"SELECT COUNT(*) FROM attendance_records {where_sql}", trend_params)
                     row = cursor.fetchone()
                     val = list(row.values())[0] if use_mysql and isinstance(row, dict) and row else (row[0] if row else 0)
                     daily_counts.append(val)
                 stats['attendance']['daily_trend'] = {'dates': dates, 'counts': daily_counts}

            # Access Stats with Filter
            cursor.execute(f"SELECT COUNT(*) FROM access_records {date_filter_sql}", params)
            row = cursor.fetchone()
            stats['access']['total_pass'] = list(row.values())[0] if use_mysql and isinstance(row, dict) and row else (row[0] if row else 0)

            # Access Status Distribution
            if date_filter_sql:
                 cursor.execute(f"SELECT status, COUNT(*) FROM access_records {date_filter_sql} GROUP BY status", params)
            else:
                 cursor.execute("SELECT status, COUNT(*) FROM access_records GROUP BY status")

            if use_mysql and isinstance(cursor, pymysql.cursors.DictCursor):
                access_status = {list(r.values())[0]: list(r.values())[1] for r in cursor.fetchall()}
            else:
                access_status = dict(cursor.fetchall())
                
            stats['access']['allowed'] = access_status.get('Allowed', 0)
            stats['access']['denied'] = access_status.get('Denied', 0) + access_status.get('Denied-Blacklist', 0)

            # System Stats
            system_conditions = ["level='ERROR'"]
            if start_date and end_date:
                system_conditions.append("timestamp BETWEEN %s AND %s" if use_mysql else "timestamp BETWEEN ? AND ?")
            elif start_date:
                system_conditions.append("timestamp >= %s" if use_mysql else "timestamp >= ?")
                
            if device_id and device_id != 'all':
                system_conditions.append("device_id = %s" if use_mysql else "device_id = ?")
                
            system_where = " WHERE " + " AND ".join(system_conditions)
            cursor.execute(f"SELECT COUNT(*) FROM system_logs {system_where}", params)
            
            row = cursor.fetchone()
            stats['system']['error_count'] = list(row.values())[0] if use_mysql and isinstance(row, dict) and row else (row[0] if row else 0)
            
            conn.close()
        except Exception as e:
            logger.error(f"Stats aggregation failed: {e}")

        return stats

    def delete_device(self, device_id):
        """Unbind/Delete device from MySQL"""
        if not pymysql:
            return False
        conn = self.get_mysql_connection()
        if not conn:
            return False
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM device_info WHERE device_id = %s", (device_id,))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to delete device: {e}")
            return False
        finally:
            conn.close()

    def get_device_details(self, device_id):
        """Get detailed device info"""
        if not pymysql:
            return None
        conn = self.get_mysql_connection()
        if not conn:
            return None
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM device_info WHERE device_id = %s", (device_id,))
                return cursor.fetchone()
        except Exception as e:
            logger.error(f"Failed to get device details: {e}")
            return None
        finally:
            conn.close()

    def update_device_config(self, device_id, business_mode, startup_mode, updated_at):
        """Update device configuration in MySQL"""
        if not pymysql:
            return False
        conn = self.get_mysql_connection()
        if not conn:
            return False
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE device_info SET business_mode=%s, startup_mode=%s, config_updated_at=%s WHERE device_id=%s",
                    (business_mode, startup_mode, updated_at, device_id)
                )
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error updating device config: {e}")
            return False
        finally:
            conn.close()

    def collect_system_info(self):
        """Collect dynamic system information"""
        info = {}
        try:
            # Basic OS Info
            info['os_compatibility'] = f"{platform.system()} {platform.release()}"[:100]
            info['arch'] = platform.machine()[:20]
            info['firmware_version'] = str(platform.version())[:255]
            
            # Hardware
            info['processor_info'] = str(platform.processor())[:200]
            if psutil:
                mem = psutil.virtual_memory()
                info['memory_capacity'] = f"{mem.total / (1024**3):.2f} GB"
                info['storage_info'] = f"{psutil.disk_usage('/').total / (1024**3):.2f} GB"
                
                # Network
                info['network_interface'] = 'Unknown'
                addrs = psutil.net_if_addrs()
                for interface, snics in addrs.items():
                    for snic in snics:
                        if snic.family == socket.AF_INET:
                            info['ip_address'] = snic.address
                            info['network_interface'] = interface
                        if snic.family == psutil.AF_LINK:
                            info['mac_address'] = snic.address
                            
                # Runtime
                info['pid'] = str(os.getpid())
                p = psutil.Process(os.getpid())
                info['start_time'] = datetime.fromtimestamp(p.create_time()).strftime('%Y-%m-%d %H:%M:%S')
                info['runtime_duration'] = str(datetime.now() - datetime.fromtimestamp(p.create_time()))
                info['resource_usage'] = f"CPU: {psutil.cpu_percent()}%, MEM: {mem.percent}%"
                info['run_status'] = p.status()
                info['power_status'] = "AC" if psutil.sensors_battery() is None else f"Battery: {psutil.sensors_battery().percent}%"
                
        except Exception as e:
            logger.error(f"Failed to collect system info: {e}")
            
        return info

    def sync_device_info(self, metadata_path=None):
        """Sync full device metadata to MySQL"""
        # 1. Load static metadata from yaml if exists, otherwise create template
        static_info = {}
        if metadata_path:
            if not os.path.exists(metadata_path):
                try:
                    # Create a template metadata.yaml
                    template_content = """# Device Metadata Configuration
# This file provides static information about the device.
# It will be merged with dynamically collected system information.
# Any dynamically collected information (like IP, MAC, OS) will be overwritten by values here if provided.
# Leave empty (e.g., field: "") if you do not want to override or provide a value.

# 1. Basic Info (基础信息)
model: ""
serial_number: ""
manufacturer: ""
production_date: ""

# 2. Network Configuration (网络配置 - usually auto-collected, but can be overridden)
# ip_address: ""
# mac_address: ""
# network_interface: ""
protocol_type: ""

# 3. Device Location (设备位置)
location: ""
deployment_location: ""
site_name: ""
install_address: ""
geo_coords: ""

# 4. Hardware Specifications (硬件规格 - usually auto-collected, but can be overridden)
# processor_info: ""
# memory_capacity: ""
# storage_info: ""
expansion_slots: ""

# 5. Running Status & Other (运行状态及其他)
device_type: ""
department: ""
power_status: ""
battery_status: ""
sensor_data: ""
maintenance_record: ""
vuln_scan_result: ""
patch_level: ""
digital_signature: ""

# 6. Software Information (软件信息)
software_name: "ArcFace Edge"
software_version: "1.0.0"
software_vendor: "BioGuard"
software_description: "Edge Facial Recognition Client"
software_uuid: ""
license_type: ""
copyright_info: ""
eula_url: ""
build_time: ""
repo_url: ""
checksum: ""
install_path: ""
"""
                    with open(metadata_path, 'w', encoding='utf-8') as f:
                        f.write(template_content)
                    logger.info(f"Created default metadata.yaml at {metadata_path}")
                except Exception as e:
                    logger.error(f"Failed to create template metadata.yaml: {e}")

            if os.path.exists(metadata_path):
                try:
                    import yaml
                    with open(metadata_path, 'r', encoding='utf-8') as f:
                        static_info = yaml.safe_load(f) or {}
                except Exception as e:
                    logger.error(f"Failed to load metadata.yaml: {e}")
                
        # 2. Collect dynamic info
        dynamic_info = self.collect_system_info()
        
        # 3. Merge info (Static > Dynamic)
        info = {**dynamic_info, **static_info}
        
        # 4. Update Local SQLite
        try:
            conn = sqlite3.connect(self.sqlite_path)
            cursor = conn.cursor()
            
            # Build UPDATE query dynamically based on available keys
            # We map keys to DB columns. 
            # Note: yaml keys should match db columns or be mapped here.
            # Assuming 1-to-1 mapping for simplicity + snake_case
            
            columns = [
                'serial_number', 'manufacturer', 'production_date',
                'ip_address', 'mac_address', 'network_interface',
                'geo_coords', 'deployment_location', 'site_name', 'install_address',
                'processor_info', 'memory_capacity', 'storage_info', 'expansion_slots',
                'firmware_version', 'power_status', 'sensor_data', 'battery_status',
                'device_type', 'department', 'maintenance_record', 'protocol_type',
                'software_name', 'software_version', 'software_uuid', 'software_description', 'software_vendor',
                'os_compatibility', 'arch', 'license_type', 'copyright_info', 'eula_url',
                'build_time', 'repo_url', 'checksum', 'install_path',
                'pid', 'start_time', 'runtime_duration', 'resource_usage', 'run_status',
                'vuln_scan_result', 'patch_level', 'digital_signature'
            ]
            
            update_fields = []
            values = []
            for col in columns:
                if col in info:
                    update_fields.append(f"{col} = ?")
                    values.append(str(info[col]))
            
            if update_fields:
                sql = f"UPDATE device_info SET {', '.join(update_fields)} WHERE device_id = ?"
                values.append(self.device_id)
                cursor.execute(sql, values)
                conn.commit()
                logger.info("Updated local device metadata")
                
            conn.close()
        except Exception as e:
            logger.error(f"Failed to update local device info: {e}")
            
        # 5. Sync to MySQL
        if not pymysql:
            return

        mysql_conn = self.get_mysql_connection()
        if not mysql_conn:
            return
            
        try:
            # We need to update the same columns in MySQL
            # First, check if device exists in MySQL (it should, from init)
            with mysql_conn.cursor() as cursor:
                # Use same logic as SQLite update
                update_fields_mysql = []
                values_mysql = []
                for col in columns:
                    if col in info:
                        update_fields_mysql.append(f"{col} = %s")
                        values_mysql.append(str(info[col]))
                
                if update_fields_mysql:
                    sql = f"UPDATE device_info SET {', '.join(update_fields_mysql)} WHERE device_id = %s"
                    values_mysql.append(self.device_id)
                    cursor.execute(sql, values_mysql)
                    mysql_conn.commit()
                    logger.info("Synced device metadata to Cloud MySQL")
                    
        except Exception as e:
            logger.error(f"Failed to sync device info to MySQL: {e}")
        finally:
            mysql_conn.close()

    def get_local_device_info(self):
        try:
            conn = sqlite3.connect(self.sqlite_path)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM device_info LIMIT 1")
            row = cursor.fetchone()
            conn.close()
            if row:
                return {'device_id': row[0], 'machine_code': row[1], 'model': row[2], 'location': row[3], 'registered_at': row[4]}
            return None
        except Exception as e:
            logger.error(f"Failed to get local device info: {e}")
            return None

    def start_sync_service(self):
        """Start background synchronization thread"""
        self.sync_running = True
        self.sync_thread = threading.Thread(target=self._sync_loop, daemon=True)
        self.sync_thread.start()
        logger.info("Sync service started")

    def stop_sync_service(self):
        """Stop background sync"""
        self.sync_running = False
        if hasattr(self, 'sync_thread'):
            self.sync_thread.join(timeout=1)

    def _sync_loop(self):
        """Background sync loop"""
        while self.sync_running:
            try:
                # Check interval
                interval = self.config_manager.get_sync_interval()
                
                if interval > 0:
                    self.sync_data()
                    time.sleep(interval)
                else:
                    # Real-time mode: just keep heartbeat alive periodically (e.g., every 60s)
                    # Data sync is triggered by events.
                    # But we still need to sync device info or heartbeat.
                    self.sync_data() # This also updates heartbeat
                    time.sleep(60) 
                    
            except Exception as e:
                logger.error(f"Sync loop error: {e}")
                time.sleep(30)

    def sync_data_now(self):
        """Manual sync trigger"""
        try:
            self.sync_data()
            return True
        except Exception as e:
            logger.error(f"Manual sync failed: {e}")
            return False

    def sync_data(self):
        """Sync pending records from SQLite to MySQL"""
        if not pymysql:
            return

        mysql_conn = self.get_mysql_connection()
        if not mysql_conn:
            return

        sqlite_conn = sqlite3.connect(self.sqlite_path)
        # Use Row factory to access columns by name if needed, but fetchall returns tuples by default
        sqlite_cursor = sqlite_conn.cursor()
        
        try:
            # Sync Attendance
            sqlite_cursor.execute("SELECT id, user_name, timestamp, status, remarks, device_id FROM attendance_records WHERE sync_status='pending'")
            rows = sqlite_cursor.fetchall()
            if rows:
                with mysql_conn.cursor() as cursor:
                    for row in rows:
                        sql = "INSERT IGNORE INTO attendance_records (user_name, timestamp, status, remark, device_id) VALUES (%s, %s, %s, %s, %s)"
                        cursor.execute(sql, (row[1], row[2], row[3], row[4], row[5]))
                    mysql_conn.commit()
                
                # Update status in SQLite
                ids = [row[0] for row in rows]
                sqlite_cursor.execute(f"UPDATE attendance_records SET sync_status='synced', sync_timestamp=? WHERE id IN ({','.join(['?']*len(ids))})",
                                      (datetime.now(), *ids))
                sqlite_conn.commit()
                logger.info(f"Synced {len(rows)} attendance records")

            # Sync Access
            sqlite_cursor.execute("SELECT id, user_name, timestamp, direction, status, remarks, device_id FROM access_records WHERE sync_status='pending'")
            rows = sqlite_cursor.fetchall()
            if rows:
                with mysql_conn.cursor() as cursor:
                    for row in rows:
                        sql = "INSERT IGNORE INTO access_records (user_name, timestamp, direction, status, remark, device_id) VALUES (%s, %s, %s, %s, %s, %s)"
                        cursor.execute(sql, (row[1], row[2], row[3], row[4], row[5], row[6]))
                    mysql_conn.commit()
                
                ids = [row[0] for row in rows]
                sqlite_cursor.execute(f"UPDATE access_records SET sync_status='synced', sync_timestamp=? WHERE id IN ({','.join(['?']*len(ids))})",
                                      (datetime.now(), *ids))
                sqlite_conn.commit()
                logger.info(f"Synced {len(rows)} access records")

            # Sync Logs
            sqlite_cursor.execute("SELECT id, level, message, timestamp, module, device_id FROM system_logs WHERE sync_status='pending'")
            rows = sqlite_cursor.fetchall()
            if rows:
                with mysql_conn.cursor() as cursor:
                    for row in rows:
                        sql = "INSERT INTO system_logs (level, message, timestamp, module, device_id) VALUES (%s, %s, %s, %s, %s)"
                        cursor.execute(sql, (row[1], row[2], row[3], row[4], row[5]))
                    mysql_conn.commit()
                
                ids = [row[0] for row in rows]
                sqlite_cursor.execute(f"UPDATE system_logs SET sync_status='synced', sync_timestamp=? WHERE id IN ({','.join(['?']*len(ids))})",
                                      (datetime.now(), *ids))
                sqlite_conn.commit()
                logger.info(f"Synced {len(rows)} system logs")

            # Sync Admin Logs
            sqlite_cursor.execute("SELECT id, admin_name, action, target, details, sensitivity, timestamp, device_id FROM admin_logs WHERE sync_status='pending'")
            rows = sqlite_cursor.fetchall()
            if rows:
                with mysql_conn.cursor() as cursor:
                    for row in rows:
                        sql = "INSERT INTO admin_logs (admin_name, action, target, details, sensitivity, timestamp, device_id) VALUES (%s, %s, %s, %s, %s, %s, %s)"
                        cursor.execute(sql, (row[1], row[2], row[3], row[4], row[5], row[6], row[7]))
                    mysql_conn.commit()

                ids = [row[0] for row in rows]
                sqlite_cursor.execute(f"UPDATE admin_logs SET sync_status='synced', sync_timestamp=? WHERE id IN ({','.join(['?']*len(ids))})",
                                      (datetime.now(), *ids))
                sqlite_conn.commit()
                logger.info(f"Synced {len(rows)} admin logs")

            # Sync Device Config
            client_mode = self.config_manager.get_mode()
            client_start_mode = self.config_manager.get_start_mode()
            client_updated_at = self.config_manager.get_config_updated_at()

            with mysql_conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("SELECT business_mode, startup_mode, config_updated_at FROM device_info WHERE device_id=%s", (self.device_id,))
                server_config = cursor.fetchone()
                if server_config:
                    server_updated_at = server_config.get('config_updated_at') or 0
                    server_mode = server_config.get('business_mode')
                    server_start_mode = server_config.get('startup_mode')

                    if client_updated_at > server_updated_at:
                        cursor.execute("UPDATE device_info SET business_mode=%s, startup_mode=%s, config_updated_at=%s WHERE device_id=%s",
                                       (client_mode, client_start_mode, client_updated_at, self.device_id))
                        mysql_conn.commit()
                    elif server_updated_at > client_updated_at:
                        if server_mode and server_mode != 'None':
                            self.config_manager.set_mode(server_mode)
                        if server_start_mode and server_start_mode != 'None':
                            self.config_manager.set_start_mode(server_start_mode)
                        self.config_manager.set_config_updated_at(server_updated_at)
            
            # Sync Faces to Remote Server (Client -> Server)
            # This requires WebAdmin config to be set
            web_config = self.config_manager.get_web_admin_config()
            if web_config.get('host'):
                # We also need to sync deletions. 
                # If a face has sync_status='pending_delete', we should call the remote delete API
                sqlite_cursor.execute("SELECT user_name, device_id FROM faces WHERE sync_status='pending_delete'")
                deleted_rows = sqlite_cursor.fetchall()
                if deleted_rows:
                    for row in deleted_rows:
                        del_name, del_device_id = row
                        url = f"http://{web_config['host']}:{web_config['port']}/api/face/{del_name}?device_id={del_device_id}"
                        try:
                            # Add auth headers if token exists
                            headers = {}
                            if web_config.get('token'):
                                headers['Authorization'] = f"Bearer {web_config['token']}"
                                
                            logger.info(f"Syncing deletion for {del_name} ({del_device_id}) to {url}")
                            resp = requests.delete(url, headers=headers, timeout=10)
                            if resp.status_code == 200 or resp.status_code == 404:
                                # Successfully deleted on remote or already gone
                                # Now we can safely physically delete it from local SQLite
                                self.delete_face_from_db(del_name, del_device_id)
                            else:
                                logger.error(f"Failed to sync deletion for {del_name}: HTTP {resp.status_code} - {resp.text}")
                        except Exception as ex:
                            logger.error(f"Error syncing deletion for {del_name}: {ex}")

                # Sync new or updated faces
                sqlite_cursor.execute("SELECT user_name, groups, list_type, metadata, embedding, device_id FROM faces WHERE sync_status='pending'")
                face_rows = sqlite_cursor.fetchall()
                if face_rows:
                    synced_faces = []
                    for row in face_rows:
                        try:
                            # We expect 6 columns now
                            if len(row) >= 6:
                                name, groups, list_type, metadata, encrypted_emb, face_device_id = row[:6]
                                try:
                                    embedding = self._decrypt_embedding(encrypted_emb)
                                except:
                                    embedding = None
                            elif len(row) == 5:
                                name, groups, list_type, metadata, encrypted_emb = row
                                face_device_id = self.device_id
                                try:
                                    embedding = self._decrypt_embedding(encrypted_emb)
                                except:
                                    embedding = None
                            else:
                                name, groups, list_type, metadata = row[:4]
                                face_device_id = self.device_id
                                embedding = None
                            
                            # Load image
                            _, new_path = self.get_image_path(name, face_device_id)
                            old_path, _ = self.get_image_path(name, 'admin')
                            
                            image_path = new_path if os.path.exists(new_path) else old_path
                            if not os.path.exists(image_path):
                                logger.warning(f"Skipping sync for {name} on {face_device_id}: Image not found")
                                # If image is truly missing, we might still want to sync the embedding?
                                # For now let's just create a dummy file to pass the API or handle API without file.
                                # The current API requires a file. So we skip.
                                continue
                                
                            url = f"http://{web_config['host']}:{web_config['port']}/api/face/sync/push"
                            
                            # Add auth headers if token exists
                            headers = {}
                            if web_config.get('token'):
                                headers['Authorization'] = f"Bearer {web_config['token']}"
                            
                            # Check for full image
                            full_image_path = os.path.join(self.face_images_dir, "full", f"{hashlib.md5(name.encode()).hexdigest()}.jpg")
                            if not os.path.exists(full_image_path):
                                full_image_path = None
                                
                            # Use requests in a separate function to allow mocking/testing or retry logic
                            # and importantly to handle the file opening safely
                            # Pass face_device_id to push
                            self._push_face_to_remote(url, name, image_path, groups, list_type, metadata, headers, synced_faces, embedding, full_image_path, face_device_id)
                                    
                        except Exception as ex:
                            logger.error(f"Error syncing face {name}: {ex}")
                            
                    if synced_faces:
                        # Need to update sync_status based on name AND device_id
                        for s_name, s_device_id in synced_faces:
                            sqlite_cursor.execute("UPDATE faces SET sync_status='synced' WHERE user_name=? AND device_id=?", (s_name, s_device_id))
                        sqlite_conn.commit()
                        logger.info(f"Synced {len(synced_faces)} new faces to server")
                    # For now, we only sync 'pending' faces.
                    # If user updates face (re-registers), add_face_to_db sets status to 'pending', so it will be re-synced.
                    # Good.

            # Update device heartbeat
            with mysql_conn.cursor() as cursor:
                cursor.execute("UPDATE device_info SET last_seen=NOW() WHERE device_id=%s", (self.device_id,))
            mysql_conn.commit()

        except Exception as e:
            logger.error(f"Sync failed: {e}")
        finally:
            sqlite_conn.close()
            mysql_conn.close()

    def _push_face_to_remote(self, url, name, image_path, groups, list_type, metadata, headers, synced_faces, embedding=None, full_image_path=None, device_id='admin'):
        try:
            files = {}
            # We need to keep file handles open until request is sent
            open_files = []
            
            try:
                f = open(image_path, 'rb')
                open_files.append(f)
                files['file'] = (f"{name}.jpg", f, 'image/jpeg')
                
                if full_image_path:
                    f_full = open(full_image_path, 'rb')
                    open_files.append(f_full)
                    files['full_image'] = (f"{name}_full.jpg", f_full, 'image/jpeg')
                
                data = {
                    'name': name,
                    'groups': groups,
                    'list_type': list_type,
                    'metadata': metadata,
                    'device_id': device_id
                }
                if embedding is not None:
                    import base64
                    import pickle
                    data['embedding'] = base64.b64encode(pickle.dumps(embedding)).decode('utf-8')
                
                resp = requests.post(url, files=files, data=data, headers=headers, timeout=30) # Increased timeout for larger upload
                if resp.status_code == 200:
                    synced_faces.append((name, device_id))
                elif resp.status_code == 400:
                    # If 400 (Bad Request), likely invalid image or no face detected.
                    # We should mark it as synced to prevent infinite retries.
                    logger.warning(f"Face sync rejected for {name} (400 Bad Request). Marking as synced to skip.")
                    synced_faces.append((name, device_id))
                elif resp.status_code == 409:
                    logger.warning(f"Face sync rejected for {name} (409 Conflict). Marking as synced to skip.")
                    synced_faces.append((name, device_id))
                else:
                    logger.error(f"Failed to sync face {name}: {resp.text}")
            finally:
                for f in open_files:
                    f.close()
                    
        except Exception as e:
            logger.error(f"Error pushing face {name}: {e}")

    def add_attendance_record(self, user_name, status="Normal", remark=""):
        try:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            conn = sqlite3.connect(self.sqlite_path)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO attendance_records (user_name, status, timestamp, device_id, sync_status, remarks) VALUES (?, ?, ?, ?, ?, ?)",
                           (user_name, status, timestamp, self.device_id, 'pending', remark))
            conn.commit()
            conn.close()
            
            # Check for real-time sync
            if self.config_manager.get_sync_interval() == 0:
                self.sync_data_now()
                
            return True
        except Exception as e:
            logger.error(f"Failed to add attendance record: {e}")
            return False

    def add_access_record(self, user_name, direction="In", status="Allowed", remark=""):
        try:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            conn = sqlite3.connect(self.sqlite_path)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO access_records (user_name, direction, status, timestamp, device_id, sync_status, remarks) VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (user_name, direction, status, timestamp, self.device_id, 'pending', remark))
            conn.commit()
            conn.close()
            
            # Check for real-time sync
            if self.config_manager.get_sync_interval() == 0:
                self.sync_data_now()

            return True
        except Exception as e:
            logger.error(f"Failed to add access record: {e}")
            return False
            
    def clear_logs(self, log_type='system'):
        """Clear logs from SQLite"""
        try:
            conn = sqlite3.connect(self.sqlite_path)
            cursor = conn.cursor()
            if log_type == 'system':
                cursor.execute("DELETE FROM system_logs")
            elif log_type == 'admin':
                cursor.execute("DELETE FROM admin_logs")
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Failed to clear logs: {e}")
            return False

    def add_system_log(self, level, message, module="System", device_id=None, sync_status='pending'):
        # Skip if called from log handler to avoid recursion
        # But we need to distinguish direct calls vs log handler calls
        # Let's trust the handler logic above.
        
        try:
            conn = sqlite3.connect(self.sqlite_path)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO system_logs (level, message, module, device_id, sync_status) VALUES (?, ?, ?, ?, ?)",
                           (level, message, module, device_id or self.device_id, sync_status))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Failed to add system log: {e}")
            return False

    def add_admin_log(self, admin_name, action, target, details="", sensitivity="normal", device_id=None):
        try:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            conn = sqlite3.connect(self.sqlite_path)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO admin_logs (admin_name, action, target, details, sensitivity, timestamp, device_id, sync_status) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')",
                           (admin_name, action, target, details, sensitivity, timestamp, device_id or self.device_id))
            conn.commit()
            conn.close()
            
            # Check for real-time sync
            if self.config_manager.get_sync_interval() == 0:
                self.sync_data_now()
                
            return True
        except Exception as e:
            logger.error(f"Failed to add admin log: {e}")
            return False

    def get_attendance_records(self, limit=100, offset=0, start_date=None, end_date=None, search="", device_id=""):
        # First try to fetch from MySQL if configured
        if pymysql:
            conn = self.get_mysql_connection()
            if conn:
                try:
                    with conn.cursor() as cursor:
                        query = "SELECT * FROM attendance_records WHERE 1=1"
                        params = []
                        
                        if start_date:
                            query += " AND timestamp >= %s"
                            params.append(start_date)
                        if end_date:
                            query += " AND timestamp <= %s"
                            params.append(end_date)
                        if search:
                            query += " AND (user_name LIKE %s OR remark LIKE %s)"
                            params.extend([f"%{search}%", f"%{search}%"])
                        if device_id:
                            query += " AND device_id = %s"
                            params.append(device_id)
                            
                        query += " ORDER BY timestamp DESC LIMIT %s OFFSET %s"
                        params.extend([limit, offset])
                        
                        cursor.execute(query, params)
                        rows = cursor.fetchall()
                        
                        # Convert dict rows to list format to match SQLite output for compatibility
                        # SQLite: id, user_name, timestamp, status, remarks, device_id, sync_status, sync_timestamp
                        result = []
                        for row in rows:
                            result.append((
                                row.get('id'),
                                row.get('user_name'),
                                row.get('timestamp'),
                                row.get('status'),
                                row.get('remark'),
                                row.get('device_id'),
                                'synced', # Always synced if from MySQL
                                row.get('sync_timestamp')
                            ))
                        return result
                except Exception as e:
                    logger.error(f"Failed to fetch attendance from MySQL: {e}")
                finally:
                    conn.close()

        # Fallback to SQLite
        try:
            conn = sqlite3.connect(self.sqlite_path)
            cursor = conn.cursor()
            query = "SELECT * FROM attendance_records WHERE 1=1"
            params = []
            
            if start_date:
                query += " AND timestamp >= ?"
                params.append(start_date)
            if end_date:
                query += " AND timestamp <= ?"
                params.append(end_date)
            if search:
                query += " AND (user_name LIKE ? OR remarks LIKE ?)"
                params.extend([f"%{search}%", f"%{search}%"])
            if device_id:
                query += " AND device_id = ?"
                params.append(device_id)
                
            query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            conn.close()
            return rows
        except Exception as e:
            logger.error(f"Failed to get attendance records: {e}")
            return []

    def get_access_records(self, limit=100, offset=0, start_date=None, end_date=None, search="", status="", device_id=""):
        # First try to fetch from MySQL if configured
        if pymysql:
            conn = self.get_mysql_connection()
            if conn:
                try:
                    with conn.cursor() as cursor:
                        query = "SELECT * FROM access_records WHERE 1=1"
                        params = []
                        
                        if start_date:
                            query += " AND timestamp >= %s"
                            params.append(start_date)
                        if end_date:
                            query += " AND timestamp <= %s"
                            params.append(end_date)
                        if search:
                            query += " AND (user_name LIKE %s OR remark LIKE %s)"
                            params.extend([f"%{search}%", f"%{search}%"])
                        if status:
                            if status == 'Denied':
                                query += " AND (status = 'Denied' OR status = 'Denied-Blacklist')"
                            else:
                                query += " AND status = %s"
                                params.append(status)
                        if device_id:
                            query += " AND device_id = %s"
                            params.append(device_id)
                                
                        query += " ORDER BY timestamp DESC LIMIT %s OFFSET %s"
                        params.extend([limit, offset])
                        
                        cursor.execute(query, params)
                        rows = cursor.fetchall()
                        
                        # Convert dict rows to list format
                        # SQLite: id, user_name, timestamp, direction, status, remarks, device_id, sync_status, sync_timestamp
                        result = []
                        for row in rows:
                            result.append((
                                row.get('id'),
                                row.get('user_name'),
                                row.get('timestamp'),
                                row.get('direction'),
                                row.get('status'),
                                row.get('remark'),
                                row.get('device_id'),
                                'synced',
                                row.get('sync_timestamp')
                            ))
                        return result
                except Exception as e:
                    logger.error(f"Failed to fetch access records from MySQL: {e}")
                finally:
                    conn.close()

        # Fallback to SQLite
        try:
            conn = sqlite3.connect(self.sqlite_path)
            cursor = conn.cursor()
            query = "SELECT * FROM access_records WHERE 1=1"
            params = []
            
            if start_date:
                query += " AND timestamp >= ?"
                params.append(start_date)
            if end_date:
                query += " AND timestamp <= ?"
                params.append(end_date)
            if search:
                query += " AND (user_name LIKE ? OR remarks LIKE ?)"
                params.extend([f"%{search}%", f"%{search}%"])
            if status:
                if status == 'Denied':
                    query += " AND (status = 'Denied' OR status = 'Denied-Blacklist')"
                else:
                    query += " AND status = ?"
                    params.append(status)
            if device_id:
                query += " AND device_id = ?"
                params.append(device_id)
                    
            query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            conn.close()
            return rows
        except Exception as e:
            logger.error(f"Failed to get access records: {e}")
            return []

    def get_system_logs(self, limit=100, offset=0, device_id=""):
        # First try to fetch from MySQL if configured
        if pymysql:
            conn = self.get_mysql_connection()
            if conn:
                try:
                    with conn.cursor() as cursor:
                        query = "SELECT * FROM system_logs WHERE 1=1"
                        params = []
                        if device_id:
                            query += " AND device_id = %s"
                            params.append(device_id)
                        query += " ORDER BY timestamp DESC LIMIT %s OFFSET %s"
                        params.extend([limit, offset])
                        
                        cursor.execute(query, params)
                        rows = cursor.fetchall()
                        
                        # SQLite: id, level, message, timestamp, module, device_id, sync_status, sync_timestamp
                        result = []
                        for row in rows:
                            result.append((
                                row.get('id'),
                                row.get('level'),
                                row.get('message'),
                                row.get('timestamp'),
                                row.get('module'),
                                row.get('device_id'),
                                'synced',
                                row.get('sync_timestamp')
                            ))
                        return result
                except Exception as e:
                    logger.error(f"Failed to fetch system logs from MySQL: {e}")
                finally:
                    conn.close()

        try:
            conn = sqlite3.connect(self.sqlite_path)
            cursor = conn.cursor()
            query = "SELECT * FROM system_logs WHERE 1=1"
            params = []
            if device_id:
                query += " AND device_id = ?"
                params.append(device_id)
            query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            conn.close()
            return rows
        except Exception as e:
            logger.error(f"Failed to get system logs: {e}")
            return []

    def get_admin_logs(self, limit=100, offset=0, start_date=None, end_date=None, search="", device_id=""):
        # First try to fetch from MySQL if configured
        if pymysql:
            conn = self.get_mysql_connection()
            if conn:
                try:
                    with conn.cursor() as cursor:
                        query = "SELECT * FROM admin_logs WHERE 1=1"
                        params = []
                        
                        if start_date:
                            query += " AND timestamp >= %s"
                            params.append(start_date)
                        if end_date:
                            query += " AND timestamp <= %s"
                            params.append(end_date)
                        if search:
                            query += " AND (admin_name LIKE %s OR action LIKE %s OR target LIKE %s)"
                            params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
                        if device_id:
                            query += " AND device_id = %s"
                            params.append(device_id)
                            
                        query += " ORDER BY timestamp DESC LIMIT %s OFFSET %s"
                        params.extend([limit, offset])
                        
                        cursor.execute(query, params)
                        rows = cursor.fetchall()
                        
                        # SQLite: id, admin_name, action, target, details, sensitivity, timestamp, device_id, sync_status, sync_timestamp
                        result = []
                        for row in rows:
                            result.append((
                                row.get('id'),
                                row.get('admin_name'),
                                row.get('action'),
                                row.get('target'),
                                row.get('details'),
                                row.get('sensitivity'),
                                row.get('timestamp'),
                                row.get('device_id'),
                                'synced',
                                row.get('sync_timestamp')
                            ))
                        return result
                except Exception as e:
                    logger.error(f"Failed to fetch admin logs from MySQL: {e}")
                finally:
                    conn.close()

        try:
            conn = sqlite3.connect(self.sqlite_path)
            cursor = conn.cursor()
            query = "SELECT * FROM admin_logs WHERE 1=1"
            params = []
            
            if start_date:
                query += " AND timestamp >= ?"
                params.append(start_date)
            if end_date:
                query += " AND timestamp <= ?"
                params.append(end_date)
            if search:
                query += " AND (admin_name LIKE ? OR action LIKE ? OR target LIKE ?)"
                params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
            if device_id:
                query += " AND device_id = ?"
                params.append(device_id)
                
            query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            conn.close()
            return rows
        except Exception as e:
            logger.error(f"Failed to get admin logs: {e}")
            return []

    def _encrypt_embedding(self, embedding):
        if not Fernet:
            return pickle.dumps(embedding)
        key = self.config_manager.get_encryption_key()
        if not key:
            return pickle.dumps(embedding)
        f = Fernet(key)
        return f.encrypt(pickle.dumps(embedding))

    def _decrypt_embedding(self, encrypted_data):
        if not Fernet:
            return pickle.loads(encrypted_data)
        key = self.config_manager.get_encryption_key()
        if not key:
            try:
                return pickle.loads(encrypted_data)
            except:
                return None
        try:
            f = Fernet(key)
            return pickle.loads(f.decrypt(encrypted_data))
        except Exception as e:
            # Fallback to plain pickle in case of legacy unencrypted data or wrong key
            try:
                return pickle.loads(encrypted_data)
            except:
                pass
            logger.error(f"Decryption failed: {e}")
            return None

    def get_image_path(self, name, device_id='admin'):
        safe_name = hashlib.md5(name.encode()).hexdigest()
        old_path = os.path.join(self.face_images_dir, f"{safe_name}.jpg")
        
        safe_dev = hashlib.md5(device_id.encode()).hexdigest() if device_id != 'admin' else 'admin'
        new_path = os.path.join(self.face_images_dir, f"{safe_name}_{safe_dev}.jpg")
        
        return old_path, new_path

    def save_face_image(self, name, face_image, device_id='admin'):
        try:
            _, new_path = self.get_image_path(name, device_id)
            cv2.imwrite(new_path, face_image, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
            return True
        except Exception as e:
            logger.error(f"Failed to save face image: {str(e)}")
            return False

    def load_face_image(self, name, device_id=None):
        try:
            if device_id:
                old_path, new_path = self.get_image_path(name, device_id)
                if os.path.exists(new_path):
                    return cv2.imread(new_path)
                elif os.path.exists(old_path):
                    return cv2.imread(old_path)
                    
            # Try to find any image associated with this user's device_ids
            user_faces = getattr(self, 'database', {}).get(name, [])
            if isinstance(user_faces, list):
                for face in user_faces:
                    f_device_id = face.get('device_id', 'admin')
                    old_path, new_path = self.get_image_path(name, f_device_id)
                    if os.path.exists(new_path):
                        return cv2.imread(new_path)
                    elif os.path.exists(old_path):
                        return cv2.imread(old_path)
                        
            # Fallback to global
            old_path, new_path = self.get_image_path(name, 'admin')
            if os.path.exists(new_path):
                return cv2.imread(new_path)
            elif os.path.exists(old_path):
                return cv2.imread(old_path)
                
            return None
        except Exception as e:
            logger.error(f"Failed to load face image: {str(e)}")
            return None

    def delete_face_image(self, name, device_id='admin'):
        try:
            old_path, new_path = self.get_image_path(name, device_id)
            if os.path.exists(new_path):
                os.remove(new_path)
                return True
            elif os.path.exists(old_path):
                os.remove(old_path)
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to delete face image: {str(e)}")
            return False

    def check_face_image_exists(self, name, device_id=None):
        if device_id:
            old_path, new_path = self.get_image_path(name, device_id)
            if os.path.exists(new_path) or os.path.exists(old_path):
                return True
                
        user_faces = getattr(self, 'database', {}).get(name, [])
        if isinstance(user_faces, list):
            for face in user_faces:
                f_device_id = face.get('device_id', 'admin')
                old_path, new_path = self.get_image_path(name, f_device_id)
                if os.path.exists(new_path) or os.path.exists(old_path):
                    return True
                    
        old_path, new_path = self.get_image_path(name, 'admin')
        return os.path.exists(new_path) or os.path.exists(old_path)

    def load_faces_from_db(self):
        faces = {}
        try:
            conn = sqlite3.connect(self.sqlite_path)
            cursor = conn.cursor()
            
            # Check if metadata column exists (migration)
            cursor.execute("PRAGMA table_info(faces)")
            columns = [info[1] for info in cursor.fetchall()]
            has_metadata = 'metadata' in columns
            has_device_id = 'device_id' in columns
            
            query = "SELECT user_name, embedding, groups, list_type"
            if has_metadata: query += ", metadata"
            if has_device_id: query += ", device_id"
            query += " FROM faces WHERE sync_status != 'pending_delete'"
            
            cursor.execute(query)
            rows = cursor.fetchall()
            
            import json
            for row in rows:
                name = row[0]
                encrypted_emb = row[1]
                groups = row[2] if row[2] else 'all'
                list_type = row[3] if row[3] else 'white'
                
                metadata = {}
                device_id = 'admin'
                
                idx = 4
                if has_metadata:
                    metadata_json = row[idx]
                    try:
                        metadata = json.loads(metadata_json) if metadata_json else {}
                    except:
                        metadata = {}
                    idx += 1
                    
                if has_device_id:
                    device_id = row[idx] if row[idx] else 'admin'
                    
                emb = self._decrypt_embedding(encrypted_emb)
                if emb is not None:
                    if name not in faces:
                        faces[name] = []
                    faces[name].append({
                        'embedding': emb,
                        'groups': groups,
                        'list_type': list_type,
                        'metadata': metadata,
                        'device_id': device_id
                    })
        except Exception as e:
            logger.error(f"Failed to load faces from DB: {e}")
        
        # Migrate from Pickle if empty
        if not faces and os.path.exists(self.database_path):
            try:
                with open(self.database_path, "rb") as f:
                    old_faces = pickle.load(f)
                
                # We need a new cursor since the old one might be closed or we want to commit
                cursor = conn.cursor()
                for name, emb in old_faces.items():
                    encrypted_emb = self._encrypt_embedding(emb)
                    cursor.execute("INSERT OR REPLACE INTO faces (user_name, embedding, groups, list_type, metadata, device_id, sync_status) VALUES (?, ?, ?, ?, ?, ?, 'synced')", 
                                   (name, encrypted_emb, 'all', 'white', '{}', 'admin'))
                    faces[name] = [{
                        'embedding': emb,
                        'groups': 'all',
                        'list_type': 'white',
                        'metadata': {},
                        'device_id': 'admin'
                    }]
                conn.commit()
                logger.info("Migrated faces from pickle to SQLite")
                
                # Rename the pickle file to prevent re-migration of deleted users
                try:
                    new_path = self.database_path + ".migrated"
                    if os.path.exists(new_path):
                        os.remove(new_path)
                    os.rename(self.database_path, new_path)
                    logger.info(f"Renamed legacy database to {new_path}")
                except Exception as e:
                    logger.warning(f"Failed to rename legacy database: {e}")

            except Exception as e:
                logger.error(f"Migration failed: {e}")
        
        # If SQLite is already populated but legacy pickle exists, rename it to prevent future re-migration
        elif faces and os.path.exists(self.database_path):
            try:
                new_path = self.database_path + ".migrated"
                if os.path.exists(new_path):
                    os.remove(new_path)
                os.rename(self.database_path, new_path)
                logger.info(f"Renamed legacy database {self.database_path} to .migrated (SQLite already populated)")
            except Exception as e:
                logger.warning(f"Failed to rename legacy database: {e}")
                
        if 'conn' in locals():
            conn.close()
            
        return faces

    def load_admins_from_db(self):
        admins = set()
        try:
            conn = sqlite3.connect(self.sqlite_path)
            cursor = conn.cursor()
            cursor.execute("SELECT user_name FROM admins")
            rows = cursor.fetchall()
            conn.close()
            admins = {row[0] for row in rows}
        except Exception as e:
            logger.error(f"Failed to load admins from DB: {e}")
            
        # Migrate admins
        admin_pkl = self.database_path.replace(".pkl", "_admin.pkl")
        if not admins and os.path.exists(admin_pkl):
             try:
                with open(admin_pkl, "rb") as f:
                    old_admins = pickle.load(f)
                for name in old_admins:
                    self.set_admin_db(name)
                    admins.add(name)
                logger.info("Migrated admins from pickle to SQLite")
                
                # Rename the pickle file to prevent re-migration of deleted users
                try:
                    new_path = admin_pkl + ".migrated"
                    if os.path.exists(new_path):
                        os.remove(new_path)
                    os.rename(admin_pkl, new_path)
                    logger.info(f"Renamed legacy admin database to {new_path}")
                except Exception as e:
                    logger.warning(f"Failed to rename legacy admin database: {e}")
                    
             except Exception as e:
                logger.error(f"Admin migration failed: {e}")
        
        # If SQLite admins populated but legacy pickle exists, rename it
        elif admins and os.path.exists(admin_pkl):
            try:
                new_path = admin_pkl + ".migrated"
                if os.path.exists(new_path):
                    os.remove(new_path)
                os.rename(admin_pkl, new_path)
                logger.info(f"Renamed legacy admin database {admin_pkl} to .migrated (SQLite already populated)")
            except Exception as e:
                logger.warning(f"Failed to rename legacy admin database: {e}")
                
        return admins

    def add_face_to_db(self, name, embedding, groups='all', list_type='white', metadata=None, device_id=None, sync_status='pending'):
        if device_id is None:
            device_id = getattr(self, 'device_id', 'admin')
        try:
            encrypted_emb = self._encrypt_embedding(embedding)
            conn = sqlite3.connect(self.sqlite_path)
            cursor = conn.cursor()
            
            # Use json.dumps for metadata, ensure it's not None
            import json
            metadata_json = json.dumps(metadata) if metadata else '{}'
            
            cursor.execute("INSERT OR REPLACE INTO faces (user_name, embedding, groups, list_type, metadata, device_id, sync_status) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                           (name, encrypted_emb, groups, list_type, metadata_json, device_id, sync_status))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Failed to add face to DB: {e}")
            return False

    def mark_face_as_deleted(self, name, device_id=None, sync_status='pending_delete'):
        """Mark face as deleted instead of removing it immediately to allow syncing the deletion"""
        try:
            conn = sqlite3.connect(self.sqlite_path)
            cursor = conn.cursor()
            if device_id:
                cursor.execute(
                    "UPDATE faces SET sync_status = ? WHERE user_name = ? AND device_id = ?",
                    (sync_status, name, device_id)
                )
            else:
                cursor.execute(
                    "UPDATE faces SET sync_status = ? WHERE user_name = ?",
                    (sync_status, name)
                )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error marking face {name} as deleted in SQLite: {e}")

    def delete_face_from_db(self, name, device_id=None):
        try:
            conn = sqlite3.connect(self.sqlite_path)
            cursor = conn.cursor()
            if device_id:
                cursor.execute("DELETE FROM faces WHERE user_name=? AND device_id=?", (name, device_id))
            else:
                cursor.execute("DELETE FROM faces WHERE user_name=?", (name,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Failed to delete face from DB: {e}")
            return False

    def set_admin_db(self, name):
        try:
            conn = sqlite3.connect(self.sqlite_path)
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO admins (user_name) VALUES (?)", (name,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Failed to set admin in DB: {e}")
            return False

    def remove_admin_db(self, name):
        try:
            conn = sqlite3.connect(self.sqlite_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM admins WHERE user_name=?", (name,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Failed to remove admin from DB: {e}")
            return False

class SyncDatabaseManager(DatabaseManagerBase):
    def __init__(self, database_path="./dd/face_database.pkl", sqlite_path="./dd/records.db"):
        super().__init__(database_path, sqlite_path)
        self.database = self.load_faces_from_db()
        self.admin_users = self.load_admins_from_db()

    def add_face(self, name, embedding, face_image=None, groups='all', list_type='white', metadata=None, device_id=None):
        if device_id is None:
            device_id = getattr(self, 'device_id', 'admin')
        if name not in self.database:
            self.database[name] = []
        self.database[name] = [f for f in self.database[name] if f['device_id'] != device_id]
        self.database[name].append({
            'embedding': embedding,
            'groups': groups,
            'list_type': list_type,
            'metadata': metadata or {},
            'device_id': device_id
        })
        if face_image is not None:
            self.save_face_image(name, face_image, device_id)
        self.add_face_to_db(name, embedding, groups, list_type, metadata, device_id, sync_status='pending')
        self.add_system_log("INFO", f"Added face for user: {name}", "FaceManager")

    def delete_face(self, name, device_id=None, sync_status='pending_delete'):
        if name in self.database:
            if device_id:
                self.database[name] = [f for f in self.database[name] if f['device_id'] != device_id]
                self.delete_face_image(name, device_id)
                # Instead of physical delete, mark as pending_delete
                self.mark_face_as_deleted(name, device_id, sync_status)
                if not self.database[name]:
                    del self.database[name]
                    if name in self.admin_users:
                        self.admin_users.remove(name)
                        self.remove_admin_db(name)
                self.add_system_log("INFO", f"Deleted face for user: {name} (Device: {device_id})", "FaceManager")
                return True
            else:
                for f in self.database[name]:
                    self.delete_face_image(name, f['device_id'])
                    self.mark_face_as_deleted(name, f['device_id'], sync_status)
                del self.database[name]
                if name in self.admin_users:
                    self.admin_users.remove(name)
                    self.remove_admin_db(name)
                self.add_system_log("INFO", f"Deleted all faces for user: {name}", "FaceManager")
                return True
        return False

    def get_all_names(self):
        return list(self.database.keys())

    def name_exists(self, name):
        return name in self.database

    def set_as_admin(self, name):
        if name in self.database:
            self.admin_users.add(name)
            self.set_admin_db(name)
            self.add_system_log("INFO", f"Set user as admin: {name}", "AuthManager")
            return True
        return False

    def is_admin(self, name):
        return name in self.admin_users

    def remove_admin(self, name):
        if name in self.admin_users:
            self.admin_users.remove(name)
            self.remove_admin_db(name)
            self.add_system_log("INFO", f"Removed admin rights from: {name}", "AuthManager")
            return True
        return False

    def build_nn_model(self):
        if not self.database:
            return None, []
        embeddings = []
        names = []
        for name, face_list in self.database.items():
            for face in face_list:
                embeddings.append(face['embedding'])
                names.append(name)
        if not embeddings:
            return None, []
        nn_model = NearestNeighbors(n_neighbors=1, metric="cosine")
        nn_model.fit(embeddings)
        return nn_model, names

    def find_best_match(self, embedding, threshold=0.6, device_id=None):
        nn_model, names = self.build_nn_model()
        if nn_model is None:
            return None, 0, None, None
        distances, indices = nn_model.kneighbors([embedding])
        if distances[0][0] < threshold:
            similarity = 1 - distances[0][0]
            name = names[indices[0][0]]
            user_faces = self.database.get(name, [])
            if user_faces:
                 # Try to return the face that matches the device_id if provided
                 if device_id:
                     for face in user_faces:
                         if face.get('device_id', 'admin') == device_id:
                             return name, similarity, face.get('groups', 'all'), face.get('list_type', 'white')
                 
                 return name, similarity, user_faces[0].get('groups', 'all'), user_faces[0].get('list_type', 'white')
            return name, similarity, 'all', 'white'
        return None, 0, None, None

    def sync_faces_from_remote(self, host, port):
        try:
            url = f"http://{host}:{port}/api/face/sync/all?device_id={self.device_id}"
            logger.info(f"Syncing faces from {url}...")
            response = requests.get(url, timeout=60)
            
            if response.status_code == 200:
                users = response.json()
                count = 0
                updated = 0
                remote_names = set()
                
                for user in users:
                    name = user['name']
                    remote_names.add(name)
                    # Handle embedding list to numpy
                    embedding_list = user['embedding']
                    embedding = np.array(embedding_list, dtype=np.float32)
                    
                    groups = user.get('groups', 'all')
                    list_type = user.get('list_type', 'white')
                    metadata = user.get('metadata', {})
                    is_admin = user.get('is_admin', False)
                    face_image_b64 = user.get('face_image')
                    device_id = user.get('device_id', 'admin')
                    
                    # Check if this face belongs to this device
                    device_ids = [d.strip() for d in device_id.split(',')]
                    if self.device_id not in device_ids:
                        continue
                    
                    exists = self.name_exists(name)
                    
                    # Update Memory
                    if name not in self.database:
                        self.database[name] = []
                    self.database[name] = [f for f in self.database[name] if f['device_id'] != device_id]
                    self.database[name].append({
                        'embedding': embedding,
                        'groups': groups,
                        'list_type': list_type,
                        'metadata': metadata,
                        'device_id': device_id
                    })
                    
                    # Update SQLite
                    # If the face is from ANOTHER device, we just save it as 'synced' locally so it doesn't push back
                    # If the face is from OUR device, it might be already 'pending' or 'synced', we shouldn't overwrite 
                    # a 'pending' state with 'synced' just from pulling, unless we want to confirm it's synced.
                    # But the server has it, so it IS synced.
                    self.add_face_to_db(name, embedding, groups, list_type, metadata, device_id, sync_status='synced')
                    
                    # Save Image
                    if face_image_b64:
                        try:
                            img_data = base64.b64decode(face_image_b64)
                            nparr = np.frombuffer(img_data, np.uint8)
                            face_image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                            if face_image is not None:
                                self.save_face_image(name, face_image, device_id)
                        except Exception as ie:
                            logger.error(f"Image save error for {name}: {ie}")
                            
                    # Admin
                    if is_admin:
                        self.set_as_admin(name)
                    else:
                        if self.is_admin(name):
                            self.remove_admin(name)
                            
                    if exists:
                        updated += 1
                    else:
                        count += 1
                        
                # Handle deletions: Remove local faces that are not on the remote server
                # BUT wait! We only want to delete them if they have already been synced to the server.
                # If a local face is 'pending' (newly created locally), we MUST NOT delete it.
                
                # Logic:
                # 1. Get all local faces
                # 2. For each local face, check if it exists in remote list (match name AND device_id)
                # 3. If not in remote list AND sync_status is 'synced', then delete it.
                
                sqlite_conn = sqlite3.connect(self.sqlite_path)
                sqlite_cursor = sqlite_conn.cursor()
                
                # Get all local faces with device_id and sync_status
                sqlite_cursor.execute("SELECT user_name, device_id, sync_status FROM faces")
                local_faces = sqlite_cursor.fetchall() # list of (name, device_id, sync_status)
                
                deleted_count = 0
                
                # Build remote set for fast lookup: (name, device_id)
                remote_face_set = set()
                for user in users:
                    r_name = user['name']
                    r_device_id = user.get('device_id', 'admin')
                    # Because we no longer filter by device_id in the /api/face/sync/all API,
                    # we get ALL faces. So we can just check if the face is in this list.
                    
                    if r_device_id == 'admin':
                        remote_face_set.add((r_name, 'admin'))
                    else:
                        for dev in r_device_id.split(','):
                            remote_face_set.add((r_name, dev.strip()))
                            
                # Let's add logging to debug what's happening
                logger.info(f"Remote faces count: {len(remote_face_set)}. Local faces count: {len(local_faces)}")
                
                for l_name, l_device_id, l_sync_status in local_faces:
                    # Skip if this is our OWN device face that hasn't synced yet (pending)
                    # We should keep it.
                    # But if it is 'synced', and not in remote_face_set, it means it was deleted on server.
                    
                    # Also check if this face actually belongs to us (cleanup from previous bugs)
                    l_device_ids = [d.strip() for d in l_device_id.split(',')]
                    belongs_to_us = self.device_id in l_device_ids
                    
                    if not belongs_to_us or (l_name, l_device_id) not in remote_face_set:
                        # Special check: If server sent back 'admin', it covers all devices for that user if we want,
                        # but in our new schema, 'admin' is just a device_id.
                        # Wait, if we register a face on edge as "my_device", it will be "my_device".
                        # If the server has it as "my_device", it will be in remote_face_set.
                        # If the server deleted it, it won't be in remote_face_set.
                        
                        if l_sync_status == 'synced':
                            # Let's double check if we really need to delete.
                            # We should only delete if the remote doesn't have it AND we successfully communicated.
                            logger.info(f"Deleting local face: {l_name} ({l_device_id}) because it is not in remote set.")
                            # Check if the face is still in database memory before trying to delete
                            if l_name in self.database:
                                has_device = any(f.get('device_id', 'admin') == l_device_id for f in self.database[l_name])
                                if has_device:
                                    self.delete_face(l_name, l_device_id)
                                    deleted_count += 1
                        elif l_sync_status == 'pending':
                             # This is a local new face, keep it.
                             logger.info(f"Keeping pending local face: {l_name} ({l_device_id})")
                             pass
                            
                sqlite_conn.close()
                        
                logger.info(f"Sync complete: {count} new, {updated} updated, {deleted_count} deleted")
                return True, f"同步成功: 新增 {count}, 更新 {updated}, 删除 {deleted_count}。本地新录入数据仍保留。"
            else:
                return False, f"HTTP Error: {response.status_code}"
        except Exception as e:
            logger.error(f"Sync faces failed: {e}")
            return False, f"同步失败: {str(e)}"

    def _add_face_sync(self, name, embedding, groups='all', list_type='white'):
        self.add_face(name, embedding, groups=groups, list_type=list_type)

class AsyncDatabaseManager(DatabaseManagerBase):
    def __init__(self, database_path="./dd/face_database.pkl", sqlite_path="./dd/records.db"):
        super().__init__(database_path, sqlite_path)
        self.database = self.load_faces_from_db()
        self.admin_users = self.load_admins_from_db()

    def add_face(self, name, embedding, face_image=None, groups='all', list_type='white', metadata=None, device_id=None):
        if device_id is None:
            device_id = getattr(self, 'device_id', 'admin')
        self._add_face_sync(name, embedding, groups, list_type, metadata, device_id)
        if face_image is not None:
            self.save_face_image(name, face_image, device_id)

    async def add_face_async(self, name, embedding, groups='all', list_type='white', metadata=None, device_id=None):
        if device_id is None:
            device_id = getattr(self, 'device_id', 'admin')
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            await loop.run_in_executor(executor, self._add_face_sync, name, embedding, groups, list_type, metadata, device_id)

    def _add_face_sync(self, name, embedding, groups='all', list_type='white', metadata=None, device_id=None):
        if device_id is None:
            device_id = getattr(self, 'device_id', 'admin')
        try:
            if name not in self.database:
                self.database[name] = []
            
            # Remove existing face for this device_id
            self.database[name] = [f for f in self.database[name] if f['device_id'] != device_id]
            
            self.database[name].append({
                'embedding': embedding,
                'groups': groups,
                'list_type': list_type,
                'metadata': metadata or {},
                'device_id': device_id
            })
            self.add_face_to_db(name, embedding, groups, list_type, metadata, device_id, sync_status='pending')
            self.add_system_log("INFO", f"Added face for user: {name} (Device: {device_id})", "FaceManager")
        except Exception as e:
            logger.error(f"Failed to add face: {e}")
            raise e

    async def delete_face_async(self, name, device_id=None):
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            return await loop.run_in_executor(executor, self._delete_face_sync, name, device_id)

    def _delete_face_sync(self, name, device_id=None):
        if name in self.database:
            if device_id:
                self.database[name] = [f for f in self.database[name] if f['device_id'] != device_id]
                self.delete_face_image(name, device_id)
                self.delete_face_from_db(name, device_id)
                if not self.database[name]:
                    del self.database[name]
                    if name in self.admin_users:
                        self.admin_users.remove(name)
                        self.remove_admin_db(name)
                self.add_system_log("INFO", f"Deleted face for user: {name} (Device: {device_id})", "FaceManager")
                return True
            else:
                for f in self.database[name]:
                    self.delete_face_image(name, f['device_id'])
                del self.database[name]
                if name in self.admin_users:
                    self.admin_users.remove(name)
                    self.remove_admin_db(name)
                self.delete_face_from_db(name)
                self.add_system_log("INFO", f"Deleted all faces for user: {name}", "FaceManager")
                return True
        return False

    def delete_face(self, name, device_id=None):
        return self._delete_face_sync(name, device_id)

    def get_all_names(self):
        return list(self.database.keys())

    def name_exists(self, name):
        return name in self.database

    async def set_as_admin_async(self, name):
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            return await loop.run_in_executor(executor, self._set_as_admin_sync, name)

    def _set_as_admin_sync(self, name):
        if name in self.database:
            self.admin_users.add(name)
            self.set_admin_db(name)
            self.add_system_log("INFO", f"Set user as admin: {name}", "AuthManager")
            return True
        return False

    def set_as_admin(self, name):
        return self._set_as_admin_sync(name)

    def remove_admin(self, name):
        return self._remove_admin_sync(name)

    def is_admin(self, name):
        return name in self.admin_users

    async def remove_admin_async(self, name):
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            return await loop.run_in_executor(executor, self._remove_admin_sync, name)

    def _remove_admin_sync(self, name):
        if name in self.admin_users:
            self.admin_users.remove(name)
            self.remove_admin_db(name)
            self.add_system_log("INFO", f"Removed admin rights from: {name}", "AuthManager")
            return True
        return False

    def build_nn_model(self):
        if not self.database:
            return None, []
        embeddings = []
        names = []
        for name, face_list in self.database.items():
            for face in face_list:
                embeddings.append(face['embedding'])
                names.append(name)
        if not embeddings:
            return None, []
        nn_model = NearestNeighbors(n_neighbors=1, metric="cosine")
        nn_model.fit(embeddings)
        return nn_model, names

    async def find_best_match_async(self, embedding, threshold=0.6):
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            return await loop.run_in_executor(executor, self._find_best_match_sync, embedding, threshold)

    def _find_best_match_sync(self, embedding, threshold, device_id=None):
        nn_model, names = self.build_nn_model()
        if nn_model is None:
            return None, 0, None, None
        distances, indices = nn_model.kneighbors([embedding])
        if distances[0][0] < threshold:
            similarity = 1 - distances[0][0]
            name = names[indices[0][0]]
            user_faces = self.database.get(name, [])
            if user_faces:
                 if device_id:
                     for face in user_faces:
                         if face.get('device_id', 'admin') == device_id:
                             return name, similarity, face.get('groups', 'all'), face.get('list_type', 'white')
                 
                 return name, similarity, user_faces[0].get('groups', 'all'), user_faces[0].get('list_type', 'white')
            return name, similarity, 'all', 'white'
        return None, 0, None, None

    def find_best_match(self, embedding, threshold=0.6, device_id=None):
        return self._find_best_match_sync(embedding, threshold, device_id)

    def sync_faces_from_remote(self, host, port):
        # Use sync logic but wrapped if needed, or just block (it's a maintenance task)
        try:
            url = f"http://{host}:{port}/api/face/sync/all?device_id={self.device_id}"
            logger.info(f"AsyncManager: Syncing faces from {url}...")
            response = requests.get(url, timeout=60)
            
            if response.status_code == 200:
                users = response.json()
                count = 0
                updated = 0
                remote_names = set()
                
                for user in users:
                    name = user['name']
                    remote_names.add(name)
                    embedding_list = user['embedding']
                    embedding = np.array(embedding_list, dtype=np.float32)
                    
                    groups = user.get('groups', 'all')
                    list_type = user.get('list_type', 'white')
                    metadata = user.get('metadata', {})
                    is_admin = user.get('is_admin', False)
                    face_image_b64 = user.get('face_image')
                    device_id = user.get('device_id', 'admin')
                    
                    # Check if this face belongs to this device
                    device_ids = [d.strip() for d in device_id.split(',')]
                    if self.device_id not in device_ids:
                        continue
                    
                    exists = self.name_exists(name)
                    
                    # Update Memory
                    if name not in self.database:
                        self.database[name] = []
                    self.database[name] = [f for f in self.database[name] if f['device_id'] != device_id]
                    self.database[name].append({
                        'embedding': embedding,
                        'groups': groups,
                        'list_type': list_type,
                        'metadata': metadata,
                        'device_id': device_id
                    })
                    
                    # Update SQLite
                    self.add_face_to_db(name, embedding, groups, list_type, metadata, device_id, sync_status='synced')
                    
                    # Save Image
                    if face_image_b64:
                        try:
                            img_data = base64.b64decode(face_image_b64)
                            nparr = np.frombuffer(img_data, np.uint8)
                            face_image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                            if face_image is not None:
                                self.save_face_image(name, face_image, device_id)
                        except Exception as ie:
                            logger.error(f"Image save error for {name}: {ie}")
                            
                    # Admin
                    if is_admin:
                        self.set_as_admin(name)
                    else:
                        if self.is_admin(name):
                            self.remove_admin(name)
                            
                    if exists:
                        updated += 1
                    else:
                        count += 1
                        
                # Handle deletions: Remove local faces that are not on the remote server
                # Logic:
                # 1. Get all local faces
                # 2. For each local face, check if it exists in remote list (match name AND device_id)
                # 3. If not in remote list AND sync_status is 'synced', then delete it.
                
                sqlite_conn = sqlite3.connect(self.sqlite_path)
                sqlite_cursor = sqlite_conn.cursor()
                
                # Get all local faces with device_id and sync_status
                sqlite_cursor.execute("SELECT user_name, device_id, sync_status FROM faces")
                local_faces = sqlite_cursor.fetchall() # list of (name, device_id, sync_status)
                
                deleted_count = 0
                
                # Build remote set for fast lookup: (name, device_id)
                remote_face_set = set()
                for user in users:
                    r_name = user['name']
                    r_device_id = user.get('device_id', 'admin')
                    
                    if r_device_id == 'admin':
                        remote_face_set.add((r_name, 'admin'))
                    else:
                        for dev in r_device_id.split(','):
                            remote_face_set.add((r_name, dev.strip()))
                
                for l_name, l_device_id, l_sync_status in local_faces:
                    # Skip if this is our OWN device face that hasn't synced yet (pending)
                    # We should keep it.
                    # But if it is 'synced', and not in remote_face_set, it means it was deleted on server.
                    
                    # Also check if this face actually belongs to us (cleanup from previous bugs)
                    l_device_ids = [d.strip() for d in l_device_id.split(',')]
                    belongs_to_us = self.device_id in l_device_ids
                    
                    if not belongs_to_us or (l_name, l_device_id) not in remote_face_set:
                        # Special check: If server sent back 'admin', it covers all devices for that user if we want,
                        # but in our new schema, 'admin' is just a device_id.
                        
                        if l_sync_status == 'synced':
                            # Check if the face is still in database memory before trying to delete
                            if l_name in self.database:
                                has_device = any(f.get('device_id', 'admin') == l_device_id for f in self.database[l_name])
                                if has_device:
                                    self.delete_face(l_name, l_device_id)
                                    deleted_count += 1
                        elif l_sync_status == 'pending':
                             # This is a local new face, keep it.
                             pass
                            
                sqlite_conn.close()
                        
                logger.info(f"AsyncManager: Sync complete: {count} new, {updated} updated, {deleted_count} deleted")
                return True, f"同步成功: 新增 {count}, 更新 {updated}, 删除 {deleted_count}。本地新录入数据仍保留。"
            else:
                return False, f"HTTP Error: {response.status_code}"
        except Exception as e:
            logger.error(f"Sync faces failed: {e}")
            return False, f"同步失败: {str(e)}"
