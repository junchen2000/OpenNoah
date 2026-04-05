import asyncio
from noah_code.services.mcp_client import MCPManager

async def main():
    mgr = MCPManager()
    conns = await mgr.connect_all()
    print('connections', len(conns))
    for c in conns:
        print(c.config.name, c.connected, c.error, len(c.tools))
        for t in c.tools:
            print('tool', t.tool_name, t.description[:80])
    await mgr.disconnect_all()

asyncio.run(main())
