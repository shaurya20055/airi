import pytest
import asyncio
from app.tools.system.terminal import execute_command, execute_shell
from app.core.permissions.command_policy import CommandPolicy
from app.core.permissions.levels import PermissionLevel

@pytest.mark.asyncio
async def test_execute_echo_helloworld():
    result = await execute_command("echo helloworld")
    assert result.success is True
    assert result.data["stdout"].strip() == "helloworld"
    assert result.data["exit_code"] == 0

@pytest.mark.asyncio
async def test_execute_pwd():
    result = await execute_command("pwd")
    assert result.success is True
    assert result.data["exit_code"] == 0
    assert len(result.data["stdout"]) > 0

@pytest.mark.asyncio
async def test_execute_multiple_args():
    result = await execute_command("printf '%s %s' hello world")
    assert result.success is True
    assert result.data["stdout"] == "hello world"

@pytest.mark.asyncio
async def test_execute_nonzero_exit():
    result = await execute_command("ls /completely/fake/directory/that/doesnt/exist")
    assert result.success is False
    assert result.data["exit_code"] != 0
    assert len(result.data["stderr"]) > 0

@pytest.mark.asyncio
async def test_execute_timeout():
    # sleep 2 should timeout if we set timeout to 1
    result = await execute_command("sleep 2", timeout=1)
    assert result.success is False
    assert "timed out" in result.error

@pytest.mark.asyncio
async def test_execute_missing_executable():
    result = await execute_command("completelyfakecommandthatdoesntexist")
    assert result.success is False
    assert "Command not found" in result.error

def test_security_sudo():
    level, reason = CommandPolicy.classify({"command": "sudo rm -rf /"})
    assert level == PermissionLevel.DANGEROUS
    assert "modifies system" in reason.lower()

def test_security_rm():
    level, reason = CommandPolicy.classify({"command": "rm file.txt"})
    assert level == PermissionLevel.DANGEROUS

def test_security_shell_meta():
    level, reason = CommandPolicy.classify({"command": "echo hello > file.txt"})
    assert level == PermissionLevel.DANGEROUS
    assert "metacharacter" in reason.lower()
    
    level, reason = CommandPolicy.classify({"command": "ls | grep py"})
    assert level == PermissionLevel.DANGEROUS

def test_security_safe_command():
    level, reason = CommandPolicy.classify({"command": "echo hello"})
    assert level == PermissionLevel.SAFE
    assert reason == ""

