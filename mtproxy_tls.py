"""Fake TLS transport adapter for the pinned Telethon version."""
import asyncio
import hashlib
import hmac
import os

from TelethonFakeTLS.FakeTLS import MTProxyFakeTLSClientCodec, FakeTLSStreamWriter
from telethon.network.connection.tcpmtproxy import ConnectionTcpMTProxyRandomizedIntermediate


class TLSReader:
    def __init__(self, reader):
        self.reader = reader
        self.buffer = bytearray()

    async def readexactly(self, size):
        while len(self.buffer) < size:
            header = await self.reader.readexactly(5)
            length = int.from_bytes(header[3:], 'big')
            if header[:3] != b'\x17\x03\x03' or not 0 < length <= 18432:
                raise ConnectionError('Invalid Fake TLS data record')
            self.buffer.extend(await self.reader.readexactly(length))
        result = bytes(self.buffer[:size])
        del self.buffer[:size]
        return result


class TLSWriter(FakeTLSStreamWriter):
    async def wait_closed(self):
        await self.upstream.wait_closed()


class ConnectionTcpMTProxyFakeTLS(ConnectionTcpMTProxyRandomizedIntermediate):
    def __init__(self, ip, port, dc_id, *, loggers, proxy=None, local_addr=None):
        # The public configuration contains the complete, validated ee secret.
        self.tls_codec = MTProxyFakeTLSClientCodec(proxy[2][2:])
        # Upstream stores its template at class level: isolate concurrent clients.
        self.tls_codec.client_hello_dict = dict(self.tls_codec.client_hello_dict)
        self.tls_codec.fix_padding = self._fix_padding
        super().__init__(ip, port, dc_id, loggers=loggers,
                         proxy=(proxy[0], proxy[1], 'dd' + proxy[2][2:34]), local_addr=local_addr)

    def _fix_padding(self):
        codec = self.tls_codec
        codec.client_hello('ext_padding', b'')
        padding = max(0, 517 - len(codec.glue_pkt()))
        codec.client_hello('ext_padding_len', padding)
        codec.client_hello('ext_padding', bytes(padding))
        total = len(codec.glue_pkt())
        codec.client_hello('len', total - 5)
        codec.client_hello('handshake_len', total - 9)
        fields = list(codec.client_hello_dict)
        extension_size = sum(len(codec.client_hello_dict[key])
                             for key in fields[fields.index('extensions_len') + 1:])
        codec.client_hello('extensions_len', extension_size)

    async def _connect(self, timeout=None, ssl=None):
        async def handshake():
            address = self._local_addr
            if isinstance(address, str):
                address = (address, 0)
            self._reader, self._writer = await asyncio.open_connection(
                self._ip, self._port, local_addr=address)
            codec = self.tls_codec
            codec.gen_set_session_id = lambda: codec.client_hello('session_id', os.urandom(32))
            # Match the upstream public-key-shaped field, using OS randomness.
            codec.gen_set_key_share = lambda: codec.client_hello('ext_key_share_exchange',
                pow(int.from_bytes(os.urandom(32), 'little'), 2, 2**255 - 19).to_bytes(32, 'little'))
            self._writer.write(codec.build_new_client_hello_packet())
            await self._writer.drain()
            header = await self._reader.readexactly(5)
            if header[:3] != b'\x16\x03\x03' or int.from_bytes(header[3:], 'big') != 122:
                raise ConnectionError('Invalid Fake TLS server hello')
            hello = header + await self._reader.readexactly(122)
            change_cipher = await self._reader.readexactly(6)
            if change_cipher != b'\x14\x03\x03\x00\x01\x01':
                raise ConnectionError('Invalid Fake TLS handshake')
            record = await self._reader.readexactly(5)
            length = int.from_bytes(record[3:], 'big')
            if record[:3] != b'\x17\x03\x03' or not 0 < length <= 18432:
                raise ConnectionError('Invalid Fake TLS handshake record')
            hello += change_cipher + record + await self._reader.readexactly(length)
            if hello[44:76] != codec.client_hello_dict['session_id']:
                raise ConnectionError('Fake TLS session mismatch')
            digest = hmac.new(codec.secret, codec.client_hello_dict['random'] +
                              hello[:11] + bytes(32) + hello[43:], hashlib.sha256).digest()
            if not hmac.compare_digest(hello[11:43], digest):
                raise ConnectionError('Fake TLS proxy authentication failed')
            self._reader = TLSReader(self._reader)
            self._writer = TLSWriter(self._writer)
            self._codec = self.packet_codec(self)
            self._init_conn()
            await self._writer.drain()
        try:
            await asyncio.wait_for(handshake(), timeout=timeout or 15)
        except BaseException:
            if self._writer:
                self._writer.close()
                try:
                    await asyncio.wait_for(self._writer.wait_closed(), timeout=2)
                except (Exception, asyncio.CancelledError):
                    pass
            raise
