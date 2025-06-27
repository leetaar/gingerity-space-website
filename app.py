from flask import Flask, render_template, jsonify, Response, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash # POPRAWIONY IMPORT
import psutil
import subprocess
import os
import time
from datetime import datetime
from dotenv import load_dotenv

import smtplib
import requests
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta


# Cache dla alertów (żeby nie spamować)
alert_cache = {}
ALERT_COOLDOWN = 300  # 5 minut między alertami tego samego typu

def check_alerts(system_data):
    """Sprawdza progi alertów"""
    if not os.getenv('ALERTS_ENABLED', 'false').lower() == 'true':
        return
    
    alerts = []
    
    # Sprawdź temperaturę
    temp = system_data.get('temperature', 0)
    temp_warn = float(os.getenv('TEMP_WARNING', '70'))
    temp_crit = float(os.getenv('TEMP_CRITICAL', '80'))
    
    if temp >= temp_crit:
        if should_send_alert('temp_critical'):
            alerts.append({
                'type': 'critical',
                'title': 'KRYTYCZNA TEMPERATURA',
                'message': f'🔥 Temperatura CPU: {temp}°C (próg: {temp_crit}°C)',
                'value': temp,
                'threshold': temp_crit
            })
    elif temp >= temp_warn:
        if should_send_alert('temp_warning'):
            alerts.append({
                'type': 'warning', 
                'title': 'Wysoka temperatura',
                'message': f'⚠️ Temperatura CPU: {temp}°C (próg: {temp_warn}°C)',
                'value': temp,
                'threshold': temp_warn
            })
    
    # Sprawdź CPU
    cpu = system_data.get('cpu_percent', 0)
    cpu_warn = float(os.getenv('CPU_WARNING', '80'))
    cpu_crit = float(os.getenv('CPU_CRITICAL', '95'))
    
    if cpu >= cpu_crit:
        if should_send_alert('cpu_critical'):
            alerts.append({
                'type': 'critical',
                'title': 'KRYTYCZNE OBCIĄŻENIE CPU',
                'message': f'🔥 Użycie CPU: {cpu}% (próg: {cpu_crit}%)',
                'value': cpu,
                'threshold': cpu_crit
            })
    elif cpu >= cpu_warn:
        if should_send_alert('cpu_warning'):
            alerts.append({
                'type': 'warning',
                'title': 'Wysokie obciążenie CPU',
                'message': f'⚠️ Użycie CPU: {cpu}% (próg: {cpu_warn}%)',
                'value': cpu,
                'threshold': cpu_warn
            })
    
    # Sprawdź pamięć
    memory_percent = system_data.get('memory', {}).get('percent', 0)
    mem_warn = float(os.getenv('MEMORY_WARNING', '85'))
    mem_crit = float(os.getenv('MEMORY_CRITICAL', '95'))
    
    if memory_percent >= mem_crit:
        if should_send_alert('memory_critical'):
            alerts.append({
                'type': 'critical',
                'title': 'KRYTYCZNE UŻYCIE PAMIĘCI',
                'message': f'🔥 Użycie RAM: {memory_percent}% (próg: {mem_crit}%)',
                'value': memory_percent,
                'threshold': mem_crit
            })
    elif memory_percent >= mem_warn:
        if should_send_alert('memory_warning'):
            alerts.append({
                'type': 'warning',
                'title': 'Wysokie użycie pamięci',
                'message': f'⚠️ Użycie RAM: {memory_percent}% (próg: {mem_warn}%)',
                'value': memory_percent,
                'threshold': mem_warn
            })
    
    # Sprawdź dysk
    disk_percent = system_data.get('disk', {}).get('percent', 0)
    disk_warn = float(os.getenv('DISK_WARNING', '85'))
    disk_crit = float(os.getenv('DISK_CRITICAL', '95'))
    
    if disk_percent >= disk_crit:
        if should_send_alert('disk_critical'):
            alerts.append({
                'type': 'critical',
                'title': 'KRYTYCZNE ZAPEŁNIENIE DYSKU',
                'message': f'🔥 Użycie dysku: {disk_percent}% (próg: {disk_crit}%)',
                'value': disk_percent,
                'threshold': disk_crit
            })
    elif disk_percent >= disk_warn:
        if should_send_alert('disk_warning'):
            alerts.append({
                'type': 'warning',
                'title': 'Wysokie zapełnienie dysku',
                'message': f'⚠️ Użycie dysku: {disk_percent}% (próg: {disk_warn}%)',
                'value': disk_percent,
                'threshold': disk_warn
            })
    
    # Wyślij alerty
    for alert in alerts:
        send_alert(alert)

