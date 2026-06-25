# main.py
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import json

@register(
    name="astrbot_plugin_image_nsfw_guard",
    desc="QQ群图片色情检测自动撤回",
    version="1.0.8",
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
        logger.info("🔧 QQ群插件触发 - 收到消息")

        if not self.enabled:
            return

        # ==================== QQ专用图片提取 ====================
        images = []
        try:
            # QQ 最常见的结构
            message_obj = getattr(event, "message_obj", None) or event
            message_list = getattr(message_obj, "message", None) or getattr(event, "message", None)

            if isinstance(message_list, list):
                for seg in message_list:
                    if isinstance(seg, dict) and seg.get("type") == "image":
                        images.append(seg)
                        logger.info(f"✅ 找到QQ图片: {seg.get('data', {}).get('url', '无url')}")
                    elif hasattr(seg, "type") and seg.type == "image":
                        images.append(seg)
                        logger.info("✅ 找到Image对象")

            # 备用方法
            if not images and hasattr(event, "get_message_chain"):
                for item in event.get_message_chain():
                    if str(type(item)).find("Image") != -1 or getattr(item, "type", None) == "image":
                        images.append(item)
        except Exception as e:
            logger.error(f"提取图片失败: {e}")

        if not images:
            logger.info("未检测到图片")
            return

        logger.info(f"✅ 检测到 {len(images)} 张QQ图片，开始审核...")

        # 白名单过滤
        group_id = str(getattr(getattr(event, "message_obj", None), "group_id", None) or "")
        if group_id and group_id in [str(g) for g in self.whitelist_groups]:
            logger.info(f"白名单群 {group_id}，跳过")
            return

        try:
            # 提取图片URL
            image_inputs = []
            for img in images:
                if isinstance(img, dict):
                    data = img.get("data", {})
                    url = data.get("url") or data.get("file")
                else:
                    url = getattr(img, "url", None) or getattr(img, "file", None)
                if url:
                    image_inputs.append(url)

            if not image_inputs:
                logger.warning("无法获取图片URL")
                return

            prompt = (
                "这是一个内容审核任务。请分析图片是否包含色情、裸露、性暗示等NSFW内容。\n"
                "只返回JSON，不要其他任何内容：\n"
                "{\"is_nsfw\": true/false, \"confidence\": 0.8, \"reason\": \"简短理由\"}"
            )

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
                is_nsfw = any(k in result_text.lower() for k in ["色情","nsfw","裸","porn","性"])
                confidence = 0.75

            if is_nsfw and confidence >= self.threshold:
                logger.warning("🚨 检测到NSFW内容，执行撤回！")
                await event.recall()
                if self.notify_user:
                    await event.send("⚠️ 你发送的图片包含不适宜内容，已自动撤回。请注意群规。", at_sender=True)
        except Exception as e:
            logger.error(f"审核过程出错: {e}")
