# main.py
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import json
import re

@register(
    name="astrbot_plugin_image_nsfw_guard",
    desc="QQ群图片色情检测自动撤回",
    version="1.2.0",
    author="Grok 助手 (基于 zhyx111999)"
)
class ImageNSFWGuard(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = config or context.get_config() or {}
        self.enabled = self.config.get("enabled", True)
        self.selected_provider = self.config.get("selected_provider", "")
        self.threshold = self.config.get("threshold", 0.7)
        self.notify_user = self.config.get("notify_user", True)
        self.whitelist_groups = self.config.get("whitelist_groups", [])

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_image_message(self, event: AstrMessageEvent):
        if not self.enabled:
            return

        image_urls = self._get_image_urls(event)
        if not image_urls:
            logger.info("❌ 未检测到有效图片")
            return

        logger.info(f"✅ 检测到 {len(image_urls)} 张图片，开始 NSFW 审核...")

        # 白名单过滤
        group_id = str(getattr(getattr(event, "message_obj", None), "group_id", None) or "")
        if group_id and group_id in [str(g) for g in self.whitelist_groups]:
            logger.info("白名单群，跳过")
            return

        try:
            prompt = (
                "内容审核任务：仔细分析这张图片是否包含色情、裸露、性暗示等NSFW内容。\n"
                "只返回JSON，不要其他任何内容：\n"
                "{\"is_nsfw\": true/false, \"confidence\": 0.85, \"reason\": \"简短理由\"}"
            )

            llm_tool = self.context.get_llm_tool()
            result = await llm_tool.chat(
                prompt=prompt,
                images=image_urls,
                session_id=event.session_id,
                provider_id=self.selected_provider if self.selected_provider else None
            )

            result_text = result.completion_text.strip()
            logger.info(f"模型返回: {result_text}")

            try:
                data = json.loads(result_text)
                is_nsfw = data.get("is_nsfw", False)
                confidence = float(data.get("confidence", 0.0))
            except:
                is_nsfw = any(k in result_text.lower() for k in ["色情","nsfw","裸","porn","性"])
                confidence = 0.75

            if is_nsfw and confidence >= self.threshold:
                logger.warning("🚨 检测到NSFW内容，执行撤回！")
                await event.recall()
                if self.notify_user:
                    await event.send("⚠️ 你发送的图片包含不适宜内容，已自动撤回。请注意群规。", at_sender=True)
        except Exception as e:
            logger.error(f"审核出错: {e}")

    def _get_image_urls(self, event: AstrMessageEvent):
        """完整版图片提取逻辑（直接参考对方仓库）"""
        urls = []
        try:
            # 原始消息结构
            original_event = getattr(event, "original_event", None)
            raw_msg = None
            if original_event and hasattr(original_event, "message"):
                raw_msg = original_event.message
            else:
                message_obj = getattr(event, "message_obj", event)
                raw_msg = getattr(message_obj, "message", None) or getattr(event, "message", None)

            if isinstance(raw_msg, list):
                for seg in raw_msg:
                    if isinstance(seg, dict) and seg.get("type") == "image":
                        data = seg.get("data", {}) or seg
                        url = data.get("url") or data.get("file") or data.get("path")
                        if url and url not in urls:
                            urls.append(url)
                            logger.info(f"✅ 找到图片URL: {url[:100]}...")

            # 组件方式补充
            if not urls and hasattr(event, "get_message_chain"):
                for comp in event.get_message_chain():
                    url = getattr(comp, "url", None) or getattr(comp, "file", None)
                    if url and url not in urls:
                        urls.append(url)
        except Exception as e:
            logger.error(f"提取图片失败: {e}")

        return urls