def should_send_alert(alert_key):
    """Sprawdza czy alert nie jest w cooldown"""
    global alert_cache
    current_time = datetime.now()
    
    if alert_key in alert_cache:
        last_sent = alert_cache[alert_key]
        if (current_time - last_sent).seconds < ALERT_COOLDOWN:
            return False
    
    alert_cache[alert_key] = current_time
    return True

def send_alert(alert):
    """Wysyła alert (email/discord/telegram)"""
    def send_async():
        try:
            print(f"🚨 ALERT: {alert['message']}")
            send_email_alert(alert)
            send_discord_alert(alert)
        except Exception as e:
            print(f"Błąd wysyłania alertu: {e}")
    
    threading.Thread(target=send_async).start()

def send_email_alert(alert):
    """Wysyła alert przez email"""
    smtp_server = os.getenv('SMTP_SERVER')
    smtp_user = os.getenv('SMTP_USER')
    smtp_pass = os.getenv('SMTP_PASS')
    alert_email = os.getenv('ALERT_EMAIL')
    
    if not all([smtp_server, smtp_user, smtp_pass, alert_email]):
        return
    
    try:
        msg = MIMEMultipart()
        msg['From'] = smtp_user
        msg['To'] = alert_email
        msg['Subject'] = f"🚨 [Raspberry Pi] {alert['title']}"
        
        body = f"""
Alert z GINGERITY (gingerity.space):

{alert['message']}

📊 Szczegóły:
- Wartość: {alert['value']}
- Próg: {alert['threshold']}
- Czas: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- Typ: {alert['type'].upper()}

🔗 Dashboard: https://gingerity.space
📹 Kamera: https://gingerity.space/cam

---
Raspberry Pi Alert System
        """
        
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP(smtp_server, int(os.getenv('SMTP_PORT', '587')))
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        
        print(f"✅ Email alert sent: {alert['title']}")
    except Exception as e:
        print(f"❌ Email alert failed: {e}")

def send_discord_alert(alert):
    """Wysyła alert na Discord"""
    webhook_url = os.getenv('DISCORD_WEBHOOK')
    if not webhook_url:
        return
    
    try:
        color = 0xff0000 if alert['type'] == 'critical' else 0xffa500
        
        data = {
            "embeds": [{
                "title": f"🚨 {alert['title']}",
                "description": alert['message'],
                "color": color,
                "fields": [
                    {"name": "📊 Wartość", "value": f"`{alert['value']}`", "inline": True},
                    {"name": "🎯 Próg", "value": f"`{alert['threshold']}`", "inline": True},
                    {"name": "⏰ Czas", "value": datetime.now().strftime('%H:%M:%S'), "inline": True}
                ],
                "footer": {
                    "text": "GINGERITY",
                    "icon_url": "https://cdn.jsdelivr.net/gh/devicons/devicon/icons/raspberrypi/raspberrypi-original.svg"
                },
                "timestamp": datetime.now().isoformat()
            }],
            "components": [{
                "type": 1,
                "components": [{
                    "type": 2,
                    "style": 5,
                    "label": "🔗 Otwórz Dashboard",
                    "url": "https://gingerity.space"
                }]
            }]
        }
        
        response = requests.post(webhook_url, json=data, timeout=10)
        print(f"✅ Discord alert sent: {alert['title']}")
    except Exception as e:
        print(f"❌ Discord alert failed: {e}")

# Załaduj zmienne z .env
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'fallback-secret-key-change-this')

# Konfiguracja użytkowników z .env
CAM_USERS = {
    os.getenv('CAM_ADMIN_USER', 'admin'): os.getenv('CAM_ADMIN_PASS', 'admin123'),
    os.getenv('CAM_MARCIN_USER', 'marcin'): os.getenv('CAM_MARCIN_PASS', 'raspberry2025')
}

# Konfiguracja kamery
STREAM_WIDTH = int(os.getenv('STREAM_WIDTH', '1280'))
STREAM_HEIGHT = int(os.getenv('STREAM_HEIGHT', '720'))
STREAM_FPS = int(os.getenv('STREAM_FPS', '15'))
STREAM_QUALITY = int(os.getenv('STREAM_QUALITY', '90'))
CAMERA_WIDTH = int(os.getenv('CAMERA_WIDTH', '1280'))
CAMERA_HEIGHT = int(os.getenv('CAMERA_HEIGHT', '720'))
CAMERA_QUALITY = int(os.getenv('CAMERA_QUALITY', '90'))
PHOTOS_MAX = int(os.getenv('PHOTOS_MAX', '20'))

# Katalog na zdjęcia
PHOTOS_DIR = "/home/marcin/dashboard/static/photos"
os.makedirs(PHOTOS_DIR, exist_ok=True)

