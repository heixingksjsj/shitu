# main.py
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import astrbot.api.message_components as Comp
from typing import List

@register(
    name="astrbot_plugin_image_nsfw_guard",
    desc="图片色情检测自动撤回（使用已配置的 Vision 模型）",
    version="1.0.0",
    author="Grok 助手",
)
class ImageNSFWGuard(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 默认配置（可在 WebUI 插件配置中修改）
        self.config = context.get_config() or {}
        self.enabled = True
        self.threshold = 0.7  # 置信度阈值
        self.notify_user = True
        self.whitelist_groups = []  # 白名单群号列表

    @filter.on_message()
    async def on_image_message(self, event: AstrMessageEvent):
        if not self.enabled:
            return

        # 检查是否包含图片
        images: List[Comp.Image] = event.get_images()
        if not images:
            return

        # 白名单过滤
        if event.message_obj.group_id and str(event.message_obj.group_id) in self.whitelist_groups:
            return

        logger.info(f"检测到图片消息，准备进行 NSFW 分析... (消息ID: {event.message_obj.message_id})")

        try:
            # 使用当前会话配置的 LLM（Vision 模型）进行分析
            prompt = (
                "这是一个内容审核任务。请仔细分析图片，判断是否包含色情、裸露、性暗示等 NSFW 内容。\n"
                "只返回 JSON 格式：{\"is_nsfw\": true/false, \"confidence\": 0.0-1.0, \"reason\": \"简短理由\"}\n"
                "不要输出其他任何内容。"
            )

            # 构造带图片的消息链给 LLM
            analysis_event = event.copy()
            analysis_result = await self.context.get_llm_tool().chat(
                prompt=prompt,
                images=[img.url or img.file for img in images if img.url or img.file],
                session_id=event.session_id  # 使用当前会话的模型配置
            )

            result_text = analysis_result.completion_text.strip()
            logger.info(f"模型返回: {result_text}")

            # 简单解析 JSON
            import json
            try:
                data = json.loads(result_text)
                is_nsfw = data.get("is_nsfw", False)
                confidence = float(data.get("confidence", 0))
            except:
                # 容错解析
                is_nsfw = "nsfw" in result_text.lower() or "色情" in result_text
                confidence = 0.8

            if is_nsfw and confidence >= self.threshold:
                logger.warning(f"检测到 NSFW 内容 (置信度: {confidence})，准备撤回")

                # 尝试撤回（安卓版/Qq 适配器支持）
                await event.recall()

                if self.notify_user:
                    notify_msg = "⚠️ 你发送的图片包含不适宜内容，已自动撤回。请注意群规。"
                    await event.send(notify_msg, at_sender=True)

                # 可选：记录日志或通知管理员
                await event.send_to_admin(f"🚨 NSFW 撤回：用户 {event.get_sender_name()} 发送了违规图片")

        except Exception as e:
            logger.error(f"图片审核失败: {e}")

    # 插件配置（WebUI 支持）
    def get_config(self):
        return {
            "enabled": {"type": "boolean", "default": True, "desc": "是否启用插件"},
            "threshold": {"type": "number", "default": 0.7, "desc": "NSFW 置信度阈值 (0.0-1.0)"},
            "notify_user": {"type": "boolean", "default": True, "desc": "是否提醒发送者"},
            "whitelist_groups": {"type": "list", "default": [], "desc": "白名单群号 (字符串列表)"}
}
