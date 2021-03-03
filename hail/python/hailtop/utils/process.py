import asyncio

from .utils import async_to_blocking


class CalledProcessError(Exception):
    def __init__(self, command, returncode, outerr):
        super().__init__()
        self.command = command
        self.returncode = returncode
        self.outerr = outerr

    def __str__(self):
        return (f'Command {self.command} returned non-zero exit status {self.returncode}.'
                f' Output:\n{self.outerr}')


async def check_shell_output(script, echo=False):
    if echo:
        print(script)
    proc = await asyncio.create_subprocess_exec(
        '/bin/bash', '-c', script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)
    outerr = await proc.communicate()
    if proc.returncode != 0:
        raise CalledProcessError(script, proc.returncode, outerr)
    return outerr


async def check_shell(script, echo=False):
    # discard output
    await check_shell_output(script, echo)


def sync_check_shell_output(script, echo=False):
    return async_to_blocking(check_shell_output(script, echo))


def sync_check_shell(script, echo=False):
    # discard output
    sync_check_shell_output(script, echo)


async def check_call(args, stdout=None, stderr=None):
    if stdout is None:
        stdout = asyncio.subprocess.PIPE
    if stderr is None:
        stderr = asyncio.subprocess.PIPE
    proc = await asyncio.create_subprocess_exec(
        args[0],
        *args[1:],
        stdout=stdout,
        stderr=stderr)
    outerr = await proc.communicate()
    if proc.returncode != 0:
        raise CalledProcessError(args, proc.returncode, outerr)
    return outerr
