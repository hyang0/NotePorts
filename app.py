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
from flask import Flask, render_template, jsonify, request
from collections import defaultdict
import logging
from datetime import datetime, timedelta
import os
import socket
import time
from functools import lru_cache
import argparse

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
    """Load config file"""
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            raw_config = json.load(f)
        
        processed_config = {}
        for key, value in raw_config.items():
            # Use key as service name directly
            service_name = key
            
            # Handle value
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

            if port is not None:
                processed_config[service_name] = port
        
        return processed_config
    except Exception as e:
        print(f"Failed to load config: {e}")
        return {}

def save_config(config):
    """Save config file"""
    try:
        raw_config = {}
        for key, value in config.items():
            if isinstance(value, dict) and 'port' in value:
                port = value['port']
                # Save as simple integer key-value pair
                raw_config[key] = port
            else:
                raw_config[key] = value
        
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(raw_config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Failed to save config: {e}")
        return False

# Initialize config
init_config()
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
        # Get from config first
        config_ports = {}
        for k, v in config.items():
            if isinstance(v, int):
                config_ports[k] = v
            elif isinstance(v, dict) and 'port' in v:
                config_ports[k] = v['port']
        
        port_to_service = {v: k for k, v in config_ports.items()}
        
        if port in port_to_service:
            return port_to_service[port]
        
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
        
        # Check if it's a batch update (dictionary of configs)
        if isinstance(data, dict) and not ('port' in data and 'service_name' in data):
            # Validate and process batch update
            new_config = {}
            for key, value in data.items():
                if isinstance(value, int):
                    if 1 <= value <= 65535:
                        new_config[key] = value
                elif isinstance(value, dict) and 'port' in value:
                    port = value['port']
                    if isinstance(port, int) and 1 <= port <= 65535:
                        new_config[key] = port
            
            if save_config(new_config):
                config = load_config()
                return jsonify({'success': True, 'message': 'Config saved'})
            else:
                return jsonify({'error': 'Failed to save config'}), 500

        # Single port update
        if 'port' in data and 'service_name' in data:
            port = data['port']
            service_name = data['service_name'].strip()
            
            if not service_name:
                return jsonify({'error': 'Service name cannot be empty'}), 400
            
            if not isinstance(port, int) or port < 1 or port > 65535:
                return jsonify({'error': 'Invalid port number'}), 400
            
            current_config = load_config()
            
            # Remove existing mapping for this port
            existing_service = None
            for service, config_value in current_config.items():
                # Handle both int and dict config values (migration safety)
                conf_port = config_value
                if isinstance(config_value, dict):
                    conf_port = config_value.get('port')
                
                if conf_port == port:
                    existing_service = service
                    break
            
            if existing_service:
                del current_config[existing_service]
            
            current_config[service_name] = port
            
            if save_config(current_config):
                config = load_config()
                return jsonify({'success': True, 'message': 'Config saved'})
            else:
                return jsonify({'error': 'Failed to save config'}), 500
        else:
            # Full config update not fully implemented in this simplified version
            # But we can allow it if needed, or just support single port update for now.
            # Let's keep it simple for now as the frontend might use it.
            return jsonify({'error': 'Batch update not supported in this version'}), 400
            
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
