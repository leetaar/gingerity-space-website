import pytest
import json
import os
from unittest.mock import patch, MagicMock

def test_flask_import():
    """Test czy Flask się importuje"""
    try:
        import flask
        assert True
    except ImportError:
        pytest.fail("Flask not available")

def test_psutil_import():
    """Test czy psutil się importuje"""
    try:
        import psutil
        assert True
    except ImportError:
        pytest.fail("psutil not available")

@patch('psutil.cpu_percent')
@patch('psutil.virtual_memory')
@patch('psutil.disk_usage')
def test_mock_system_metrics(mock_disk, mock_memory, mock_cpu):
    """Test mocków metryk systemowych"""
    mock_cpu.return_value = 25.5
    mock_memory.return_value = MagicMock(
        percent=45.2,
        available=2048 * 1024 * 1024
    )
    mock_disk.return_value = MagicMock(
        percent=60.0,
        free=20 * 1024 * 1024 * 1024
    )
    
    # Test czy mocki działają
    import psutil
    assert psutil.cpu_percent() == 25.5
    assert psutil.virtual_memory().percent == 45.2

def test_json_serialization():
    """Test serializacji JSON"""
    test_data = {
        'cpu_percent': 25.5,
        'memory': {'percent': 45.2},
        'temperature': 42.1
    }
    
    json_str = json.dumps(test_data)
    parsed = json.loads(json_str)
    
    assert parsed['cpu_percent'] == 25.5
    assert parsed['memory']['percent'] == 45.2

def test_basic_calculations():
    """Test podstawowych obliczeń używanych w app"""
    # Test konwersji MB
    bytes_val = 1024 * 1024 * 100  # 100MB
    mb_val = bytes_val / 1024 / 1024
    assert mb_val == 100.0
    
    # Test formatowania temperatury
    temp_str = "temp=42.1'C"
    temp_val = float(temp_str.split('=')[1].split("'")[0])
    assert temp_val == 42.1

if __name__ == '__main__':
    pytest.main(['-v', __file__])
