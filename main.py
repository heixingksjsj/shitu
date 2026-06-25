# main.py
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import json
import astrbot.api.message_components as Comp

@register(
    name="astrbot_plugin_image_nsfw_guard",
    desc="QQ群图片色情检测自动撤回",
    version="1.0.9",
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
        logger.info("🔧 QQ插件触发 - 收到消息")

        if not self.enabled:
            logger.info("插件未启用")
            return

        # QQ专用强力图片提取
        images = []
        try:
            # 方法1：标准消息链
            if hasattr(event, "get_message_chain"):
                chain = event.get_message_chain()
                logger.info(f"消息链长度: {len(chain)}")
                for item in chain:
                    if isinstance(item, Comp.Image):
                        images.append(item)
                        logger.info(f"✅ 找到 Comp.Image: {getattr(item, 'url', '')[:100]}")
            
            # 方法2：直接从 message_obj.message (QQ最常见)
            if not images:
                msg_obj = getattr(event, "message_obj", event)
                message = getattr(msg_obj, "message", None) or getattr(event, "message", None)
                if isinstance(message, list):
                    for seg in message:
                        if isinstance(seg, dict) and seg.get("type") == "image":
                            images.append(seg)
                            logger.info(f"✅ 找到 dict image: {seg.get('data', {})}")
                        elif hasattr(seg, "type") and seg.type == "image":
                            images.append(seg)
                            logger.info("✅ 找到 Image 对象")
        except Exception as e:
            logger.error(f"提取图片异常: {e}")

        if not images:
            logger.info("❌ 本条消息未检测到图片")
            return

        logger.info(f"✅ 成功检测到 {len(images)} 张图片！开始 NSFW 审核...")

        # 白名单
        group_id = str(getattr(getattr(event, "message_obj", None), "group_id", None) or "")
        if group_id and group_id in [str(g) for g in self.whitelist_groups]:
            logger.info("白名单群，跳过")
            return

        try:
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
                logger.warning("无法提取图片URL")
                return

            prompt = (
                "内容审核：分析图片是否包含色情、裸露、性暗示等NSFW内容。\n"
                "只返回JSON：{\"is_nsfw\":true/false, \"confidence\":0.85, \"reason\":\"简短理由\"}"
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
                confidence = float(data.get("confidence", 0))
            except:
                is_nsfw = any(k in result_text.lower() for k in ["色情","nsfw","裸","porn"])
                confidence = 0.75

            if is_nsfw and confidence >= self.threshold:
                logger.warning("🚨 检测到NSFW，执行撤回！")
                await event.recall()
                if self.notify_user:
                    await event.send("⚠️ 你发送的图片包含不适宜内容，已自动撤回。请注意群规。", at_sender=True)
        except Exception as e:
            logger.error(f"审核失败: {e}")
