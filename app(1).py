# app.py (Finalna, uproszczona wersja, z linkiem do /progress)

from flask import Flask, render_template, jsonify, Response, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash
import psutil
import subprocess
import os
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
from functools import wraps
import sqlite3
import socket

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')
if not app.secret_key:
    raise ValueError("SECRET_KEY must be set in environment variables")

CAM_USERS = {
    os.getenv('CAM_ADMIN_USER', 'admin'): os.getenv('CAM_ADMIN_PASS'),
    os.getenv('CAM_MARCIN_USER', 'marcin'): os.getenv('CAM_MARCIN_PASS')
}

class ExtendedMonitoring:
    def __init__(self):
        self.db_path = '/var/www/gingerity.space/monitoring.db'
        self.init_database()
    
    def init_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, cpu_percent REAL,
                ram_percent REAL, disk_percent REAL, temperature REAL, network_sent_mb REAL,
                network_recv_mb REAL, active_connections INTEGER, load_avg_1m REAL, ping_ms REAL)''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS top_processes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, process_name TEXT,
                cpu_percent REAL, memory_mb REAL, pid INTEGER)''')
        conn.commit()
        conn.close()
    
    def get_network_metrics(self):
        try:
            net_io = psutil.net_io_counters()
            return {
                'bytes_sent_mb': round(net_io.bytes_sent / 1024 / 1024, 2),
                'bytes_recv_mb': round(net_io.bytes_recv / 1024 / 1024, 2),
                'active_connections': len(psutil.net_connections())}
        except Exception:
            return {'bytes_sent_mb': 0, 'bytes_recv_mb': 0, 'active_connections': 0}
    
    def get_top_processes(self, limit=5):
        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info']):
                try:
                    proc_info = proc.info
                    if proc_info['cpu_percent'] is not None and proc_info['memory_info'] is not None:
                        processes.append({
                            'pid': proc_info['pid'], 'name': proc_info['name'], 'cpu_percent': proc_info['cpu_percent'],
                            'memory_mb': round(proc_info['memory_info'].rss / 1024 / 1024, 1)})
                except (psutil.NoSuchProcess, psutil.AccessDenied): continue
            return {
                'top_cpu': sorted(processes, key=lambda x: x['cpu_percent'], reverse=True)[:limit],
                'top_ram': sorted(processes, key=lambda x: x['memory_mb'], reverse=True)[:limit]}
        except Exception:
            return {'top_cpu': [], 'top_ram': []}
    
    def ping_test(self, target='8.8.8.8'):
        try:
            result = subprocess.run(['ping', '-c', '1', '-W', '3', target], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'time=' in line:
                        return {'success': True, 'ping_ms': round(float(line.split('time=')[1].split()[0]), 1)}
            return {'success': False, 'ping_ms': None}
        except Exception:
            return {'success': False, 'ping_ms': None}

    def save_metrics(self, metrics):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('INSERT INTO system_metrics (cpu_percent, ram_percent, disk_percent, temperature, network_sent_mb, network_recv_mb, active_connections, load_avg_1m, ping_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',(
                metrics.get('cpu_percent', 0), metrics.get('memory', {}).get('percent', 0), metrics.get('disk', {}).get('percent', 0), metrics.get('temperature', 0),
                metrics.get('network', {}).get('bytes_sent_mb', 0), metrics.get('network', {}).get('bytes_recv_mb', 0),
                metrics.get('network', {}).get('active_connections', 0), metrics.get('load_avg', 0), metrics.get('ping', {}).get('ping_ms', 0)))
            for proc in metrics.get('processes', {}).get('top_cpu', []):
                cursor.execute('INSERT INTO top_processes (process_name, cpu_percent, memory_mb, pid) VALUES (?, ?, ?, ?)',
                               (proc['name'], proc['cpu_percent'], proc['memory_mb'], proc['pid']))
            conn.commit()
            week_ago = datetime.now() - timedelta(days=7)
            cursor.execute('DELETE FROM system_metrics WHERE timestamp < ?', (week_ago,))
            cursor.execute('DELETE FROM top_processes WHERE timestamp < ?', (week_ago,))
            conn.commit()
            conn.close()
        except Exception as e: print(f"Error saving metrics: {e}")

    def get_history(self, hours=24):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            time_ago = datetime.now() - timedelta(hours=hours)
            cursor.execute('''
                SELECT
                    strftime('%Y-%m-%d %H:00:00', timestamp) as hour,
                    AVG(cpu_percent),
                    AVG(ram_percent),
                    AVG(temperature)
                FROM system_metrics
                WHERE timestamp > ?
                GROUP BY hour
                ORDER BY hour ASC
            ''', (time_ago,))
            rows = cursor.fetchall()
            conn.close()
            return [{'timestamp': r[0], 'cpu_percent': round(r[1] or 0, 1), 'ram_percent': round(r[2] or 0, 1), 'temperature': round(r[3] or 0, 1)} for r in rows]
        except Exception as e:
            print(f"Error getting history: {e}")
            return []

extended_monitor = ExtendedMonitoring()

def verify_camera_password(username, password):
    if username not in CAM_USERS: return False
    hashed_password = CAM_USERS.get(username)
    if not hashed_password: return False
    return check_password_hash(hashed_password, password)

def camera_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'camera_logged_in' not in session: return redirect(url_for('camera_login'))
        return f(*args, **kwargs)
    return decorated_function

def get_system_info():
    info = {
        'cpu_percent': psutil.cpu_percent(interval=None), 'memory': psutil.virtual_memory()._asdict(),
        'disk': psutil.disk_usage('/')._asdict(), 'temperature': 0.0, 'uptime': "N/A",
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    try: info['temperature'] = float(subprocess.check_output(['vcgencmd', 'measure_temp']).decode('utf-8').split('=')[1].split('\'')[0])
    except Exception: pass
    try:
        uptime_seconds = time.time() - psutil.boot_time()
        info['uptime'] = f"{int(uptime_seconds // 3600)}h {int((uptime_seconds % 3600) // 60)}m"
    except Exception: pass
    info['network'] = extended_monitor.get_network_metrics()
    info['processes'] = extended_monitor.get_top_processes()
    info['ping'] = extended_monitor.ping_test()
    info['load_avg'] = round(os.getloadavg()[0], 2) if hasattr(os, 'getloadavg') else 0
    extended_monitor.save_metrics(info)
    return info

def kill_camera_processes():
    try:
        subprocess.run(['pkill', '-f', 'libcamera-vid'], timeout=5)
    except Exception as e:
        print(f"Error killing camera process: {e}")

@app.route('/')
def dashboard(): return render_template('dashboard.html')

@app.route('/api/system')
def api_system(): return jsonify(get_system_info())

@app.route('/api/system/history')
def api_system_history():
    hours = request.args.get('hours', 24, type=int)
    return jsonify(extended_monitor.get_history(hours))

# ZMIENIONA TRASA DLA STRONY Z POSTĘPAMI
@app.route('/progress')
def progress():
    return render_template('progress.html')

def generate_mjpeg_stream():
    cmd = ['libcamera-vid', '--timeout', '0', '--width', '1920', '--height', '1080', '--framerate', '20', '--codec', 'mjpeg', '--output', '-', '--nopreview']
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        byte_stream = b''
        while True:
            byte_stream += process.stdout.read(4096)
            a = byte_stream.find(b'\xff\xd8')
            b = byte_stream.find(b'\xff\xd9')
            if a != -1 and b != -1:
                jpg = byte_stream[a:b+2]
                byte_stream = byte_stream[b+2:]
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpg + b'\r\n')
    except GeneratorExit:
        print("Client disconnected, stopping stream process.")
    finally:
        print("Terminating libcamera-vid process...")
        process.terminate()
        process.wait()

@app.route('/cam/stream')
@camera_login_required
def camera_stream(): return Response(generate_mjpeg_stream(), mimetype='multipart/x-mixed-replace; boundary=frame')
    
@app.route('/cam/stop_stream', methods=['GET', 'POST'])
@camera_login_required
def stop_stream():
    kill_camera_processes()
    return jsonify({'success': True})

@app.route('/cam/login', methods=['GET', 'POST'])
def camera_login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if verify_camera_password(username, password):
            session['camera_logged_in'] = True
            session['camera_user'] = username
            return redirect(url_for('camera'))
        else: flash('Nieprawidłowe dane logowania', 'error')
    return render_template('camera_login.html')

@app.route('/cam')
@camera_login_required
def camera(): return render_template('camera.html')

@app.route('/cam/logout')
def camera_logout():
    session.pop('camera_logged_in', None)
    session.pop('camera_user', None)
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
