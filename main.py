# main.py
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import astrbot.api.message_components as Comp
import json
from typing import List

@register(
    name="astrbot_plugin_image_nsfw_guard",
    desc="图片色情检测自动撤回（使用已配置的 Vision 模型）",
    version="1.0.2",
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

    # 监听所有消息
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_image_message(self, event: AstrMessageEvent):
        if not self.enabled:
            return

        # 提取图片
        images: List[Comp.Image] = event.get_images()
        if not images:
            return

        # 白名单群过滤
        group_id = str(event.message_obj.group_id) if hasattr(event.message_obj, 'group_id') and event.message_obj.group_id else None
        if group_id and group_id in self.whitelist_groups:
            return

        logger.info(f"🔍 检测到 {len(images)} 张图片，正在进行 NSFW 审核...")

        try:
            prompt = (
                "内容审核任务：仔细分析图片，判断是否包含色情、裸露、性暗示等 NSFW 不适宜内容。\n"
                "严格只返回 JSON，不要任何其他文字：\n"
                "{\"is_nsfw\": true/false, \"confidence\": 0.85, \"reason\": \"简短理由\"}"
            )

            # 调用 Vision 模型（使用当前会话配置的模型）
            result = await self.context.get_llm_tool().chat(
                prompt=prompt,
                images=[img.url or img.file for img in images if img.url or img.file],
                session_id=event.session_id
            )

            result_text = result.completion_text.strip()
            logger.info(f"模型返回: {result_text}")

            # 解析结果
            try:
                data = json.loads(result_text)
                is_nsfw = data.get("is_nsfw", False)
                confidence = float(data.get("confidence", 0.0))
            except:
                is_nsfw = any(word in result_text.lower() for word in ["nsfw", "色情", "裸", "性", "porn"])
                confidence = 0.75

            if is_nsfw and confidence >= self.threshold:
                logger.warning(f"🚨 检测到 NSFW 内容 (置信度 {confidence:.2f})，执行撤回")

                await event.recall()   # 撤回消息

                if self.notify_user:
                    await event.send("⚠️ 你发送的图片包含不适宜内容，已自动撤回。请注意群规。", at_sender=True)

                # 可选通知管理员
                await event.send_to_admin(f"🚨 NSFW 撤回：用户 {event.get_sender_name()} 发送违规图片")

        except Exception as e:
            logger.error(f"NSFW 审核失败: {e}")

    # WebUI 配置界面
    def get_config(self):
        return {
            "enabled": {"type": "boolean", "default": True, "desc": "是否启用插件"},
            "threshold": {"type": "number", "default": 0.7, "desc": "置信度阈值 (0.0-1.0，越高越严格)"},
            "notify_user": {"type": "boolean", "default": True, "desc": "是否提醒发送者"},
            "whitelist_groups": {"type": "list", "default": [], "desc": "白名单群号（字符串列表）"}
            }
