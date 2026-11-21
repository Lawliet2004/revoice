"""Synchronous access to the WebSocket client shipped by websockets 10.4."""

import asyncio
from contextlib import contextmanager

from websockets.legacy.client import connect as legacy_connect


class LegacySocket:
    def __init__(self, runner, socket):
        self.runner = runner
        self.socket = socket
        self.pending = None

    def send(self, message):
        self.runner.run(self.socket.send(message))

    def recv(self, timeout):
        return self.runner.run(self._recv(timeout))

    async def _recv(self, timeout):
        if self.pending is None:
            self.pending = asyncio.create_task(self.socket.recv())
        done, _ = await asyncio.wait((self.pending,), timeout=timeout)
        if not done:
            raise TimeoutError
        received, self.pending = self.pending, None
        return received.result()

    async def close(self):
        if self.pending is not None:
            self.pending.cancel()
            await asyncio.gather(self.pending, return_exceptions=True)
        await self.socket.close()


@contextmanager
def connect(uri, *, close_timeout=10, **options):
    async def open_socket():
        # The legacy implementation multiplies close_timeout for the handshake.
        return await legacy_connect(uri, close_timeout=close_timeout / 5, **options)

    with asyncio.Runner() as runner:
        socket = LegacySocket(runner, runner.run(open_socket()))
        try:
            yield socket
        finally:
            runner.run(socket.close())
