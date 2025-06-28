import pytest
import json
import os
import tempfile
from unittest.mock import patch, MagicMock
from app import app, get_system_metrics

@pytest.fixture
def client():
    """Klient testowy Flask"""
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test_secret_key'
    
    with app.test_client() as client:
        with app.app_context():
            yield client

def test_dashboard_route(client):
    """Test głównej strony dashboard"""
    response = client.get('/')
    assert response.status_code == 200
    assert b'GINGERITY.space Dashboard' in response.data

def test_gablotka_route(client):
    """Test strony gablotki"""
    response = client.get('/gablotka')
    assert response.status_code == 200

@patch('app.psutil.cpu_percent')
@patch('app.psutil.virtual_memory')
@patch('app.psutil.disk_usage')
def test_api_system_basic(mock_disk, mock_memory, mock_cpu, client):
    """Test podstawowych metryk systemowych"""
    # Mock danych systemowych
    mock_cpu.return_value = 25.5
    mock_memory.return_value = MagicMock(
        percent=45.2,
        available=2048 * 1024 * 1024,  # 2GB
        total=4096 * 1024 * 1024       # 4GB
    )
    mock_disk.return_value = MagicMock(
        percent=60.0,
        free=20 * 1024 * 1024 * 1024,  # 20GB
        total=50 * 1024 * 1024 * 1024  # 50GB
    )
    
    response = client.get('/api/system')
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert 'cpu_percent' in data
    assert 'memory' in data
    assert 'disk' in data
    assert data['cpu_percent'] == 25.5
    assert data['memory']['percent'] == 45.2

@patch('app.subprocess.run')
def test_cpu_temperature(mock_subprocess, client):
    """Test odczytu temperatury CPU"""
    # Mock temperatury z vcgencmd
    mock_subprocess.return_value = MagicMock(
        stdout='temp=42.1\'C\n',
        returncode=0
    )
    
    response = client.get('/api/system')
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert 'temperature' in data
    assert data['temperature'] == 42.1

@patch('app.psutil.net_io_counters')
def test_network_metrics(mock_net, client):
    """Test metryk sieciowych"""
    mock_net.return_value = MagicMock(
        bytes_sent=1024 * 1024 * 100,    # 100MB
        bytes_recv=1024 * 1024 * 200     # 200MB
    )
    
    response = client.get('/api/system')
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert 'network' in data
    assert data['network']['bytes_sent_mb'] == 100
    assert data['network']['bytes_recv_mb'] == 200

@patch('app.psutil.process_iter')
def test_top_processes(mock_processes, client):
    """Test listy top procesów"""
    # Mock procesów
    mock_proc1 = MagicMock()
    mock_proc1.info = {
        'pid': 1234,
        'name': 'python3',
        'cpu_percent': 15.5,
        'memory_info': MagicMock(rss=50 * 1024 * 1024)  # 50MB
    }
    
    mock_proc2 = MagicMock()
    mock_proc2.info = {
        'pid': 5678,
        'name': 'nginx',
        'cpu_percent': 8.2,
        'memory_info': MagicMock(rss=30 * 1024 * 1024)  # 30MB
    }
    
    mock_processes.return_value = [mock_proc1, mock_proc2]
    
    response = client.get('/api/system')
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert 'processes' in data
    assert 'top_cpu' in data['processes']
    assert 'top_ram' in data['processes']

def test_camera_route_exists(client):
    """Test czy trasa kamery istnieje"""
    response = client.get('/cam')
    # Może zwrócić 200 lub przekierowanie, ważne że nie 404
    assert response.status_code in [200, 302, 401]

def test_invalid_api_route(client):
    """Test nieistniejącej trasy API"""
    response = client.get('/api/nonexistent')
    assert response.status_code == 404

@patch('app.sqlite3.connect')
def test_system_history_api(mock_connect, client):
    """Test API historii systemowej"""
    # Mock bazy danych
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        ('2024-01-01 12:00:00', 25.5, 45.2, 42.1),
        ('2024-01-01 13:00:00', 30.1, 48.7, 43.2)
    ]
    
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_connect.return_value = mock_conn
    
    response = client.get('/api/system/history?hours=24')
    assert response.status_code == 200
    
    data = json.loads(response.data)
    assert isinstance(data, list)
    assert len(data) == 2

def test_ping_functionality():
    """Test funkcjonalności ping"""
    from app import ping_host
    
    # Test ping do localhost (powinien działać)
    result = ping_host('127.0.0.1')
    assert 'success' in result
    assert 'ping_ms' in result

def test_uptime_formatting():
    """Test formatowania uptime"""
    from app import format_uptime
    
    # Test różnych wartości uptime
    assert format_uptime(3661) == "1h 1m"  # 1 godzina 1 minuta
    assert format_uptime(86461) == "1d 1m"  # 1 dzień 1 minuta
    assert format_uptime(90061) == "1d 1h 1m"  # 1 dzień 1 godzina 1 minuta

if __name__ == '__main__':
    pytest.main(['-v', __file__])