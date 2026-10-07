from __future__ import annotations

import importlib
import pkgutil

from app.tools.registry import ToolRegistry


def register_all_tools(registry: ToolRegistry) -> None:
    """
    Dynamically discover and register all tools in the tools package.
    """
    import app.tools
    
    # Subpackages to search
    packages = [
        'app.tools.os_tools',
        'app.tools.system',
        'app.tools.screen',
        'app.tools.files'
    ]
    
    for package_name in packages:
        try:
            package = importlib.import_module(package_name)
            for _, module_name, is_pkg in pkgutil.walk_packages(package.__path__, package.__name__ + '.'):
                if not is_pkg:
                    module = importlib.import_module(module_name)
                    if hasattr(module, 'register'):
                        module.register(registry)
        except ImportError as e:
            print(f"Warning: Failed to import tools from {package_name}: {e}")
