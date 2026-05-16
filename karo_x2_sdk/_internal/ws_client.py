from __future__ import annotations

import asyncio
import ssl
import tempfile
from typing import Any, Awaitable, Callable, Optional

import websockets

from ..error import ErrorCode, SdkException

def _is_ws_closed(ws: Any) -> bool:
    if ws is None:
        return True

    state = getattr(ws, "state", None)
    if state is not None:
        try:
            from websockets.protocol import State
            return state in (State.CLOSING, State.CLOSED)
        except ImportError:
            pass

    closed = getattr(ws, "closed", None)
    if closed is not None:
        return bool(closed)
    return False

MessageHandler = Callable[[bytes], Awaitable[None]]
CloseHandler = Callable[[ErrorCode, str], Awaitable[None]]

class WsClient:

    def __init__(
        self,
        host: str,
        port: int,
        cert_pem: str,
        key_pem: str,
        ca_pem: str,
        insecure_skip_verify: bool,
        path: str = "/",
    ) -> None:
        self._host = host
        self._port = port
        self._cert_pem = cert_pem
        self._key_pem = key_pem
        self._ca_pem = ca_pem
        self._insecure = insecure_skip_verify
        self._path = path

        self._ws: Optional[Any] = None
        self._read_task: Optional[asyncio.Task[None]] = None
        self._closed = False
        self._lock = asyncio.Lock()

        self.on_message: Optional[MessageHandler] = None
        self.on_close: Optional[CloseHandler] = None

    @property
    def is_open(self) -> bool:
        return self._ws is not None and not _is_ws_closed(self._ws)

    async def connect(self, timeout: float) -> None:
        ssl_ctx = self._build_ssl_context()
        uri = f"wss://{self._host}:{self._port}{self._path}"
        try:
            self._ws = await asyncio.wait_for(
                websockets.connect(
                    uri,
                    ssl=ssl_ctx,
                    server_hostname=self._host,

                    subprotocols=None,
                    open_timeout=timeout,
                    close_timeout=2,
                    max_size=64 * 1024 * 1024,

                    user_agent_header="karo-x2-sdk-python/3.2.15",
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError as e:
            raise SdkException(ErrorCode.TIMEOUT, f"ws connect timeout: {e}")
        except ssl.SSLError as e:
            raise SdkException(ErrorCode.AUTH_FAILED, f"TLS error: {e}")
        except websockets.exceptions.InvalidHandshake as e:
            raise SdkException(ErrorCode.TRANSPORT_FAILURE, f"WS handshake: {e}")
        except OSError as e:
            raise SdkException(ErrorCode.TRANSPORT_FAILURE, f"TCP error: {e}")

        self._read_task = asyncio.create_task(self._read_loop(), name="ws-read")

    def _build_ssl_context(self) -> ssl.SSLContext:

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        if self._insecure:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        else:
            ctx.check_hostname = True
            ctx.verify_mode = ssl.CERT_REQUIRED
            if self._ca_pem:

                ctx.load_verify_locations(cadata=self._ca_pem)
            else:
                ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)

        if self._cert_pem and self._key_pem:

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".pem", delete=False
            ) as cert_f, tempfile.NamedTemporaryFile(
                mode="w", suffix=".pem", delete=False
            ) as key_f:
                cert_f.write(self._cert_pem)
                cert_f.flush()
                key_f.write(self._key_pem)
                key_f.flush()
                cert_path = cert_f.name
                key_path = key_f.name
            try:
                ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
            except ssl.SSLError as e:
                raise SdkException(ErrorCode.AUTH_FAILED, f"cert/key load: {e}")
            finally:
                import os

                try:
                    os.unlink(cert_path)
                except OSError:
                    pass
                try:
                    os.unlink(key_path)
                except OSError:
                    pass
        return ctx

    async def _read_loop(self) -> None:
        ws = self._ws
        if ws is None:
            return
        try:
            async for msg in ws:
                if isinstance(msg, bytes):
                    if self.on_message is not None:
                        try:
                            await self.on_message(msg)
                        except Exception:
                            pass

        except websockets.exceptions.ConnectionClosed as e:
            reason = ErrorCode.CANCELLED if e.code == 1000 else ErrorCode.TRANSPORT_FAILURE
            await self._fire_close(reason, str(e))
        except Exception as e:
            await self._fire_close(ErrorCode.TRANSPORT_FAILURE, str(e))

    async def _fire_close(self, reason: ErrorCode, msg: str) -> None:
        if self._closed:
            return
        self._closed = True
        cb = self.on_close
        if cb is not None:
            try:
                await cb(reason, msg)
            except Exception:
                pass

    async def send(self, data: bytes) -> bool:
        if _is_ws_closed(self._ws):
            return False
        try:
            await self._ws.send(data)
            return True
        except websockets.exceptions.ConnectionClosed:

            return False
        except Exception:
            return False

    async def close(self) -> None:
        ws = self._ws
        if ws is None:
            return
        if not _is_ws_closed(ws):
            try:
                await ws.close(code=1000, reason="client close")
            except Exception:
                pass
        if self._read_task is not None:
            if asyncio.current_task() is self._read_task:

                self._read_task = None
                self._ws = None
                return
            try:
                await asyncio.wait_for(self._read_task, timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                self._read_task.cancel()
                try:
                    await self._read_task
                except (asyncio.CancelledError, Exception):
                    pass
            self._read_task = None
        self._ws = None