# Zmienne dla streamu
streaming = False

def verify_camera_password(username, password):
    """Weryfikacja dostępu do kamery przy użyciu hashy"""
    if username not in CAM_USERS:
        return False

    # Pobierz zahashowane hasło z konfiguracji
    hashed_password = CAM_USERS[username]

    # Porównaj podane hasło z hashem
    return check_password_hash(hashed_password, password)

def camera_login_required(f):
    """Dekorator wymagający logowania do kamery"""
    def decorated_function(*args, **kwargs):
        if 'camera_logged_in' not in session or not session['camera_logged_in']:
            return redirect(url_for('camera_login'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

def get_system_info():
    """Pobiera informacje o systemie"""
    basic_info = {
        'cpu_percent': psutil.cpu_percent(interval=1),
        'memory': {
            'total': round(psutil.virtual_memory().total / (1024**3), 2),
            'used': round(psutil.virtual_memory().used / (1024**3), 2),
            'percent': psutil.virtual_memory().percent
        },
        'disk': {
            'total': round(psutil.disk_usage('/').total / (1024**3), 2),
            'used': round(psutil.disk_usage('/').used / (1024**3), 2),
            'percent': round((psutil.disk_usage('/').used / psutil.disk_usage('/').total) * 100, 2)
        },
        'temperature': get_cpu_temperature(),
        'uptime': get_uptime(),
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'camera_status': check_camera_status(),
        'camera_logged_in': session.get('camera_logged_in', False),
        'camera_user': session.get('camera_user', '')
    }

    threading.Thread(target=lambda: check_alerts(basic_info.copy())).start()
    
    return basic_info

def get_cpu_temperature():
    """Pobiera temperaturę CPU"""
    try:
        result = subprocess.run(['vcgencmd', 'measure_temp'], capture_output=True, text=True)
        temp = result.stdout.strip().replace('temp=', '').replace("'C", '')
        return float(temp)
    except:
        return 0

def get_uptime():
    """Pobiera czas działania systemu"""
    try:
        with open('/proc/uptime', 'r') as f:
            uptime_seconds = float(f.readline().split()[0])
        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        return f"{days}d {hours}h {minutes}m"
    except:
        return "Nieznany"

def check_camera_status():
    """Sprawdza czy kamera jest dostępna"""
    try:
        result = subprocess.run(['libcamera-hello', '--list-cameras'], 
                                 capture_output=True, text=True, timeout=3)
        return 'Available cameras' in result.stdout
    except:
        return False

def generate_mjpeg_stream():
    """Generator MJPEG z libcamera-vid - 2K wysoka jakość"""
    global streaming
    
    cmd = [
        'libcamera-vid',
        '--timeout', '0',           
        '--width', '2560',          # 2K rozdzielczość
        '--height', '1440',         # 16:9 QHD
        '--framerate', '25',        # 25 FPS dla jakości
        '--codec', 'mjpeg',         
        '--quality', '95',          # Bardzo wysoka jakość
        '--output', '-',            
        '--nopreview',
        '--denoise', 'cdn_off',
        '--bitrate', '15000000'     # 15 Mbps dla 2K
    ]
    
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        buffer = b''
        
        while streaming:
            chunk = process.stdout.read(4096)
            if not chunk:
                break
                
            buffer += chunk
            
            while True:
                start = buffer.find(b'\xff\xd8')
                if start == -1:
                    break
                    
                end = buffer.find(b'\xff\xd9', start)
                if end == -1:
                    break
                    
                jpeg_frame = buffer[start:end+2]
                buffer = buffer[end+2:]
                
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + jpeg_frame + b'\r\n')
                       
    except Exception as e:
        print(f"Błąd streamu: {e}")
    finally:
        if 'process' in locals() and process:
            process.terminate()

# ===== PUBLICZNE ROUTES =====
@app.route('/')
def dashboard():
    return render_template('dashboard.html')

@app.route('/api/system')
def api_system():
    return jsonify(get_system_info())

# ===== KAMERA - CHRONIONE ROUTES =====
@app.route('/cam')
@camera_login_required
def camera():
    return render_template('camera.html')

@app.route('/cam/login', methods=['GET', 'POST'])
def camera_login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        if verify_camera_password(username, password):
            session['camera_logged_in'] = True
            session['camera_user'] = username
            session['camera_login_time'] = datetime.now().isoformat()
            return redirect(url_for('camera'))
        else:
            flash('Nieprawidłowe dane logowania', 'error')
    
    return render_template('camera_login.html')

@app.route('/cam/logout')
def camera_logout():
    session.pop('camera_logged_in', None)
    session.pop('camera_user', None)
    session.pop('camera_login_time', None)
    return redirect(url_for('dashboard'))

@app.route('/cam/stream')
@camera_login_required
def camera_stream():
    global streaming
    streaming = True
    return Response(generate_mjpeg_stream(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/cam/photo', methods=['POST'])
@camera_login_required
def take_photo():
    global streaming
    
    try:
        was_streaming = streaming
        if was_streaming:
            streaming = False
            time.sleep(0.5)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        username = session.get('camera_user', 'unknown')
        filename = f"photo_{username}_{timestamp}.jpg"
        filepath = os.path.join(PHOTOS_DIR, filename)
        
        result = subprocess.run([
            'libcamera-still',
            '--output', filepath,
            '--timeout', '3000',
            '--width', str(CAMERA_WIDTH),
            '--height', str(CAMERA_HEIGHT),
            '--quality', str(CAMERA_QUALITY),
            '--encoding', 'jpg',
            '--denoise', 'cdn_hq',
            '--immediate'
        ], capture_output=True, text=True, timeout=15)
        
        if was_streaming:
            streaming = True
        
        if result.returncode == 0 and os.path.exists(filepath):
            file_size = os.path.getsize(filepath)
            return jsonify({
                'success': True,
                'filename': filename,
                'filepath': f'/static/photos/{filename}',
                'size': round(file_size / 1024, 1)
            })
        else:
            return jsonify({'error': f'Błąd kamery: {result.stderr}'}), 500
            
    except Exception as e:
        if 'was_streaming' in locals() and was_streaming:
            streaming = True
        return jsonify({'error': str(e)}), 500

@app.route('/cam/photos')
@camera_login_required
def list_photos():
    try:
        photos = []
        for filename in sorted(os.listdir(PHOTOS_DIR), reverse=True)[:PHOTOS_MAX]:
            if filename.endswith('.jpg'):
                filepath = os.path.join(PHOTOS_DIR, filename)
                if os.path.exists(filepath):
                    stat = os.stat(filepath)
                    photos.append({
                        'filename': filename,
                        'path': f'/static/photos/{filename}',
                        'size': round(stat.st_size / 1024, 1),
                        'date': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                    })
        return jsonify(photos)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/cam/stop_stream')
@camera_login_required
def stop_stream():
    global streaming
    streaming = False
    return jsonify({'success': True})

@app.route('/cam/delete_photo', methods=['POST'])
@camera_login_required
def delete_photo():
    try:
        filename = request.json.get('filename')
        if not filename or not filename.endswith('.jpg') or '/' in filename or '\\' in filename:
            return jsonify({'error': 'Nieprawidłowa nazwa pliku'}), 400
        
        filepath = os.path.join(PHOTOS_DIR, filename)
        
        if os.path.exists(filepath):
            os.remove(filepath)
            return jsonify({'success': True, 'message': f'Zdjęcie {filename} zostało usunięte'})
        else:
            return jsonify({'error': 'Plik nie istnieje'}), 404
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/cam/disable_camera', methods=['POST'])
@camera_login_required
def disable_camera():
    global streaming
    try:
        streaming = False
        time.sleep(1)
        subprocess.run(['sudo', 'dtoverlay', '-r', 'imx708'], timeout=10)
        return jsonify({'success': True, 'message': 'Kamera została wyłączona systemowo'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/cam/enable_camera', methods=['POST'])
@camera_login_required
def enable_camera():
    try:
        subprocess.run(['sudo', 'dtoverlay', 'imx708'], timeout=10)
        return jsonify({'success': True, 'message': 'Kamera została włączona - odczekaj chwilę'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/test-alert')
@camera_login_required
def test_alert():
    test_alert = {
        'type': 'warning',
        'title': 'Test systemu alertów',
        'message': '🧪 To jest test alertów GINGERITY',
        'value': '100',
        'threshold': '80'
    }
    send_alert(test_alert)
    return jsonify({'success': True, 'message': 'Alert testowy wysłany!'})


# ===== SERWOWANIE PLIKÓW =====
@app.route('/static/photos/<path:filename>')
@camera_login_required
def serve_photo(filename):
    return app.send_static_file(f'photos/{filename}')

@app.route('/static/<path:filename>')
def serve_static(filename):
    if filename.startswith('photos/'):
        return "Forbidden", 403
    return app.send_static_file(filename)


if __name__ == '__main__':
    try:
        debug_mode = os.getenv('DEBUG', 'False').lower() == 'true'
        app.run(host='0.0.0.0', port=5000, debug=debug_mode, threaded=True)
    finally:
        streaming = False