import enum
import logging.config
import socket
from typing import Any, Callable, Dict

import liburing

logger = logging.getLogger('uring_server')


class EntryType(enum.Enum):
    ACCEPT = enum.auto()
    READ = enum.auto()
    WRITE = enum.auto()
    CLOSE = enum.auto()


class Uring:
    def __init__(self, queue_size: int = 32):
        self._ring = liburing.io_uring()
        self._cqes = liburing.io_uring_cqes()
        self._queue_size = queue_size
        self._store: Dict[int, Any] = {}

    def start(self):
        liburing.io_uring_queue_init(self._queue_size, self._ring)

    def close(self):
        liburing.io_uring_queue_exit(self._ring)

    def submit_accept_entry(self, fd: int, addr: liburing, addrlen):
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
        self._submit(EntryType.WRITE, sqe, client_socket)

    def submit_close_entry(self, client_socket: int):
        sqe = liburing.io_uring_get_sqe(self._ring)
        liburing.io_uring_prep_close(sqe, client_socket)
        self._submit(EntryType.CLOSE, sqe)

    def _submit(self, entry_type: EntryType, sqe, *args):
        user_data = object()
        sqe.user_data = id(user_data)  # id is guaranteed to be unique during object's lifetime
        self._store[sqe.user_data] = entry_type, *args, user_data
        liburing.io_uring_submit(self._ring)

    def iter_cqes(self):
        while True:
            liburing.io_uring_wait_cqe(self._ring, self._cqes)
            cqe = self._cqes[0]
            liburing.trap_error(cqe.res)
            try:
                yield cqe, *self._store[cqe.user_data]
            finally:
                liburing.io_uring_cqe_seen(self._ring, cqe)


def start_server(
    host: str,
    port: int,
    handler: Callable[[bytes], bytes],
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

    uring = Uring()

    try:
        uring.start()
        uring.submit_accept_entry(fd, addr, addrlen)
        logger.info('listening on %s:%s', host, port)

        for cqe, entry_type, *args in uring.iter_cqes():
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
                    response = handler(buffer[:read_length])
                    uring.submit_write_entry(client_socket, response)

                elif entry_type is EntryType.WRITE:
                    # logger.debug('Response sent')
                    client_socket = args[0]
                    uring.submit_close_entry(client_socket)

                elif entry_type is EntryType.CLOSE:
                    ...
                    # logger.debug('Connection closed')

                else:
                    raise RuntimeError('Invalid entry_type')

            except ConnectionResetError:
                pass

    except KeyboardInterrupt:
        logger.info('Shutting down')

    finally:
        sock.close()
        uring.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    def handle_request(request: bytes) -> bytes:
        return b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK'

    start_server('0.0.0.0', 8000, handle_request)
