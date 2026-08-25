"""ColorFlow 共享业务服务层。

将 Web (app.py) 与 MCP (mcp_server.py) 共用的纯逻辑下沉到此包，
消除两份实现造成的行为偏差（见开发文档 P2-12 / P2-13）。
"""
