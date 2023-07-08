import asyncio
import subprocess

import pytest

from hat import sbs
from hat import util

from hat import chatter


@pytest.fixture
def port():
    return util.get_unused_tcp_port()


@pytest.fixture
def addr(port):
    return f'tcp+sbs://127.0.0.1:{port}'


@pytest.fixture
def ssl_addr(port):
    return f'ssl+sbs://127.0.0.1:{port}'


@pytest.fixture
def pem_path(tmp_path):
    path = tmp_path / 'pem'
    subprocess.run(['openssl', 'req', '-batch', '-x509', '-noenc',
                    '-newkey', 'rsa:2048',
                    '-days', '1',
                    '-keyout', str(path),
                    '-out', str(path)],
                   stderr=subprocess.DEVNULL,
                   check=True)
    return path


@pytest.fixture(scope="session")
def sbs_repo():
    data_sbs_repo = sbs.Repository("""
        module Test

        Data = Integer
    """)
    return sbs.Repository(chatter.sbs_repo, data_sbs_repo)


async def test_sbs_repo(sbs_repo):
    data = 123
    encoded_data = sbs_repo.encode('Test', 'Data', data)
    decoded_data = sbs_repo.decode('Test', 'Data', encoded_data)
    assert data == decoded_data

    msg = {'id': 1,
           'first': 2,
           'owner': True,
           'token': False,
           'last': True,
           'data': {'module': ('value', 'Test'),
                    'type': 'Data',
                    'data': encoded_data}}
    encoded_msg = sbs_repo.encode('Hat', 'Msg', msg)
    decoded_msg = sbs_repo.decode('Hat', 'Msg', encoded_msg)
    assert msg == decoded_msg


async def test_connect(addr, sbs_repo):
    with pytest.raises(Exception):
        await chatter.connect(sbs_repo, addr)

    srv_conn_future = asyncio.Future()
    srv = await chatter.listen(sbs_repo, addr,
                               lambda conn: srv_conn_future.set_result(conn))
    conn = await chatter.connect(sbs_repo, addr)
    srv_conn = await srv_conn_future

    assert not conn.is_closed
    assert not srv_conn.is_closed
    assert srv.addresses == [addr]
    assert conn.remote_address == addr
    assert srv_conn.local_address == addr

    await conn.async_close()
    await srv.async_close()

    assert conn.is_closed
    assert srv_conn.is_closed


async def test_ssl_connect(ssl_addr, pem_path, sbs_repo):
    srv = await chatter.listen(sbs_repo, ssl_addr, lambda conn: None,
                               pem_file=pem_path)

    conn_without_cert = await chatter.connect(sbs_repo, ssl_addr)
    assert not conn_without_cert.is_closed
    await conn_without_cert.async_close()
    assert conn_without_cert.is_closed

    conn_with_cert = await chatter.connect(sbs_repo, ssl_addr,
                                           pem_file=pem_path)
    assert not conn_with_cert.is_closed
    await conn_with_cert.async_close()
    assert conn_with_cert.is_closed

    await srv.async_close()


async def test_listen(addr, sbs_repo):
    srv = await chatter.listen(sbs_repo, addr, lambda conn: None)
    assert not srv.is_closed

    conn = await chatter.connect(sbs_repo, addr)
    await conn.async_close()

    await srv.async_close()
    assert srv.is_closed

    with pytest.raises(Exception):
        await chatter.connect(sbs_repo, addr)


@pytest.mark.parametrize('address', ['tcp+sbs://127.0.0.1',
                                     'tcp://127.0.0.1:1234'])
async def test_wrong_address(sbs_repo, address):
    with pytest.raises(ValueError):
        await chatter.connect(sbs_repo, address)

    with pytest.raises(ValueError):
        await chatter.listen(sbs_repo, address, lambda conn: None)


async def test_send_receive(addr, sbs_repo):
    conn2_future = asyncio.Future()
    srv = await chatter.listen(sbs_repo, addr,
                               lambda conn: conn2_future.set_result(conn))
    conn1 = await chatter.connect(sbs_repo, addr)
    conn2 = await conn2_future

    data = chatter.Data(module='Test',
                        type='Data',
                        data=123)
    conv = conn1.send(data)
    assert conv.owner is True
    msg = await conn2.receive()
    assert msg.data == data
    assert msg.conv.owner is False
    assert msg.conv.first_id == conv.first_id
    assert msg.first is True
    assert msg.last is True
    assert msg.token is True

    await conn1.async_close()
    await conn2.async_close()
    await srv.async_close()

    with pytest.raises(ConnectionError):
        conn1.send(data)
    with pytest.raises(ConnectionError):
        await conn2.receive()


