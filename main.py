import asyncio
import json
import random
from astrbot.api import logger
from astrbot.api.star import Context, Star, register
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.api.event import filter
from .emoji_code import emoji_list

@register("astrbot_plugin_emoji_like", "Zhalslar", "智能贴表情", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    # 使用指令的方式贴表情
    @filter.command("贴表情")
    async def replyMessage(self, event: AiocqhttpMessageEvent, emojiNum: int = 0):
        """/贴表情 数量"""
        if emojiNum <= 0:
            emojiNum = random.randint(1, 20)
        elif emojiNum > 20:
            emojiNum = 20

        # 获取转发消息id
        message_id = next((msg.id for msg in event.message_obj.message if msg.type == "Reply"), None) # type: ignore
        if not message_id:
            return

        rand_emoji_list = random.sample(emoji_list, emojiNum)
        for id in rand_emoji_list:
            await event.bot.set_msg_emoji_like(
                message_id=message_id, emoji_id=id, set=True
            )
            await asyncio.sleep(0.2)

    # async def ai_supervisor(self):
    #     """让LLM监工"""

    #     func_tools_mgr = self.context.get_llm_tool_manager()

    #     system_prompt = {}

    #     try:
    #         llm_response = await self.context.get_using_provider().text_chat(
    #             prompt="他来水群了",
    #             contexts=[{"role": "system", "content": system_prompt}],
    #             image_urls=[],
    #             func_tool=func_tools_mgr,
    #         )

    #         return " " + llm_response.completion_text
    #     except Exception as e:
    #         logger.error(f"LLM 监工失败: {e}")