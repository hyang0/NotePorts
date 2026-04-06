#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NotePorts - Windows Port Monitor
Main features:
1. Monitor host TCP ports using psutil
2. Visualize port usage status
"""

import psutil
import json
import re
import sqlite3
import shutil
from flask import Flask, render_template, jsonify, request
from collections import defaultdict
import logging
from datetime import datetime, timedelta
import os
import socket
import time
from functools import lru_cache
import argparse
import fcntl

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Config file paths
CONFIG_DIR = os.path.join(os.getcwd(), 'config')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'config.json')
DB_FILE = os.path.join(CONFIG_DIR, 'noteports.db')

def init_config():
    """Initialize configuration file"""
    import shutil
    
    # Ensure config directory exists
    os.makedirs(CONFIG_DIR, exist_ok=True)
    
    # Initialize main config file
    if not os.path.exists(CONFIG_FILE):
        # Create default config if not exists
        default_config = {
            "Remote Login": 22,
            "HTTP": 80,
            "HTTPS": 443,
            "MySQL Database": 3306,
            "PostgreSQL Database": 5432,
            "Redis Cache": 6379,
            "MongoDB Database": 27017,
            "Elasticsearch": 9200,
            "NotePorts": 7577
        }
        
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, indent=2, ensure_ascii=False)
        
        print(f"Config file created (default): {CONFIG_FILE}")
    else:
        print(f"Config file exists: {CONFIG_FILE}")

def load_config():
    """Load config from SQLite, returns {service_name: port} format for API compatibility"""
    config = {}
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT port, service_name FROM services')
        rows = cursor.fetchall()
        conn.close()

        for port, service_name in rows:
            config[service_name] = port

        return config
    except Exception as e:
        logger.error(f"Failed to load config from SQLite: {e}")
        return {}

def save_config(config):
    """Save config to SQLite (full config replace)"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # Use transaction for atomicity
        cursor.execute('BEGIN TRANSACTION')
        cursor.execute('DELETE FROM services')

        for service_name, port in config.items():
            # Validate service name
            if re.search(r'[<>]', service_name):
                logger.warning(f"Skipping invalid service name (potential injection): {service_name}")
                continue

            # Handle port conversion
            if isinstance(port, str):
                try:
                    port = int(port)
                except ValueError:
                    logger.warning(f"Skipping invalid port for {service_name}: {port}")
                    continue
            if not (isinstance(port, int) and 1 <= port <= 65535):
                logger.warning(f"Skipping invalid port for {service_name}: {port}")
                continue

            cursor.execute('''
                INSERT INTO services (port, service_name) VALUES (?, ?)
            ''', (port, service_name))

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Failed to save config: {e}")
        return False

