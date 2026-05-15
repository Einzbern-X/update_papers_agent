import json
import os
import requests
from openai import OpenAI


class LLMClient:
    """普通 LLM 客户端：通过 REST 接口调用，返回 JSON 对象。用于 release judge / extraction rule 等任务。"""

    def __init__(self, cfg: dict):
        self.enabled = bool(cfg.get("enabled", False))
        self.model = cfg.get("model", "")
        self.api_key = os.getenv(cfg.get("api_key_env", "LLM_API_KEY"), "")
        self.base_url = os.getenv(cfg.get("base_url_env", "LLM_BASE_URL"), "").rstrip("/")
        self.temperature = float(cfg.get("temperature", 0.0))
        self.max_tokens = int(cfg.get("max_tokens", 2000))
        self.timeout = int(cfg.get("timeout", 60))

    def available(self) -> bool:
        return bool(self.enabled and self.model and self.api_key and self.base_url)

    def chat_json(self, system_prompt: str, user_prompt: str) -> dict:
        if not self.available():
            raise RuntimeError("LLM not available. Check config.yaml and env vars LLM_API_KEY / LLM_BASE_URL")
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return json.loads(content)


class LLMClientWeb:
    """
    支持 $web_search 工具调用的 LLM 客户端（使用 openai SDK）。
    参考 test_llm_web.py 的实现，支持多轮工具调用 agentic loop。

    用于：
    - search_release_url：搜索会议论文放榜 URL
    - 其他需要联网搜索的任务
    """

    WEB_SEARCH_TOOL = {
        "type": "builtin_function",
        "function": {"name": "$web_search"},
    }

    def __init__(self, cfg: dict):
        self.enabled = bool(cfg.get("enabled", False))
        self.model = cfg.get("model", "")
        self.api_key = os.getenv(cfg.get("api_key_env", "LLM_API_KEY"), "")
        self.base_url = os.getenv(cfg.get("base_url_env", "LLM_BASE_URL"), "")
        self.temperature = float(cfg.get("web_search_temperature", cfg.get("temperature", 0.6)))
        self.max_tokens = int(cfg.get("web_search_max_tokens", 32768))
        self.timeout = int(cfg.get("timeout", 120))
        self._client = None

    def available(self) -> bool:
        return bool(self.enabled and self.model and self.api_key and self.base_url)

    def _get_client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
            )
        return self._client

    def _chat_once(self, messages: list) -> tuple:
        """单次调用，返回 (choice, usage)"""
        client = self._get_client()
        completion = client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            tools=[self.WEB_SEARCH_TOOL],
            extra_body={"thinking": {"type": "disabled"}},
        )
        return completion.choices[0], completion.usage

    def chat_with_web_search(self, system_prompt: str, user_message: str) -> dict:
        """
        执行带 $web_search 工具调用的多轮对话，直到大模型返回最终 JSON 结果。

        大模型会自动决定何时使用 $web_search，搜索完成后返回 JSON 格式的结果。
        最终回答应是一个 JSON 字符串，本方法会解析并返回 dict。

        Args:
            system_prompt: 系统提示词
            user_message: 用户消息

        Returns:
            dict: 大模型最终返回的 JSON 结果
        """
        if not self.available():
            raise RuntimeError("LLMClientWeb not available. Check config and env vars.")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        finish_reason = None
        max_rounds = 10  # 防止死循环
        round_id = 1

        while (finish_reason is None or finish_reason == "tool_calls") and round_id <= max_rounds:
            choice, _usage = self._chat_once(messages)
            finish_reason = choice.finish_reason
            message = choice.message

            if finish_reason == "tool_calls":
                # 把 assistant 的 tool_calls 消息加入上下文
                assistant_message = {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": message.tool_calls,
                    "reasoning_content": getattr(
                        message, "reasoning_content",
                        "I need to call search tool to get information.",
                    ),
                }
                messages.append(assistant_message)

                # 处理每个工具调用
                for tool_call in message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_args = json.loads(tool_call.function.arguments)

                    if tool_name == "$web_search":
                        # Kimi 官方 $web_search：直接原样返回 arguments 即可
                        tool_result = tool_args
                    else:
                        tool_result = {"error": f"unknown tool: {tool_name}"}

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    })

                round_id += 1
                continue

            # finish_reason == "stop"，解析最终内容
            content = message.content or ""
            # 尝试直接解析 JSON
            try:
                # 去掉可能的 markdown code block
                stripped = content.strip()
                if stripped.startswith("```"):
                    lines = stripped.split("\n")
                    # 去掉首行和末行
                    stripped = "\n".join(lines[1:-1]).strip()
                return json.loads(stripped)
            except (json.JSONDecodeError, ValueError):
                # 返回原始文本，让调用方处理
                return {"found": False, "url": "", "confidence": 0.0,
                        "reason": f"json_parse_failed: {content[:300]}"}

        return {"found": False, "url": "", "confidence": 0.0,
                "reason": f"max_rounds_exceeded_or_unexpected_stop"}
