"""Agent Runtime 的环境变量配置集中定义。

该文件只读取配置，不创建客户端或执行网络请求。
其他模块通过这里获得 LLM 与内部服务的默认地址，便于 Docker、本地脚本
和测试环境用环境变量覆盖。
"""
import os

# LLM 配置：优先由环境变量提供，默认值用于本地演示和开发。
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# 内部服务地址：Agent Runtime 需要知道自身和 LLM Router 的访问入口。
AGENT_RUNTIME_URL = os.getenv("AGENT_RUNTIME_HOST", "http://localhost:8003")
LLM_ROUTER_URL = os.getenv("LLM_ROUTER_HOST", "http://localhost:8002")