def atomic_update_config(update_func):
    """Atomically update config with file lock to prevent race conditions"""
    import tempfile

    # Use lock file for synchronization
    lock_file = CONFIG_FILE + '.lock'
    lock_fd = os.open(lock_file, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        # Read current config
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                raw_config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            raw_config = {}

        # Process raw config
        current_config = {}
        for key, value in raw_config.items():
            if re.search(r'[<>]', key):
                continue
            port = None
            if isinstance(value, int):
                port = value
            elif isinstance(value, str):
                try:
                    port = int(value)
                except ValueError:
                    pass
            elif isinstance(value, dict):
                port = value.get('port')
            if port is not None and isinstance(port, int) and 1 <= port <= 65535:
                current_config[key] = port

        # Apply update function
        new_config = update_func(current_config)

        # Write to temp file first
        temp_fd, temp_path = tempfile.mkstemp(dir=CONFIG_DIR, suffix='.json')
        try:
            with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                json.dump(new_config, f, indent=2, ensure_ascii=False)
            # Atomic rename
            os.replace(temp_path, CONFIG_FILE)
        except:
            # Clean up temp file on error
            try:
                os.unlink(temp_path)
            except:
                pass
            raise

        return new_config
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def init_db():
    """Initialize SQLite database and create table"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Create table with port as primary key
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS services (
            port INTEGER PRIMARY KEY,
            service_name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()


def migrate_json_to_db():
    """Migrate existing JSON data to SQLite if database is empty"""
    # Check if database already has data
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM services')
    count = cursor.fetchone()[0]
    conn.close()

    if count > 0:
        # Already has data, no migration needed
        return True

    # Load data from JSON
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            json_config = json.load(f)
    except Exception as e:
        logger.error(f"Failed to read JSON for migration: {e}")
        return False

    # Migrate to SQLite
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    migrated = 0
    for service_name, port in json_config.items():
        # Handle port conversion
        if isinstance(port, str):
            try:
                port = int(port)
            except ValueError:
                continue
        if not (isinstance(port, int) and 1 <= port <= 65535):
            continue
        # Validate service name
        if re.search(r'[<>]', service_name):
            continue

        # Insert, port primary key handles conflicts automatically
        cursor.execute('''
            INSERT OR REPLACE INTO services (port, service_name)
            VALUES (?, ?)
        ''', (port, service_name))
        migrated += 1

    conn.commit()
    conn.close()

    # Backup original JSON file
    if os.path.exists(CONFIG_FILE):
        backup_file = CONFIG_FILE + '.bak'
        shutil.copy2(CONFIG_FILE, backup_file)
        logger.info(f"Original JSON config backed up to: {backup_file}")

    logger.info(f"Migration completed: {migrated} entries migrated")
    return True


# Initialize config
init_config()
init_db()
migrate_json_to_db()
config = load_config()

class PortMonitor:
    """Port Monitor Class"""

    def __init__(self):
        # Default port service mapping
        self.default_ports = {
            21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS", 80: "HTTP",
            110: "POP3", 135: "RPC", 139: "NetBIOS Session", 143: "IMAP", 443: "HTTPS",
            445: "SMB", 1433: "SQL Server", 1521: "Oracle", 3306: "MySQL", 3389: "RDP",
            5432: "PostgreSQL", 5900: "VNC", 6379: "Redis", 8080: "HTTP Proxy",
            8443: "HTTPS Alt", 9200: "Elasticsearch", 27017: "MongoDB"
        }
        # Load port cache from SQLite (port -> service_name)
        self.port_cache = self._load_port_cache()

    def _load_port_cache(self):
        """Load all port-service mappings from SQLite into memory cache"""
        cache = {}
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute('SELECT port, service_name FROM services')
            rows = cursor.fetchall()
            for port, service_name in rows:
                cache[port] = service_name
            conn.close()
        except Exception as e:
            logger.error(f"Failed to load port cache: {e}")
        return cache

    def refresh_cache(self):
        """Refresh cache after config update"""
        self.port_cache = self._load_port_cache()

    def get_host_ports(self):
        """Get host TCP ports using psutil"""
        port_info = {}

        try:
            # Get all network connections
            connections = psutil.net_connections(kind='tcp')

            for conn in connections:
                # We only care about LISTENING ports
                if conn.status == psutil.CONN_LISTEN:
                    port = conn.laddr.port

                    # Get process info if available
                    pid = conn.pid
                    process_name = "Unknown"
                    try:
                        if pid:
                            process = psutil.Process(pid)
                            process_name = process.name()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                    if port not in port_info:
                        port_info[port] = {
                            'port': port,
                            'protocol': 'TCP',
                            'service_name': self.get_service_name(port),
                            'process': process_name,
                            'pid': pid
                        }

        except Exception as e:
            logger.error(f"Failed to get host ports: {e}")

        return port_info

    def get_service_name(self, port):
        """Get service name based on port"""
        # Get from cache first (loaded from SQLite)
        if port in self.port_cache:
            return self.port_cache[port]

        if port in self.default_ports:
            return self.default_ports[port]

        return 'Unknown Service'
    
    def get_port_analysis(self, start_port=1, end_port=65535):
        """Analyze port usage and generate data"""
        host_ports_info = self.get_host_ports()
        
        port_cards = []
        
        # Filter and sort ports
        sorted_ports = sorted(host_ports_info.keys())
        
        for port in sorted_ports:
            if port < start_port or port > end_port:
                continue
                
            info = host_ports_info[port]
            
            card_data = {
                'port': port,
                'type': 'used',
                'source': 'system',
                'protocol': 'TCP',
                'service_name': info['service_name'],
                'process': info['process'],
                'pid': info['pid']
            }
            port_cards.append(card_data)
        
        return {
            'port_cards': port_cards,
            'total_used': len(port_cards),
            'tcp_used': len(port_cards),
            'udp_used': 0
        }

# Create monitor instance
port_monitor = PortMonitor()

@app.route('/')
def index():
    """Index page"""
    return render_template('index.html')

@app.route('/api/ports')
def api_ports():
    """Get ports info API"""
    try:
        # Get port range params
        start_port = request.args.get('start_port', '1')
        end_port = request.args.get('end_port', '65535')
        
        try:
            start_port = int(start_port)
            end_port = int(end_port)
            if start_port < 1: start_port = 1
            if end_port > 65535: end_port = 65535
            if start_port > end_port: start_port, end_port = end_port, start_port
        except ValueError:
            start_port = 1
            end_port = 65535
        
        port_data = port_monitor.get_port_analysis(start_port=start_port, end_port=end_port)
        
        # Search functionality
        search = request.args.get('search', '').strip().lower()
        if search:
            filtered_cards = []
            for card in port_data['port_cards']:
                searchable_text = ' '.join([
                    str(card.get('port', '')),
                    str(card.get('process', '')),
                    str(card.get('service_name', '')),
                    str(card.get('pid', ''))
                ]).lower()
                
                if search in searchable_text:
                    filtered_cards.append(card)
            
            port_data['port_cards'] = filtered_cards
            port_data['total_used'] = len(filtered_cards)
        
        return jsonify({
            'success': True,
            'data': port_data
        })
    except Exception as e:
        logger.error(f"API call failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/config')
def api_get_config():
    """Get config API"""
    try:
        return jsonify(config)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/config', methods=['POST'])
def api_save_config():
    """Save config API"""
    global config
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid data'}), 400

        # Check if it's a batch update (dictionary of configs in {service_name: port} format)
        if isinstance(data, dict) and not ('port' in data and 'service_name' in data):
            # Batch update - replace all config
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()

            # Use transaction for atomicity
            cursor.execute('BEGIN TRANSACTION')
            cursor.execute('DELETE FROM services')

            for service_name, value in data.items():
                # Validate service name
                if re.search(r'[<>]', service_name):
                    logger.warning(f"Skipping invalid service name (potential injection): {service_name}")
                    continue

                # Handle port conversion
                port = None
                if isinstance(value, int):
                    port = value
                elif isinstance(value, str):
                    try:
                        port = int(value)
                    except ValueError:
                        pass
                elif isinstance(value, dict) and 'port' in value:
                    port = value.get('port')

                if port is not None and isinstance(port, int) and 1 <= port <= 65535:
                    cursor.execute('''
                        INSERT INTO services (port, service_name) VALUES (?, ?)
                    ''', (port, service_name))
                else:
                    logger.warning(f"Skipping invalid port for {service_name}: {port}")

            conn.commit()
            conn.close()

            # Refresh global config and cache
            config = load_config()
            port_monitor.refresh_cache()
            return jsonify({'success': True, 'message': 'Config saved'})

        # Single port update - much simpler with port as primary key
        if 'port' in data and 'service_name' in data:
            port = data['port']
            service_name = data['service_name'].strip()

            if not service_name:
                return jsonify({'error': 'Service name cannot be empty'}), 400

            # Validate service name - allow Chinese, English, numbers, and most symbols
            # Only block < > which can be used for HTML tag injection (XSS)
            if re.search(r'[<>]', service_name):
                return jsonify({'error': 'Invalid service name. Disallowed characters: < >'}), 400

            if not isinstance(port, int) or port < 1 or port > 65535:
                return jsonify({'error': 'Invalid port number'}), 400

            # Use SQLite transaction - atomic upsert
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO services (port, service_name, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            ''', (port, service_name))
            conn.commit()
            conn.close()

            # Refresh global config and cache
            config = load_config()
            port_monitor.refresh_cache()
            return jsonify({'success': True, 'message': 'Config saved'})
        else:
            return jsonify({'error': 'Invalid request format'}), 400

    except Exception as e:
        logger.error(f"Error saving config: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/refresh')
def api_refresh():
    """Refresh ports API"""
    try:
        port_data = port_monitor.get_port_analysis()
        return jsonify({
            'success': True,
            'data': port_data,
            'message': 'Refreshed'
        })
    except Exception as e:
        logger.error(f"Refresh failed: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

def parse_args():
    """Parse command line args"""
    default_port = int(os.environ.get('NOTEPORTS_PORT', 7577))
    default_host = os.environ.get('NOTEPORTS_HOST', '0.0.0.0')
    default_debug = os.environ.get('NOTEPORTS_DEBUG', '').lower() in ('true', '1', 'yes')
    
    parser = argparse.ArgumentParser(description='NotePorts - Windows Port Monitor')
    parser.add_argument('--port', '-p', type=int, default=default_port,
                        help=f'Web Port (default: {default_port})')
    parser.add_argument('--host', type=str, default=default_host,
                        help=f'Listen Address (default: {default_host})')
    parser.add_argument('--debug', action='store_true', default=default_debug,
                        help='Debug Mode')
    return parser.parse_args()

if __name__ == '__main__':
    args = parse_args()
    
    logger.info("=== NotePorts Starting ===")
    logger.info(f"Address: {args.host}")
    logger.info(f"Port: {args.port}")
    
    try:
        app.run(host=args.host, port=args.port, debug=args.debug)
    except Exception as e:
        logger.error(f"Error: {e}")
        exit(1)
