import asyncio
import random

from astrbot.api import logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star, register
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.config.default import VERSION
from astrbot.core.message.components import Image, Reply
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.provider.provider import Provider
from astrbot.core.utils.version_comparator import VersionComparator


@register("astrbot_plugin_emoji_like", "Zhalslar", "...", "...")
class EmojiLikePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        # 检查版本
        if not VersionComparator.compare_version(VERSION, "4.0.0") >= 0:
            raise Exception("AstrBot 版本过低, 请升级至 4.0.0 或更高版本")
        # 情感映射表
        self.emotions_mapping: dict[str, list[int]] = self.parse_emotions_mapping_list(
            self.config["emotions_mapping"]
        )
        # 可用情感关键字
        self.emotion_keywords: list[str] = list(self.emotions_mapping.keys())

    @staticmethod
    def parse_emotions_mapping_list(emotions_list: list[str]) -> dict[str, list[int]]:
        """解析字符串列表为字典"""
        emotions_dict = {}
        for item in emotions_list:
            emotion, values = item.split("：")
            emotions_dict[emotion] = list(map(int, values.split()))
        return emotions_dict

    @filter.command("贴表情")
    async def replyMessage(self, event: AiocqhttpMessageEvent, emojiNum: int = 5):
        """贴表情 <数量>"""
        chain = event.get_messages()
        if not chain:
            return
        seg = chain[0] if isinstance(chain[0], Reply) else None
        if not seg or not seg.chain:
            return
        text = seg.text
        message_id = seg.id
        images = []
        for reply_seg in seg.chain:
            if isinstance(reply_seg, Image):
                images.append(reply_seg)

        if not text or not message_id:
            return

        emotion = await self.judge_emotion(event, text, images)

        emoji_ids = []
        for keyword in self.emotion_keywords:
            if keyword in emotion:
                emoji_ids = self.emotions_mapping[keyword]
                break

        # 如果情感未命中或数量不足，用 1-433 随机补
        if not emoji_ids:
            emoji_ids = list(range(1, 434))
        need = min(emojiNum, 20)
        selected_emoji_ids = random.sample(emoji_ids, k=min(need, len(emoji_ids)))
        while len(selected_emoji_ids) < need:
            selected_emoji_ids.append(random.randint(1, 433))

        logger.info(
            f"选中的表情ID列表: {selected_emoji_ids}, 正在贴表情({len(selected_emoji_ids)}个)..."
        )
        for emoji_id in selected_emoji_ids:
            await event.bot.set_msg_emoji_like(
                message_id=message_id, emoji_id=emoji_id, set=True
            )
            await asyncio.sleep(self.config["emoji_interval"])
        event.stop_event()

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_message(self, event: AiocqhttpMessageEvent):
        """
        监听群消息，并进行情感分析

        """
        chain = event.get_messages()
        if not chain:
            return
        if event.is_at_or_wake_command:
            if random.random() > self.config["wake_analysis_prob"]:
                return
        else:
            if random.random() > self.config["normal_analysis_prob"]:
                return
        message_str = event.get_message_str()
        if not message_str:
            return

        emotion = await self.judge_emotion(event, message_str)
        message_id = event.message_obj.message_id

        for keyword in self.emotion_keywords:
            if keyword in emotion:
                emoji_id = random.choice(self.emotions_mapping[keyword])
                try:
                    await event.bot.set_msg_emoji_like(
                        message_id=message_id, emoji_id=emoji_id, set=True
                    )
                    logger.info(f"触发贴表情: [{keyword}{emoji_id}] -> {message_str}")
                except Exception as e:
                    logger.warning(f"设置表情失败: {e}")
                break

    async def judge_emotion(
        self,
        event: AiocqhttpMessageEvent,
        text: str,
        image_urls: list[str] | None = None,
    ):
        """让LLM判断语句的情感"""

        system_prompt = f"你是一个情感分析专家，请根据给定的文本判断其情感倾向，并给出相应的一个最符合的情感标签，可选标签有：{self.emotion_keywords}"
        prompt = "这是要分析的文本：" + text

        judge_provider = self.context.get_provider_by_id(
            self.config["judge_provider_id"]
        ) or self.context.get_using_provider(event.unified_msg_origin)

        if not isinstance(judge_provider, Provider):
            raise Exception("未找到可用的 LLM 提供商")
        try:
            logger.debug(
                f"使用{judge_provider.model_name}开始进行情感分析: {system_prompt} {prompt}"
            )
            llm_response = await judge_provider.text_chat(
                system_prompt=system_prompt,
                prompt=prompt,
                image_urls=image_urls,
            )

            return llm_response.completion_text.strip()
        except Exception as e:
            logger.error(f"情感分析失败: {e}")
            return "其他"