async def test_send_receive_native_data(addr, sbs_repo):
    conn2_future = asyncio.Future()
    srv = await chatter.listen(sbs_repo, addr,
                               lambda conn: conn2_future.set_result(conn))
    conn1 = await chatter.connect(sbs_repo, addr)
    conn2 = await conn2_future

    data = chatter.Data(module=None,
                        type='Integer',
                        data=123)
    conn1.send(data)
    msg = await conn2.receive()
    assert data == msg.data

    await conn1.async_close()
    await conn2.async_close()
    await srv.async_close()


async def test_invalid_communication(port, addr, sbs_repo):
    conn_future = asyncio.Future()
    srv = await chatter.listen(sbs_repo, addr,
                               lambda conn: conn_future.set_result(conn))
    reader, writer = await asyncio.open_connection('127.0.0.1', port)
    conn = await conn_future

    writer.write(b'\x01\x02\x03\x04')
    await writer.drain()
    with pytest.raises(ConnectionError):
        await conn.receive()

    writer.close()
    await writer.wait_closed()

    await conn.wait_closed()
    await srv.async_close()


async def test_conversation_timeout(addr, sbs_repo):
    conn2_future = asyncio.Future()
    srv = await chatter.listen(sbs_repo, addr,
                               lambda conn: conn2_future.set_result(conn))
    conn1 = await chatter.connect(sbs_repo, addr)
    conn2 = await conn2_future

    data = chatter.Data(module='Test',
                        type='Data',
                        data=123)

    timeout = asyncio.Future()
    conv = conn1.send(data, last=False, timeout=1,
                      timeout_cb=lambda conv: timeout.set_result(conv))
    msg = await conn2.receive()
    conn2.send(data, last=False, conv=msg.conv)
    msg = await conn1.receive()

    assert msg.conv == conv

    conn1.send(data, last=False, token=False, timeout=0.001, conv=conv,
               timeout_cb=lambda conv: timeout.set_result(conv))
    conn1.send(data, last=False, timeout=0.001, conv=conv,
               timeout_cb=lambda conv: timeout.set_result(conv))
    assert not timeout.done()
    await timeout

    await conn1.async_close()
    await conn2.async_close()
    await srv.async_close()


async def test_ping_timeout(port, addr, sbs_repo):
    conn_future = asyncio.Future()
    srv = await chatter.listen(sbs_repo, addr,
                               lambda conn: conn_future.set_result(conn),
                               ping_timeout=0.001)
    reader, writer = await asyncio.open_connection('127.0.0.1', port)
    conn = await conn_future

    await conn.wait_closed()

    writer.close()
    await writer.wait_closed()

    await srv.async_close()


async def test_connection_close_when_queue_blocking(addr, sbs_repo):
    conn2_future = asyncio.Future()
    srv = await chatter.listen(sbs_repo, addr,
                               lambda conn: conn2_future.set_result(conn))
    conn1 = await chatter.connect(sbs_repo, addr, queue_maxsize=1)
    conn2 = await conn2_future

    data = chatter.Data(module='Test',
                        type='Data',
                        data=123)
    conn2.send(data)
    conn2.send(data)

    await asyncio.sleep(0.01)

    await conn1.async_close()
    await asyncio.wait_for(conn2.wait_closed(), 0.1)

    await srv.async_close()


async def test_example_docs():

    from hat import aio
    from hat import chatter
    from hat import sbs
    from hat import util

    sbs_repo = sbs.Repository(chatter.sbs_repo, r"""
        module Example

        Msg = Integer
    """)

    port = util.get_unused_tcp_port()
    address = f'tcp+sbs://127.0.0.1:{port}'

    server_conns = aio.Queue()
    server = await chatter.listen(sbs_repo, address, server_conns.put_nowait)

    client_conn = await chatter.connect(sbs_repo, address)
    server_conn = await server_conns.get()

    data = chatter.Data('Example', 'Msg', 123)
    client_conn.send(data)

    msg = await server_conn.receive()
    assert msg.data == data

    await server.async_close()
    await client_conn.wait_closed()
    await server_conn.wait_closed()
