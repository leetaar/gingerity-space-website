# app.py (Rozszerzona wersja z nowymi metrykami)

from flask import Flask, render_template, jsonify, Response, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash
import psutil
import subprocess
import os
import time
from datetime import datetime
from dotenv import load_dotenv
from functools import wraps
import concurrent.futures
import threading
import sqlite3
import socket
from datetime import timedelta

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')
if not app.secret_key:
    raise ValueError("SECRET_KEY must be set in environment variables")

CAM_USERS = {
    os.getenv('CAM_ADMIN_USER', 'admin'): os.getenv('CAM_ADMIN_PASS'),
    os.getenv('CAM_MARCIN_USER', 'marcin'): os.getenv('CAM_MARCIN_PASS')
}

PHOTOS_DIR = "/var/www/gingerity.space/static/photos"
os.makedirs(PHOTOS_DIR, exist_ok=True)

# Thread pool for camera operations
camera_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
camera_tasks = {}

# --- Extended Monitoring Class ---

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
                load_avg_1m REAL,
                ping_ms REAL
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
            return {'bytes_sent_mb': 0, 'bytes_recv_mb': 0, 'active_connections': 0}
    
    def get_top_processes(self, limit=5):
        """Top procesów CPU i RAM"""
        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info']):
                try:
                    proc_info = proc.info
                    if proc_info['cpu_percent'] is not None and proc_info['memory_info'] is not None:
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
            return {'top_cpu': [], 'top_ram': []}
    
    def ping_test(self, target='8.8.8.8'):
        """Test ping do Google DNS"""
        try:
            result = subprocess.run(['ping', '-c', '1', '-W', '3', target], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                lines = result.stdout.split('\n')
                for line in lines:
                    if 'time=' in line:
                        time_part = line.split('time=')[1].split()[0]
                        return {'success': True, 'ping_ms': round(float(time_part), 1)}
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
                 network_sent_mb, network_recv_mb, active_connections, load_avg_1m, ping_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                metrics.get('cpu_percent', 0),
                metrics.get('memory', {}).get('percent', 0),
                metrics.get('disk', {}).get('percent', 0),
                metrics.get('temperature', 0),
                metrics.get('network', {}).get('bytes_sent_mb', 0),
                metrics.get('network', {}).get('bytes_recv_mb', 0),
                metrics.get('network', {}).get('active_connections', 0),
                metrics.get('load_avg', 0),
                metrics.get('ping', {}).get('ping_ms', 0)
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

    def get_history(self, hours=24):
        """Pobierz historię metryk"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            time_ago = datetime.now() - timedelta(hours=hours)
            
            cursor.execute('''
                SELECT timestamp, cpu_percent, ram_percent, temperature, ping_ms
                FROM system_metrics 
                WHERE timestamp > ?
                ORDER BY timestamp DESC
                LIMIT 50
            ''', (time_ago,))
            
            rows = cursor.fetchall()
            conn.close()
            
            history = []
            for row in rows:
                history.append({
                    'timestamp': row[0],
                    'cpu_percent': row[1],
                    'ram_percent': row[2], 
                    'temperature': row[3],
                    'ping_ms': row[4]
                })
            
            return history
            
        except Exception as e:
            return []

# Initialize extended monitoring
extended_monitor = ExtendedMonitoring()

# --- Funkcje pomocnicze i Dekoratory ---

def verify_camera_password(username, password):
    if username not in CAM_USERS: return False
    hashed_password = CAM_USERS.get(username)
    if not hashed_password: return False
    return check_password_hash(hashed_password, password)

def camera_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'camera_logged_in' not in session:
            return redirect(url_for('camera_login'))
        return f(*args, **kwargs)
    return decorated_function

def get_system_info():
    """Rozszerzone informacje systemowe"""
    info = {
        'cpu_percent': psutil.cpu_percent(interval=None),
        'memory': psutil.virtual_memory()._asdict(),
        'disk': psutil.disk_usage('/')._asdict(),
        'temperature': 0.0,
        'uptime': "N/A",
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    # Temperatura CPU
    try:
        temp_str = subprocess.check_output(['vcgencmd', 'measure_temp']).decode('utf-8')
        info['temperature'] = float(temp_str.split('=')[1].split('\'')[0])
    except Exception:
        pass
    
    # Uptime
    try:
        uptime_seconds = time.time() - psutil.boot_time()
        hours = int(uptime_seconds // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        info['uptime'] = f"{hours}h {minutes}m"
    except Exception:
        pass
    
    # Rozszerzone metryki
    info['network'] = extended_monitor.get_network_metrics()
    info['processes'] = extended_monitor.get_top_processes()
    info['ping'] = extended_monitor.ping_test()
    info['load_avg'] = round(os.getloadavg()[0], 2) if hasattr(os, 'getloadavg') else 0
    
    # Zapisz metryki do bazy
    extended_monitor.save_metrics(info)
    
    return info

def kill_camera_processes():
    """Kill camera processes asynchronously"""
    try:
        subprocess.run(['pkill', '-f', 'libcamera-vid'], timeout=5)
        time.sleep(0.5)
    except subprocess.TimeoutExpired:
        subprocess.run(['pkill', '-9', '-f', 'libcamera-vid'])

def capture_photo_sync():
    """Synchronous photo capture for thread execution"""
    try:
        kill_camera_processes()
        time.sleep(1)

        filename = f"photo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        filepath = os.path.join(PHOTOS_DIR, filename)
        
        subprocess.run(
            ['libcamera-still', '-o', filepath, '--timeout', '1000', '--width', '1920', '--height', '1080'],
            check=True, capture_output=True, text=True, timeout=10
        )
        return {'success': True, 'filename': filename}
    except subprocess.CalledProcessError as e:
        error_details = e.stderr if e.stderr else str(e)
        return {'success': False, 'error': f'Błąd wykonania libcamera-still: {error_details}'}
    except subprocess.TimeoutExpired:
        return {'success': False, 'error': 'Timeout podczas robienia zdjęcia'}
    except Exception as e:
        return {'success': False, 'error': str(e)}

# --- Główne Trasy Aplikacji ---

@app.route('/')
def dashboard():
    return render_template('dashboard.html')

@app.route('/api/system')
def api_system():
    return jsonify(get_system_info())

@app.route('/api/system/history')
def api_system_history():
    """Historia metryk systemowych"""
    hours = request.args.get('hours', 24, type=int)
    history = extended_monitor.get_history(hours)
    return jsonify(history)

@app.route('/gablotka')
def gablotka():
    return render_template('gablotka.html')

# === TRASY DLA KAMERY (Z POPRAWIONĄ LOGIKĄ) ===

def generate_mjpeg_stream():
    cmd = [
        'libcamera-vid', '--timeout', '0', '--width', '1920', '--height', '1080',
        '--framerate', '20', '--codec', 'mjpeg', '--output', '-', '--nopreview'
    ]
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
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + jpg + b'\r\n')
    except GeneratorExit:
        print("Client disconnected, stopping stream process.")
    finally:
        print("Terminating libcamera-vid process...")
        process.terminate()
        process.wait()

@app.route('/cam/stream')
@camera_login_required
def camera_stream():
    return Response(generate_mjpeg_stream(), mimetype='multipart/x-mixed-replace; boundary=frame')
    
@app.route('/cam/stop_stream')
@camera_login_required
def stop_stream():
    def kill_async():
        try:
            kill_camera_processes()
        except Exception as e:
            print(f"Error stopping stream: {e}")
    
    threading.Thread(target=kill_async).start()
    return jsonify({'success': True})

@app.route('/cam/photo', methods=['POST'])
@camera_login_required
def take_photo():
    task_id = str(int(time.time() * 1000))
    future = camera_executor.submit(capture_photo_sync)
    camera_tasks[task_id] = future
    return jsonify({'success': True, 'task_id': task_id, 'status': 'processing'})

@app.route('/cam/photo_status/<task_id>')
@camera_login_required
def photo_status(task_id):
    if task_id not in camera_tasks:
        return jsonify({'success': False, 'error': 'Task not found'})
    
    future = camera_tasks[task_id]
    if future.done():
        result = future.result()
        del camera_tasks[task_id]  # Cleanup
        return jsonify(result)
    else:
        return jsonify({'success': True, 'status': 'processing'})

@app.route('/cam/login', methods=['GET', 'POST'])
def camera_login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if verify_camera_password(username, password):
            session['camera_logged_in'] = True
            session['camera_user'] = username
            return redirect(url_for('camera'))
        else:
            flash('Nieprawidłowe dane logowania', 'error')
    return render_template('camera_login.html')

@app.route('/cam')
@camera_login_required
def camera():
    return render_template('camera.html')

@app.route('/cam/logout')
def camera_logout():
    session.pop('camera_logged_in', None)
    session.pop('camera_user', None)
    return redirect(url_for('dashboard'))

@app.route('/cam/photos')
@camera_login_required
def list_photos():
    photos = []
    try:
        for filename in sorted(os.listdir(PHOTOS_DIR), reverse=True):
            if filename.lower().endswith('.jpg'):
                path = os.path.join(PHOTOS_DIR, filename)
                photos.append({
                    'filename': filename, 'path': f"/static/photos/{filename}",
                    'size': f"{os.path.getsize(path) / 1024:.1f} KB",
                    'date': datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d %H:%M')
                })
    except Exception as e:
        print(f"Błąd odczytu zdjęć: {e}")
    return jsonify(photos)

@app.route('/static/photos/<path:filename>')
@camera_login_required
def serve_photo(filename):
    # Better path validation
    if '..' in filename or '/' in filename or '\\' in filename:
        return jsonify({'error': 'Invalid filename'}), 400
    return app.send_static_file(f'photos/{filename}')

@app.route('/cam/delete_photo', methods=['POST'])
@camera_login_required
def delete_photo():
    filename = request.json.get('filename')
    # Better path validation
    if not filename or '..' in filename or '/' in filename or '\\' in filename:
        return jsonify({'success': False, 'error': 'Invalid filename'})
    
    filepath = os.path.join(PHOTOS_DIR, filename)
    if os.path.exists(filepath) and os.path.commonpath([PHOTOS_DIR, filepath]) == PHOTOS_DIR:
        os.remove(filepath)
        return jsonify({'success': True, 'message': 'Zdjęcie usunięte.'})
    return jsonify({'success': False, 'error': 'Nie znaleziono pliku.'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)