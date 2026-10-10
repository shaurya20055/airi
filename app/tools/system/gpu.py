from __future__ import annotations
import asyncio
import subprocess
from app.tools.registry import tool, ToolResult, PermissionLevel, ToolParameter

@tool(
    name="get_gpu_status",
    description="Get NVIDIA GPU telemetry including utilization, temperature, power, and VRAM. READ_ONLY/MONITORING.",
    category="system",
    permission_level=PermissionLevel.SAFE,
)
async def get_gpu_status() -> ToolResult:
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        
        name = pynvml.nvmlDeviceGetName(handle)
        if isinstance(name, bytes):
            name = name.decode('utf-8')
            
        utilization = pynvml.nvmlDeviceGetUtilizationRates(handle)
        temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
        
        try:
            power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
            power_limit = pynvml.nvmlDeviceGetPowerManagementLimit(handle) / 1000.0
        except pynvml.NVMLError:
            power, power_limit = 0.0, 0.0
            
        memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
        
        pynvml.nvmlShutdown()
        
        data = {
            "name": name,
            "utilization_percent": utilization.gpu,
            "temperature_c": temp,
            "power_usage_w": power,
            "power_limit_w": power_limit,
            "vram_used_mb": memory.used // (1024 * 1024),
            "vram_total_mb": memory.total // (1024 * 1024),
        }
        return ToolResult(success=True, data=data)
    except Exception as nvml_err:
        # Fallback to nvidia-smi
        try:
            proc = await asyncio.create_subprocess_exec(
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,temperature.gpu,power.draw,power.limit,memory.used,memory.total",
                "--format=csv,noheader,nounits",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                parts = [p.strip() for p in stdout.decode().strip().split(',')]
                if len(parts) >= 7:
                    data = {
                        "name": parts[0],
                        "utilization_percent": float(parts[1]) if parts[1] != "[Not Supported]" else 0.0,
                        "temperature_c": float(parts[2]),
                        "power_usage_w": float(parts[3]) if parts[3] != "[Not Supported]" else 0.0,
                        "power_limit_w": float(parts[4]) if parts[4] != "[Not Supported]" else 0.0,
                        "vram_used_mb": float(parts[5]),
                        "vram_total_mb": float(parts[6])
                    }
                    return ToolResult(success=True, data=data)
        except FileNotFoundError:
            pass
        except Exception:
            pass
            
        return ToolResult(success=False, error=f"GPU unavailable or not NVIDIA. NVML error: {nvml_err}")
