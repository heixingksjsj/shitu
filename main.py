# main.py
from astrbot.api.event import filter, AstrMessageEvent, EventMessageType
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import astrbot.api.message_components as Comp
from typing import List
import json

@register(
    name="astrbot_plugin_image_nsfw_guard",
    desc="图片色情检测自动撤回（使用已配置的 Vision 模型）",
    version="1.0.1",
    author="Grok 助手",
)
class ImageNSFWGuard(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.config = context.get_config() or {}
        self.enabled = self.config.get("enabled", True)
        self.threshold = self.config.get("threshold", 0.7)
        self.notify_user = self.config.get("notify_user", True)
        self.whitelist_groups = self.config.get("whitelist_groups", [])

    @filter.event_message_type(EventMessageType.ALL)  # 监听所有消息
    async def on_image_message(self, event: AstrMessageEvent):
        if not self.enabled:
            return

        # 检查消息中是否有图片
        images: List[Comp.Image] = event.get_images()
        if not images:
            return

        # 白名单群过滤
        group_id = str(event.message_obj.group_id) if event.message_obj.group_id else None
        if group_id and group_id in self.whitelist_groups:
            return

        logger.info(f"🔍 检测到图片消息，正在进行 NSFW 审核... (消息ID: {event.message_obj.message_id})")

        try:
            prompt = (
                "内容审核任务：仔细分析这张图片，判断是否包含色情、裸露、性暗示等 NSFW 不适宜内容。\n"
                "只返回严格的 JSON 格式，不要有任何其他文字：\n"
                "{\"is_nsfw\": true/false, \"confidence\": 0.85, \"reason\": \"简短理由\"}"
            )

            # 调用当前会话配置的 Vision 模型
            result = await self.context.get_llm_tool().chat(
                prompt=prompt,
                images=[img.url or img.file for img in images],
                session_id=event.session_id
            )

            result_text = result.completion_text.strip()
            logger.info(f"模型返回: {result_text}")

            # 解析 JSON
            try:
                data = json.loads(result_text)
                is_nsfw = data.get("is_nsfw", False)
                confidence = float(data.get("confidence", 0.0))
            except:
                is_nsfw = any(kw in result_text.lower() for kw in ["nsfw", "色情", "裸", "性"])
                confidence = 0.8

            if is_nsfw and confidence >= self.threshold:
                logger.warning(f"🚨 检测到 NSFW 内容 (置信度 {confidence})，执行撤回")

                await event.recall()  # 撤回图片

                if self.notify_user:
                    await event.send("⚠️ 你发送的图片包含不适宜内容，已自动撤回。请遵守群规。", at_sender=True)

                # 通知管理员（可选）
                await event.send_to_admin(f"🚨 NSFW 撤回提醒：用户 {event.get_sender_name()} 在群 {group_id} 发送了违规图片")

        except Exception as e:
            logger.error(f"图片审核过程出错: {e}")

    def get_config(self):
        return {
            "enabled": {"type": "boolean", "default": True, "desc": "是否启用插件"},
            "threshold": {"type": "number", "default": 0.7, "desc": "NSFW 置信度阈值 (0.0\~1.0，越高越严格)"},
            "notify_user": {"type": "boolean", "default": True, "desc": "是否提醒发送者"},
            "whitelist_groups": {"type": "list", "default": [], "desc": "白名单群号列表（字符串）"}
                         }
