# main.py
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import astrbot.api.message_components as Comp
import json

@register(
    name="astrbot_plugin_image_nsfw_guard",
    desc="图片色情检测自动撤回（支持指定 Vision 模型）",
    version="1.0.6",
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
        logger.info("🔧 插件事件触发成功！收到一条消息")
        
        if not self.enabled:
            logger.info("插件已禁用")
            return

        # 强力图片检测
        images = []
        try:
            # 方式1
            if hasattr(event, "get_images"):
                images = event.get_images()
                logger.info(f"使用 get_images() 找到 {len(images)} 张图片")
            # 方式2
            if not images:
                chain = event.get_message_chain() if hasattr(event, "get_message_chain") else getattr(event, "message", [])
                for item in chain:
                    if isinstance(item, Comp.Image) or getattr(item, "type", None) == "image":
                        images.append(item)
                logger.info(f"从消息链找到 {len(images)} 张图片")
        except Exception as e:
            logger.error(f"提取图片失败: {e}")

        if not images:
            logger.info("未检测到图片，跳过")
            return

        logger.info(f"✅ 成功检测到 {len(images)} 张图片，开始 NSFW 审核...")

        # 白名单检查
        group_id = str(getattr(event.message_obj, "group_id", None) or "")
        if group_id and group_id in [str(g) for g in self.whitelist_groups]:
            logger.info(f"群 {group_id} 在白名单中，跳过审核")
            return

        try:
            prompt = (
                "内容审核：这张图片是否包含色情、裸露、性暗示等NSFW内容？\n"
                "只返回JSON：{\"is_nsfw\": true/false, \"confidence\": 0.8, \"reason\": \"理由\"}"
            )

            image_inputs = []
            for img in images:
                url = getattr(img, "url", None) or getattr(img, "file", None)
                if url:
                    image_inputs.append(url)

            if not image_inputs:
                logger.warning("无法获取图片URL")
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
                confidence = float(data.get("confidence", 0))
            except:
                is_nsfw = "色情" in result_text or "nsfw" in result_text.lower()
                confidence = 0.75

            if is_nsfw and confidence >= self.threshold:
                logger.warning("🚨 检测到NSFW，执行撤回！")
                await event.recall()
                if self.notify_user:
                    await event.send("⚠️ 你发送的图片包含不适宜内容，已自动撤回。", at_sender=True)
        except Exception as e:
            logger.error(f"审核过程出错: {e}")
