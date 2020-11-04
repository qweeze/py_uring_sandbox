import asyncio
import uvloop


async def main(host, port):
    async def handler(reader, writer):
        await reader.read(256)
        response = b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK'
        writer.write(response)
        await writer.drain()
        writer.close()

    async with (await asyncio.start_server(handler, host, port)) as server:
        await server.serve_forever()


if __name__ == '__main__':
    uvloop.install()
    asyncio.run(main('0.0.0.0', 8000))
