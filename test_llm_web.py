import os
import json
from openai import OpenAI


client = OpenAI(
    base_url=os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1"),
    api_key=os.getenv("MOONSHOT_API_KEY"),
)


TOOLS = [
    {
        "type": "builtin_function",
        "function": {
            "name": "$web_search",
        },
    }
]


def search_impl(arguments):
    """
    Kimi 官方 $web_search 的关键点：
    这里不要自己 requests，不要自己搜索。
    直接把模型返回的 arguments 原样返回即可。
    """
    return arguments


def chat(messages):
    completion = client.chat.completions.create(
        model=os.getenv("KIMI_MODEL", "kimi-k2.6"),
        messages=messages,
        max_tokens=32768,
        temperature=0.6,
        tools=TOOLS,
        extra_body={
            "thinking": {"type": "disabled"}
        },
    )
    return completion.choices[0], completion.usage


def main():
    if not os.getenv("MOONSHOT_API_KEY"):
        raise RuntimeError("请先设置 MOONSHOT_API_KEY")

    messages = [
        {
            "role": "system",
            "content": (
                "你是 Kimi。"
            ),
        },
        {
            "role": "user",
            "content": (
                "请使用 $web_search 搜索并阅读这个网页："
                "https://www.ijcai.org/proceedings/2025/ 。"
                "然后告诉我这个页面的标题、主要内容，以及它是不是 IJCAI 2025 的论文集页面。"
                "内容介绍200字左右"
            ),
        },
    ]

    finish_reason = None
    round_id = 1

    while finish_reason is None or finish_reason == "tool_calls":
        print(f"\n========== Round {round_id} ==========")

        choice, usage = chat(messages)
        finish_reason = choice.finish_reason
        message = choice.message

        print("finish_reason:", finish_reason)

        if finish_reason == "tool_calls":
            print("\n模型请求调用工具：")
            print(message.tool_calls)

            # 重要：把 assistant 的 tool_calls 消息加入上下文
            # 有些情况下需要显式带上 reasoning_content 字段，官方文档第二个示例也这样写。
            assistant_message = {
                "role": "assistant",
                "content": message.content,
                "tool_calls": message.tool_calls,
                "reasoning_content": getattr(
                    message,
                    "reasoning_content",
                    "I need to call search tool to get information.",
                ),
            }
            messages.append(assistant_message)

            for tool_call in message.tool_calls:
                tool_call_name = tool_call.function.name
                tool_call_arguments = json.loads(tool_call.function.arguments)

                if tool_call_name == "$web_search":
                    print("\n$web_search arguments:")
                    print(json.dumps(tool_call_arguments, ensure_ascii=False, indent=2)[:3000])

                    # 关键：原样返回 arguments
                    tool_result = search_impl(tool_call_arguments)
                else:
                    tool_result = {
                        "error": f"unknown tool: {tool_call_name}"
                    }

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call_name,
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    }
                )

            round_id += 1
            continue

        print("\n===== 最终回答 =====\n")
        print(message.content)

        if usage:
            print("\n===== token usage =====")
            print(usage)

        break


if __name__ == "__main__":
    main()