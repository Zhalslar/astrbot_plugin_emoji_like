import asyncio
import random
from typing import Final

from astrbot.api import logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.message.components import Face, Image, Reply
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.provider.provider import Provider


class EmojiLikePlugin(Star):
    """
    贴表情插件

    特性：
    - 表情选用策略可配置
    - LLM 情感分析按需调用
    - 所有路径弱一致、可降级
    """

    # ---------- 1. 表情号段常量 ----------
    EMOJI_RANGE_START: Final[int] = 1  # 范围起点
    EMOJI_RANGE_END: Final[int] = 434  # 范围终点（不含）

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

        # 情感映射
        self.emotions_mapping: dict[str, list[int]] = self.parse_emotions_mapping_list(
            self.config.get("emotions_mapping", [])
        )
        self.emotion_keywords: list[str] = list(self.emotions_mapping.keys())
        # 表情池
        self.emoji_pool = list(range(self.EMOJI_RANGE_START, self.EMOJI_RANGE_END))

    @staticmethod
    def parse_emotions_mapping_list(
        emotions_list: list[str],
    ) -> dict[str, list[int]]:
        """
        ["开心：1 2 3", "愤怒：4 5"] -> {"开心": [1,2,3], "愤怒": [4,5]}
        """
        result: dict[str, list[int]] = {}
        for item in emotions_list:
            try:
                emotion, values = item.split("：", 1)
                result[emotion.strip()] = list(map(int, values.split()))
            except Exception:
                logger.warning(f"无法解析情感映射项: {item}")
        return result

    def select_emoji_ids(
        self,
        *,
        emotion: str | None,
        need: int,
    ) -> list[int]:
        """
        表情选用策略入口
        """
        strategy = self.config.get("emoji_select_strategy", "random")

        if strategy == "random":
            return self._select_random(need)

        if strategy == "emotion_llm":
            return self._select_by_emotion(emotion, need)

        logger.warning(f"未知表情策略: {strategy}, 回退 random")
        return self._select_random(need)

    def _select_random(self, need: int) -> list[int]:
        return random.sample(self.emoji_pool, k=min(need, len(self.emoji_pool)))

    def _select_by_emotion(
        self,
        emotion: str | None,
        need: int,
    ) -> list[int]:
        if not emotion:
            return self._select_random(need)

        for keyword in self.emotion_keywords:
            if keyword in emotion:
                pool = self.emotions_mapping.get(keyword)
                if pool:
                    selected = random.sample(pool, k=min(need, len(pool)))
                    while len(selected) < need:
                        selected.append(random.choice(self.emoji_pool))
                    return selected

        return self._select_random(need)

    @filter.command("贴表情")
    async def replyMessage(
        self,
        event: AiocqhttpMessageEvent,
        emojiNum: int = 5,
    ):
        chain = event.get_messages()
        if not chain:
            return

        reply = chain[0] if isinstance(chain[0], Reply) else None
        if not reply or not reply.chain:
            return

        text = reply.text
        message_id = reply.id
        images = [seg.url for seg in reply.chain if isinstance(seg, Image) and seg.url]

        if not text or not message_id:
            return

        emotion = None
        if self.config.get("emoji_select_strategy") == "emotion_llm":
            emotion = await self.judge_emotion(event, text, images)

        need = min(int(emojiNum), 20)
        emoji_ids = self.select_emoji_ids(
            emotion=emotion,
            need=need,
        )

        logger.info(f"贴表情: {emoji_ids}")

        for emoji_id in emoji_ids:
            await event.bot.set_msg_emoji_like(
                message_id=message_id,
                emoji_id=emoji_id,
                set=True,
            )
            await asyncio.sleep(self.config.get("emoji_interval", 0.5))

        event.stop_event()

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_message(self, event: AiocqhttpMessageEvent):
        """群消息监听"""
        chain = event.get_messages()
        if not chain:
            return

        message_str = event.get_message_str()
        if not message_str:
            return

        if event.is_at_or_wake_command:
            return

        # 跟随已有表情
        face_segs = [seg for seg in chain if isinstance(seg, Face)]
        if face_segs and random.random() < self.config.get("emoji_follow", 0):
            face = random.choice(face_segs)
            try:
                await event.bot.set_msg_emoji_like(
                    message_id=event.message_obj.message_id,
                    emoji_id=face.id,
                    set=True,
                )
            except Exception as e:
                logger.warning(f"表情跟随失败: {e}")

        # 主动表情
        if random.random() < self.config.get("emoji_like_prob", 0):
            emotion = None
            if self.config.get("emoji_select_strategy") == "emotion_llm":
                emotion = await self.judge_emotion(event, message_str)

            emoji_ids = self.select_emoji_ids(
                emotion=emotion,
                need=1,
            )
            if not emoji_ids:
                return

            try:
                await event.bot.set_msg_emoji_like(
                    message_id=event.message_obj.message_id,
                    emoji_id=emoji_ids[0],
                    set=True,
                )
            except Exception as e:
                logger.warning(f"设置表情失败: {e}")

    async def judge_emotion(
        self,
        event: AiocqhttpMessageEvent,
        text: str,
        image_urls: list[str] | None = None,
    ) -> str:
        """LLM 情感判断"""
        system_prompt = (
            "你是一个情感分析专家，请判断文本情感，"
            f"只能从以下标签中选择一个：{self.emotion_keywords}"
        )
        prompt = f"文本内容：{text}"

        provider = self.context.get_provider_by_id(
            self.config["judge_provider_id"]
        ) or self.context.get_using_provider(event.unified_msg_origin)

        if not isinstance(provider, Provider):
            logger.error("未找到可用的 LLM Provider")
            return "其他"

        try:
            resp = await provider.text_chat(
                system_prompt=system_prompt,
                prompt=prompt,
                image_urls=image_urls,
            )
            return resp.completion_text.strip()
        except Exception as e:
            logger.error(f"情感分析失败: {e}")
            return "其他"
