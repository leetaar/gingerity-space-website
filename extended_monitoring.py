# extended_monitoring.py
import psutil
import subprocess
import sqlite3
import time
import os
import socket
from datetime import datetime, timedelta

class ExtendedMonitoring:
    def __init__(self):
        self.db_path = '/var/www/gingerity.space/monitoring.db'
        self.init_database()
    
    def init_database(self):
        """Inicjalizacja bazy danych SQLite"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                cpu_percent REAL,
                ram_percent REAL,
                disk_percent REAL,
                temperature REAL,
                network_sent_mb REAL,
                network_recv_mb REAL,
                active_connections INTEGER,
                load_avg_1m REAL
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS top_processes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                process_name TEXT,
                cpu_percent REAL,
                memory_mb REAL,
                pid INTEGER
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def get_network_metrics(self):
        """Metryki sieciowe"""
        try:
            net_io = psutil.net_io_counters()
            connections = len(psutil.net_connections())
            
            return {
                'bytes_sent_mb': round(net_io.bytes_sent / 1024 / 1024, 2),
                'bytes_recv_mb': round(net_io.bytes_recv / 1024 / 1024, 2),
                'active_connections': connections
            }
        except Exception as e:
            return {'error': str(e)}
    
    def get_top_processes(self, limit=5):
        """Top procesów CPU i RAM"""
        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info']):
                try:
                    proc_info = proc.info
                    if proc_info['cpu_percent'] is not None:
                        processes.append({
                            'pid': proc_info['pid'],
                            'name': proc_info['name'],
                            'cpu_percent': proc_info['cpu_percent'],
                            'memory_mb': round(proc_info['memory_info'].rss / 1024 / 1024, 1)
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            cpu_top = sorted(processes, key=lambda x: x['cpu_percent'], reverse=True)[:limit]
            ram_top = sorted(processes, key=lambda x: x['memory_mb'], reverse=True)[:limit]
            
            return {
                'top_cpu': cpu_top,
                'top_ram': ram_top
            }
        except Exception as e:
            return {'error': str(e)}
    
    def ping_test(self, target='8.8.8.8'):
        """Test ping"""
        try:
            result = subprocess.run(['ping', '-c', '1', '-W', '3', target], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                lines = result.stdout.split('\n')
                for line in lines:
                    if 'time=' in line:
                        time_part = line.split('time=')[1].split()[0]
                        return {'success': True, 'ping_ms': float(time_part)}
            return {'success': False, 'ping_ms': None}
        except Exception:
            return {'success': False, 'ping_ms': None}
    
    def save_metrics(self, metrics):
        """Zapisz metryki do bazy"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO system_metrics 
                (cpu_percent, ram_percent, disk_percent, temperature, 
                 network_sent_mb, network_recv_mb, active_connections, load_avg_1m)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                metrics.get('cpu_percent', 0),
                metrics.get('memory', {}).get('percent', 0),
                metrics.get('disk', {}).get('percent', 0),
                metrics.get('temperature', 0),
                metrics.get('network', {}).get('bytes_sent_mb', 0),
                metrics.get('network', {}).get('bytes_recv_mb', 0),
                metrics.get('network', {}).get('active_connections', 0),
                os.getloadavg()[0] if hasattr(os, 'getloadavg') else 0
            ))
            
            # Zapisz top procesy
            for proc in metrics.get('processes', {}).get('top_cpu', []):
                cursor.execute('''
                    INSERT INTO top_processes (process_name, cpu_percent, memory_mb, pid)
                    VALUES (?, ?, ?, ?)
                ''', (proc['name'], proc['cpu_percent'], proc['memory_mb'], proc['pid']))
            
            conn.commit()
            
            # Usuń stare dane (7 dni)
            week_ago = datetime.now() - timedelta(days=7)
            cursor.execute('DELETE FROM system_metrics WHERE timestamp < ?', (week_ago,))
            cursor.execute('DELETE FROM top_processes WHERE timestamp < ?', (week_ago,))
            conn.commit()
            conn.close()
            
        except Exception as e:
            print(f"Error saving metrics: {e}")

    def get_extended_metrics(self):
        """Zbierz wszystkie rozszerzone metryki"""
        metrics = {}
        metrics['network'] = self.get_network_metrics()
        metrics['processes'] = self.get_top_processes()
        metrics['ping'] = self.ping_test()
        metrics['load_avg'] = os.getloadavg()[0] if hasattr(os, 'getloadavg') else 0
        
        return metrics

# Singleton
extended_monitor = ExtendedMonitoring()
