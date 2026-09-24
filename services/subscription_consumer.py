import logging

from services.page_service import PageService
from notification_center import send_production_alert
from services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)


def consume_subscription(message, usage: dict) -> None:
    """يخصم من رصيد اشتراك المعمل بناءً على عدد الرسائل المستهلكة والتكلفة."""
    

    try:
        page = PageService.get_page_by_page_and_platform(
            page_id=message.page_id,
            platform_id=message.platform_id,
        )

        if not page:
            logger.warning(
                "[consume_subscription] No page found for page_id=%s platform_id=%s",
                message.page_id, message.platform_id,
            )
            return

        subscription = SubscriptionService.get_by_page(page)

        if not subscription:
            logger.warning(
                "[consume_subscription] No subscription found for laboratory_id=%s",
                page.laboratory_id,
            )
            return

        # بنشيك هل الـ OCR تم استخدامه في العملية دي ولا لأ
        used_ocr = "ocr_vision_usage" in usage.get("breakdown", {})
        messages_to_deduct = 2 if used_ocr else 1

        SubscriptionService.consume(
            subscription,
            count=messages_to_deduct,
            cost=usage.get("total_cost_usd", 0.0),
        )

    except Exception as e:
        logger.exception("❌ [consume_subscription] Error deducting messages: %s", e)
        send_production_alert(
            subject="Subscription Consumption Failure",
            body_or_error=e,
            context={
                "page_id": message.page_id,
                "platform_id": message.platform_id,
                "sender_id": message.sender_id,
                "usage": usage,
            },
        )