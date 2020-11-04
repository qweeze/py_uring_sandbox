import asyncio
import ctypes
import enum
import logging.config
import os
import signal
import socket
from typing import Any, Awaitable, Callable, Dict

import liburing

logger = logging.getLogger('asyncio_uring_server')

libc = ctypes.CDLL(None)


class EntryType(enum.Enum):
    ACCEPT = enum.auto()
    READ = enum.auto()
    WRITE = enum.auto()
    CLOSE = enum.auto()


class Uring:
    def __init__(self, queue_size: int = 32, loop: asyncio.BaseEventLoop = None):
        self._ring = liburing.io_uring()
        self._cqes = liburing.io_uring_cqes()
        self._queue_size = queue_size
        self._store: Dict[int, Any] = {}

        self._loop = loop or asyncio.get_event_loop()
        self._event_fd = libc.eventfd(0, os.O_NONBLOCK | os.O_CLOEXEC)
        self._ev = asyncio.Event()
        self._is_closing: bool = False

    def start(self, loop=None):
        liburing.io_uring_queue_init(self._queue_size, self._ring)
        liburing.io_uring_register_eventfd(self._ring, self._event_fd)
        self._loop.add_reader(self._event_fd, self._ev.set)

    def close(self):
        self._is_closing = True
        self._ev.set()

    def _close(self):
        self._loop.remove_reader(self._event_fd)
        liburing.io_uring_queue_exit(self._ring)

    def submit_accept_entry(self, fd: int, addr: liburing, addrlen):
        if self._is_closing:
            return
        sqe = liburing.io_uring_get_sqe(self._ring)
        liburing.io_uring_prep_accept(sqe, fd, addr, addrlen, 0)
        self._submit(EntryType.ACCEPT, sqe)

    def submit_read_entry(self, client_socket: int, size: int):
        sqe = liburing.io_uring_get_sqe(self._ring)
        array = bytearray(size)
        iovecs = liburing.iovec(array)
        liburing.io_uring_prep_readv(sqe, client_socket, iovecs, len(iovecs), 0)
        self._submit(EntryType.READ, sqe, array, client_socket)

    def submit_write_entry(self, client_socket: int, data: bytes):
        sqe = liburing.io_uring_get_sqe(self._ring)
        array = bytearray(data)
        iovecs = liburing.iovec(array)
        liburing.io_uring_prep_writev(sqe, client_socket, iovecs, len(iovecs), 0)
        self._submit(EntryType.WRITE, sqe, client_socket, array)

    def submit_close_entry(self, client_socket: int):
        sqe = liburing.io_uring_get_sqe(self._ring)
        liburing.io_uring_prep_close(sqe, client_socket)
        self._submit(EntryType.CLOSE, sqe, client_socket)

    def _submit(self, entry_type: EntryType, sqe, *args):
        user_data = object()
        sqe.user_data = id(user_data)  # id is guaranteed to be unique during object's lifetime
        self._store[sqe.user_data] = entry_type, *args, user_data
        liburing.io_uring_submit(self._ring)

    async def iter_cqes(self):
        while True:
            await self._ev.wait()
            self._ev.clear()
            while True:
                try:
                    liburing.io_uring_peek_cqe(self._ring, self._cqes)
                except BlockingIOError:
                    break
                cqe = self._cqes[0]
                liburing.trap_error(cqe.res)
                try:
                    yield cqe, *self._store[cqe.user_data]
                finally:
                    liburing.io_uring_cqe_seen(self._ring, cqe)

            if self._is_closing:
                self._close()
                break


async def start_server(
    host: str,
    port: int,
    handler: Callable[[bytes], Awaitable[bytes]],
    backlog: int = 100,
    reuse_addr: bool = False,
    reuse_port: bool = False,
):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if reuse_addr:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
    if reuse_port:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, True)

    sock.bind((host, port))
    sock.listen(backlog)

    fd = sock.fileno()
    addr, addrlen = liburing.sockaddr()

    loop = asyncio.get_event_loop()
    uring = Uring()

    def on_stop():
        logger.info('Shutting down')
        sock.close()
        uring.close()

    uring.start()

    for sig in signal.SIGTERM, signal.SIGINT, signal.SIGHUP:
        loop.add_signal_handler(sig, on_stop)

    uring.submit_accept_entry(fd, addr, addrlen)
    logger.info('listening on %s:%s', host, port)

    async def handler_wrapper(request, client_socket):
        try:
            response = await handler(request)
        except:
            uring.submit_close_entry(client_socket)
            raise
        else:
            uring.submit_write_entry(client_socket, response)

    async for cqe, entry_type, *args in uring.iter_cqes():
        try:
            if entry_type is EntryType.ACCEPT:
                # logger.debug('Connection made')
                uring.submit_accept_entry(fd, addr, addrlen)
                uring.submit_read_entry(client_socket=cqe.res, size=256)

            elif entry_type is EntryType.READ:
                buffer, client_socket, *_ = args
                read_length = cqe.res
                if read_length == len(buffer):
                    logger.error('Request too large')  # todo
                    uring.submit_close_entry(client_socket)
                    continue

                # logger.debug('Request read')
                asyncio.create_task(handler_wrapper(buffer[:read_length], client_socket))

            elif entry_type is EntryType.WRITE:
                client_socket = args[0]
                # logger.debug('Response sent')
                uring.submit_close_entry(client_socket)

            elif entry_type is EntryType.CLOSE:
                client_socket = args[0]
                # logger.debug('Connection closed')

            else:
                raise RuntimeError('Invalid entry_type')

        except ConnectionResetError:
            pass


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)

    async def handle_request(request: bytes) -> bytes:
        return b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK'

    asyncio.run(start_server('0.0.0.0', 8000, handle_request))
