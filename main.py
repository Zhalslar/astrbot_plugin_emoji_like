import asyncio
import random
from astrbot.api import logger
from astrbot.api.star import Context, Star, register
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.api.event import filter

emotions_dict = {
    "开心": [2, 74, 109, 272, 295, 305, 318, 319, 324, 339],
    "得意": [4, 16, 28, 29, 99, 101, 178, 269, 270, 277, 283, 299, 307, 336, 426],
    "害羞": [6, 20, 21],
    "难过": [5, 34, 35, 36, 37, 173, 264, 265, 267, 425],
    "纠结": [106, 176, 262, 263, 270],
    "生气": [11, 26, 31, 105],
    "惊讶": [3, 325],
    "疑惑": [32, 268],
    "恳求": [111, 353],
    "可怕": [1, 286],
    "尴尬": [100, 306, 342, 344, 347],
    "无语": [46, 97, 181, 271, 281, 284, 287, 312, 352, 357, 427],
    "恶心": [19, 59, 323],
    "无聊": [8, 25, 285, 293],
}

@register(
    "astrbot_plugin_emoji_like",
    "Zhalslar",
    "调用LLM判断消息的情感，智能地给消息贴QQ表情",
    "1.0.0",
    "https://github.com/Zhalslar/astrbot_plugin_emoji_like",
)
class MyPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        # 情感映射表
        self.emotions_dict: dict[str, list[int]] = emotions_dict
        # 可用情感关键字
        self.emotion_keywords: list[str] = list(self.emotions_dict.keys())
        # 情感分析概率
        self.analysis_prob: float = config.get("analysis_prob", 0.1)

    @filter.command("贴表情")
    async def replyMessage(self, event: AiocqhttpMessageEvent, emojiNum: int = 5):
        """/贴表情 数量"""
        reply_text = next(
            (msg.text for msg in event.message_obj.message if msg.type == "Reply"), None  # type: ignore
        )
        if not reply_text:
            return
        message_id = next(
            (msg.id for msg in event.message_obj.message if msg.type == "Reply"), None  # type: ignore
        )

        emotion = await self.judge_emotion(reply_text)

        emoji_ids = []
        for keyword in self.emotion_keywords:
            if keyword in emotion:
                emoji_ids = self.emotions_dict[keyword]
                break

        selected_emoji_ids = random.sample(emoji_ids, k=min(emojiNum, len(emoji_ids)))

        for emoji_id in selected_emoji_ids:
            await event.bot.set_msg_emoji_like(
                message_id=message_id, emoji_id=emoji_id, set=True
            )
            await asyncio.sleep(0.2)
        event.stop_event()

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_message(self, event: AiocqhttpMessageEvent):
        """
        监听群消息，并进行情感分析

        """
        if random.random() > self.analysis_prob:
            return
        text = event.get_message_str()
        if not text:
            return
        message_id = event.message_obj.message_id
        emotion = await self.judge_emotion(text)

        for keyword in self.emotion_keywords:
            if keyword in emotion:
                emoji_id = random.choice(self.emotions_dict[keyword])
                await event.bot.set_msg_emoji_like(
                    message_id=message_id, emoji_id=emoji_id, set=True
                )
                break
        event.stop_event()

    async def judge_emotion(self, text: str):
        """让LLM判断语句的情感"""

        system_prompt = f"你是一个情感分析专家，请根据给定的文本判断其情感倾向，并给出相应的一个最符合的情感标签，可选标签有：{self.emotion_keywords}"

        try:
            llm_response = await self.context.get_using_provider().text_chat(
                prompt="这是要分析的文本：" + text,
                system_prompt=system_prompt,
                image_urls=[],
                func_tool=self.context.get_llm_tool_manager(),
            )

            return llm_response.completion_text.strip()
        except Exception as e:
            logger.error(f"情感分析失败: {e}")
            return "其他"


