# main.py
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import astrbot.api.message_components as Comp
import json
from typing import List

@register(
    name="astrbot_plugin_image_nsfw_guard",
    desc="图片色情检测自动撤回（支持指定 Vision 模型）",
    version="1.0.5",
    author="Grok 助手"
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

        # 兼容方式获取图片（修复 get_images() 不存在的问题）
        images = []
        try:
            # 方式1：尝试新版方法
            if hasattr(event, "get_images"):
                images = event.get_images()
            else:
                # 方式2：手动从消息链中提取图片（兼容 Aiocqhttp）
                msg_chain = event.get_message_chain() if hasattr(event, "get_message_chain") else getattr(event, "message", [])
                for comp in msg_chain:
                    if isinstance(comp, Comp.Image) or (hasattr(comp, "type") and comp.type == "image"):
                        images.append(comp)
        except:
            # 方式3：直接从 message_obj 中尝试
            try:
                msg_obj = getattr(event, "message_obj", None) or event
                if hasattr(msg_obj, "message") and isinstance(msg_obj.message, list):
                    for seg in msg_obj.message:
                        if isinstance(seg, dict) and seg.get("type") == "image":
                            images.append(seg)
            except:
                pass

        if not images:
            return

        group_id = str(event.message_obj.group_id) if hasattr(event.message_obj, "group_id") and event.message_obj.group_id else None
        if group_id and group_id in [str(g) for g in self.whitelist_groups]:
            return

        logger.info(f"🔍 检测到 {len(images)} 张图片，使用模型 {self.selected_provider or '默认'} 进行 NSFW 审核...")

        try:
            prompt = (
                "内容审核任务：仔细分析这张图片是否包含色情、裸露、性暗示等 NSFW 不适宜内容。\n"
                "只返回严格 JSON，不要任何其他文字：\n"
                "{\"is_nsfw\": true/false, \"confidence\": 0.85, \"reason\": \"简短理由\"}"
            )

            # 提取图片 URL 或 file 用于 Vision 模型
            image_inputs = []
            for img in images:
                if hasattr(img, "url") and img.url:
                    image_inputs.append(img.url)
                elif hasattr(img, "file") and img.file:
                    image_inputs.append(img.file)

            if not image_inputs:
                return

            llm_tool = self.context.get_llm_tool()
            result = await llm_tool.chat(
                prompt=prompt,
                images=image_inputs,
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
                is_nsfw = any(k in result_text.lower() for k in ["nsfw", "色情", "裸", "porn", "性"])
                confidence = 0.75

            if is_nsfw and confidence >= self.threshold:
                logger.warning(f"🚨 检测到 NSFW 内容 (置信度 {confidence:.2f})，执行撤回")
                await event.recall()

                if self.notify_user:
                    await event.send("⚠️ 你发送的图片包含不适宜内容，已自动撤回。请注意群规。", at_sender=True)

                await event.send_to_admin(f"🚨 NSFW 撤回：{event.get_sender_name()} 发送了违规图片")
        except Exception as e:
            logger.error(f"NSFW 审核出错: {e}")

    def get_config(self):
        return {}
