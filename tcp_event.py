# -*- coding: utf-8 -*-
import logging
import socket

from event_loop import EventLoop, POLL_ERR, POLL_IN, POLL_OUT
from utils import create_remote_socket, create_server_socket, parse_host_from_req_data

BUF_SIZE = 24 * 1024


class TCPEvent(object):

    def __init__(self, local_sock, loop):
        # type: (socket.socket,EventLoop) -> None
        local_sock.setblocking(False)
        local_sock.setsockopt(socket.SOL_TCP, socket.TCP_NODELAY, 1)
        self._local_sock = local_sock
        self._remote_sock = None  # type: socket.socket
        self.loop = loop
        self.loop.add(local_sock, POLL_IN | POLL_ERR, self)
        self.req_data = bytes()
        self.recv_data = bytes()

    def destroy(self, sock):
        self.loop.remove(sock)
        sock.close()

    def _local_read(self):
        sock = self._local_sock
        self.req_data = sock.recv(BUF_SIZE)
        if not self.req_data:
            self.destroy(sock)
            return
        logging.info("POLL_IN event fd:%s req_data:%s recv_data:%s", sock.fileno(), self.req_data,
                     self.recv_data)
        host, port = parse_host_from_req_data(self.req_data)
        logging.info('[parse_host_from_req_data] host:%s port:%s' % (host, port))
        remote_sock = create_remote_socket(host, port)
        self._remote_sock = remote_sock
        logging.info("remote_sock:%s local_sock:%s", self._remote_sock.fileno(), self._local_sock.fileno())
        self.loop.add(remote_sock, POLL_OUT | POLL_ERR, self)

    def _remote_read(self):
        sock = self._remote_sock
        data = sock.recv(BUF_SIZE)
        logging.info("POLL_IN event fd:%s recv_data:%s len:%s", sock.fileno(), data[-10:], len(data))
        if not data:
            self.destroy(self._remote_sock)
            self.destroy(self._local_sock)
            return
        self.write_to_sock(data, self._local_sock)
        logging.info("recv_len:%s", len(self.recv_data))

    def _remote_write(self):
        sock = self._remote_sock
        if self.req_data:
            data = self.req_data
            self.req_data = bytes()
            self.write_to_sock(data, sock)
        else:
            self.loop.modify(sock, POLL_IN | POLL_ERR)

    def _local_write(self):
        sock = self._local_sock
        data = self.recv_data
        self.recv_data = bytes()
        logging.info("data:%s recv_data:%s", len(data), len(self.req_data))
        self.write_to_sock(data, sock)

    def handle_event(self, sock, fd, mode):
        # type: (socket.socket,int,int) -> None
        if mode & POLL_IN:
            if sock == self._local_sock:
                self._local_read()
            elif sock == self._remote_sock:
                self._remote_read()

        if mode & POLL_OUT:
            if sock == self._remote_sock:
                self._remote_write()
            elif sock == self._local_sock:
                self._local_write()

    def write_to_sock(self, data, sock):
        if not data:
            return False
        l = len(data)
        s = sock.send(data)
        uncomplete = False
        if s < l:
            data = data[s:]
            uncomplete = True
            self.loop.modify(sock, POLL_OUT | POLL_ERR)
        logging.info("write_to_sock event fd:%s send_data:%s l:%s s:%s", sock.fileno(), data, l, s)

        if uncomplete:
            if sock == self._local_sock:
                self.recv_data += data
            else:
                self.req_data += data
        else:
            if sock == self._local_sock:
                logging.info("send to local complete:%s %s", data[-10:], len(data))
            elif sock == self._remote_sock:
                logging.info("send to remote complete:%s %s", data[-10:], len(data))
        return uncomplete


class TCPServerEvent(object):
    def __init__(self):
        self.server_sock = create_server_socket('0.0.0.0', '1082')
        logging.info("src fd:%s", self.server_sock.fileno())

    def handle_event(self, sock, fd, mode):
        # type: (socket.socket,int,int) -> None
        if sock == self.server_sock:
            local_sock, addr = sock.accept()
            logging.info("receive event fd:%s addr:%s", local_sock.fileno(), addr)
            TCPEvent(local_sock, self.loop)
        else:
            raise Exception("no this socket")

    def add_loop(self, loop):
        # type: (EventLoop) -> None
        self.loop = loop
        loop.add(self.server_sock, POLL_IN | POLL_ERR, self)


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s,%(msecs)d %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s')
    loop = EventLoop()
    TCPServerEvent().add_loop(loop)
    loop.run()