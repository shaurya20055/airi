import pytest
from unittest.mock import patch, MagicMock
from app.tools.system.gpu import get_gpu_status

@pytest.mark.asyncio
@patch('pynvml.nvmlInit')
@patch('pynvml.nvmlDeviceGetHandleByIndex')
@patch('pynvml.nvmlDeviceGetName')
@patch('pynvml.nvmlDeviceGetUtilizationRates')
@patch('pynvml.nvmlDeviceGetTemperature')
@patch('pynvml.nvmlDeviceGetPowerUsage')
@patch('pynvml.nvmlDeviceGetPowerManagementLimit')
@patch('pynvml.nvmlDeviceGetMemoryInfo')
@patch('pynvml.nvmlShutdown')
async def test_gpu_status_available(mock_shutdown, mock_mem, mock_pow_lim, mock_pow, mock_temp, mock_util, mock_name, mock_handle, mock_init):
    mock_name.return_value = b'NVIDIA RTX 5050'
    mock_util_obj = MagicMock()
    mock_util_obj.gpu = 45
    mock_util.return_value = mock_util_obj
    mock_temp.return_value = 65
    mock_pow.return_value = 45000 # 45W
    mock_pow_lim.return_value = 100000 # 100W
    mock_mem_obj = MagicMock()
    mock_mem_obj.used = 4 * 1024 * 1024 * 1024 # 4GB
    mock_mem_obj.total = 8 * 1024 * 1024 * 1024 # 8GB
    mock_mem.return_value = mock_mem_obj
    
    result = await get_gpu_status()
    assert result.success is True
    assert result.data["name"] == 'NVIDIA RTX 5050'
    assert result.data["utilization_percent"] == 45
    assert result.data["temperature_c"] == 65
    assert result.data["power_usage_w"] == 45.0
    assert result.data["power_limit_w"] == 100.0
    assert result.data["vram_used_mb"] == 4096
    assert result.data["vram_total_mb"] == 8192

@pytest.mark.asyncio
@patch('pynvml.nvmlInit', side_effect=Exception("NVML Not Found"))
@patch('asyncio.create_subprocess_exec')
async def test_gpu_smi_fallback(mock_exec, mock_init):
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"NVIDIA GeForce RTX 3060, 20, 50, 30.5, 170.0, 2048, 12288\n", b"")
    mock_proc.returncode = 0
    mock_exec.return_value = mock_proc
    
    result = await get_gpu_status()
    assert result.success is True
    assert result.data["name"] == "NVIDIA GeForce RTX 3060"
    assert result.data["utilization_percent"] == 20.0
    assert result.data["vram_used_mb"] == 2048.0

@pytest.mark.asyncio
@patch('pynvml.nvmlInit', side_effect=Exception("NVML Not Found"))
@patch('asyncio.create_subprocess_exec', side_effect=FileNotFoundError("nvidia-smi not found"))
async def test_gpu_unavailable(mock_exec, mock_init):
    result = await get_gpu_status()
    assert result.success is False
    assert "GPU unavailable" in result.error

# We need an AsyncMock class available in tests
class AsyncMock(MagicMock):
    async def __call__(self, *args, **kwargs):
        return super(AsyncMock, self).__call__(*args, **kwargs)
