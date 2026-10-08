import logging
from contextlib import asynccontextmanager
from ssl import VerifyMode
from typing import AsyncGenerator, Optional, TextIO, cast

logger = logging.getLogger(__name__)

_PATCHED = False


def ensure_patched() -> None:
    global _PATCHED
    if _PATCHED:
        return
    try:
        from pymobiledevice3.remote.core_device_tunnel_service import (
            CoreDeviceTunnelService,
            RemotePairingQuicTunnel,
            TunnelResult,
        )
        from pymobiledevice3.ca import make_cert
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            NoEncryption,
            PrivateFormat,
        )
        from qh3.asyncio.client import connect as aioquic_connect
        from qh3.quic.configuration import QuicConfiguration
    except Exception as e:
        logger.warning(f"quic compat patch skipped: {e}")
        return

    @asynccontextmanager
    async def start_quic_tunnel_fixed(
        self,
        secrets_log_file: Optional[TextIO] = None,
        max_idle_timeout: float = RemotePairingQuicTunnel.MAX_IDLE_TIMEOUT,
    ) -> AsyncGenerator[TunnelResult, None]:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        parameters = self.create_quic_listener(private_key)
        cert = make_cert(private_key, private_key.public_key())
        configuration = QuicConfiguration(
            alpn_protocols=['RemotePairingTunnelProtocol'],
            is_client=True,
            verify_mode=VerifyMode.CERT_NONE,
            verify_hostname=False,
            max_datagram_frame_size=RemotePairingQuicTunnel.MAX_QUIC_DATAGRAM,
            idle_timeout=max_idle_timeout,
        )
        configuration.load_cert_chain(
            cert.public_bytes(Encoding.PEM),
            private_key.private_bytes(
                Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()
            ),
        )
        configuration.secrets_log_file = secrets_log_file

        host = self.service.address[0]
        port = parameters['port']

        self.logger.debug(f'Connecting to {host}:{port}')
        async with aioquic_connect(
            host,
            port,
            configuration=configuration,
            create_protocol=RemotePairingQuicTunnel,
        ) as client:
            self.logger.debug('quic connected')
            client = cast(RemotePairingQuicTunnel, client)
            await client.wait_connected()
            handshake_response = await client.request_tunnel_establish()
            client.start_tunnel(handshake_response['clientParameters']['address'],
                                handshake_response['clientParameters']['mtu'])
            try:
                yield TunnelResult(
                    client.tun.name, handshake_response['serverAddress'],
                    handshake_response['serverRSDPort'],
                    __import__('pymobiledevice3.remote.common', fromlist=['TunnelProtocol']).TunnelProtocol.QUIC,
                    client)
            finally:
                await client.stop_tunnel()

    CoreDeviceTunnelService.start_quic_tunnel = start_quic_tunnel_fixed
    _PATCHED = True
    logger.debug("quic compat patch applied (load_cert_chain)")
