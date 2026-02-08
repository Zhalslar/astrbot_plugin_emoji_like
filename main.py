import asyncio
import random

from astrbot.api import logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.message.components import Face, Image, Reply
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.provider.provider import Provider

from .config import PluginConfig


class EmojiLikePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.cfg = PluginConfig(config)

    async def judge_emotion(
        self,
        event: AiocqhttpMessageEvent,
        text: str,
        image_urls: list[str] | None = None,
    ) -> str:
        """LLM 情感判断"""
        if not self.cfg.llm_select:
            return "其他"
        system_prompt = (
            "你是一个情感分析专家，请判断文本情感，"
            f"只能从以下标签中选择一个：{self.cfg.emotion_keywords}"
        )
        prompt = f"文本内容：{text}"

        provider = self.context.get_provider_by_id(
            self.cfg.judge_provider_id
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

    async def emoji_like(
        self,
        event: AiocqhttpMessageEvent,
        emoji_ids: list[int],
        message_id: int | str | None = None,
    ):
        logger.info(f"贴表情: {emoji_ids}")
        message_id = message_id or event.message_obj.message_id
        for emoji_id in emoji_ids:
            try:
                await event.bot.set_msg_emoji_like(
                    message_id=message_id,
                    emoji_id=emoji_id,
                    set=True,
                )
            except Exception as e:
                logger.warning(f"贴表情失败: {e}")

            await asyncio.sleep(self.cfg.emoji_interval)

    @filter.command("贴表情")
    async def on_command(self, event: AiocqhttpMessageEvent, emojiNum: int = 5):
        """贴表情 <数量>"""
        chain = event.get_messages()
        if not chain:
            return
        reply = chain[0] if isinstance(chain[0], Reply) else None
        if not reply or not reply.chain or not reply.text or not reply.id:
            return

        images = [seg.url for seg in reply.chain if isinstance(seg, Image) and seg.url]

        emotion = await self.judge_emotion(event, reply.text, images)
        emoji_ids = self.cfg.get_emoji_ids(emotion, need_count=int(emojiNum))
        await self.emoji_like(event, emoji_ids, message_id=reply.id)
        event.stop_event()

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_message(self, event: AiocqhttpMessageEvent):
        """群消息监听"""
        if event.is_at_or_wake_command:
            return

        # 跟随已有表情
        chain = event.get_messages()
        emoji_ids = [seg.id for seg in chain if isinstance(seg, Face)]
        if emoji_ids and random.random() < self.cfg.emoji_follow_prob:
            await self.emoji_like(event, emoji_ids)

        # 主动表情
        msg = event.message_str
        if msg and random.random() < self.cfg.emoji_like_prob:
            asyncio.create_task(self.async_emoji_like_by_emotion(event, msg))

    async def async_emoji_like_by_emotion(
        self,
        event: AiocqhttpMessageEvent,
        text: str,
        image_urls: list[str] | None = None,
        message_id: int | str | None = None,
    ):
        emotion = await self.judge_emotion(event, text, image_urls)
        emoji_ids = self.cfg.get_emoji_ids(emotion, need_count=1)
        await self.emoji_like(event, emoji_ids, message_id=message_id)
