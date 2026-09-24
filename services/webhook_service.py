import logging
import time
from typing import Optional

from models.models import db
from platforms.registry import get_handler
from platforms.facebook.handler import FacebookHandler
from platforms.facebook.parser import parse_facebook_message, parse_facebook_comment
from platforms.waha.handler import WahaHandler
from platforms.waha.parser import parse_waha_message
from schemas.incoming_message import IncomingMessage
from services.subscription_service import SubscriptionService
from services.page_service import PageService
from services.message_processor import run_agent
from services.message_queue import user_lock_manager, message_debouncer
from notification_center import send_production_alert
from config import Config


logger = logging.getLogger(__name__)


# ── Canonical Platform Lookup ─────────────────────────────────────────────────

def get_platform_id_for_facebook() -> int:
    """platform_id معرّف في FacebookHandler (ولازم يطابق id المنصة في جدول platforms)."""
    return FacebookHandler.platform_id


def get_platform_id_for_whatsapp() -> int:
    """platform_id معرّف في WahaHandler (ولازم يطابق id المنصة في جدول platforms)."""
    return WahaHandler.platform_id


# ── Feedback Helper ───────────────────────────────────────────────────────────

def build_post_booking_feedback_message(reference_id: Optional[str]) -> str:
    """Post-booking feedback message with a link to reference_id, or a generic version without one."""
    base_url = (Config.FEEDBACK_BASE_URL or "https://elbedawy-agent.revyai.tech").rstrip("/")
    if reference_id:
        url = f"{base_url}/feedback/{reference_id}"
        return f"يسعدنا تقييم تجربتك معنا من خلال الرابط التالي:\n{url}"
    return "يسعدنا تقييم تجربتك معنا ومشاركتنا رأيك لتحسين خدماتنا دائماً."


# ── Shared Helpers (used by both immediate replies and debounced agent replies) ──

def _fetch_page_and_check_quota(page_id: str, platform_id: int, log_prefix: str):
    """
    Look up the page for (page_id, platform_id) and verify its lab still has AI quota.
    Returns the page on success, or None (already logged) if the page is missing or quota is exhausted.
    """
    page = PageService.get_page_by_page_and_platform(page_id=page_id, platform_id=platform_id)
    if not page:
        logger.warning("[%s] Page not found: platform=%s page_id=%s", log_prefix, platform_id, page_id)
        return None

    allowed, reason = SubscriptionService.can_use_ai(page.laboratory_id)
    if not allowed:
        logger.warning(
            "[%s] Quota exhausted for lab=%s: %s. Dropping message silently.",
            log_prefix, page.laboratory_id, reason,
        )
        return None

    return page


def _send_reply(handler, user_id: str, reply: Optional[str], booking_pdf, visit_reference: Optional[str] = None):
    """Send the reply text, the booking PDF (if any), and the post-booking feedback message (if a PDF was sent)."""
    if reply:
        handler.send(user_id, reply)

    if booking_pdf:
        handler.send_image(recipient_id=user_id, file_bytes=booking_pdf, filename="booking_ticket.png")
        handler.send(user_id, build_post_booking_feedback_message(visit_reference))


# ── Debounce Flush Callback ───────────────────────────────────────────────────

def _make_flush_callback(platform_id: int, page_id: str, laboratory_id: int, app):
    """
    Build the callback that runs once a user's debounced messages are ready to send to the AI.
    Only captures plain values (not SQLAlchemy objects) since it runs in a background thread.
    """
    def on_flush(user_id: str, combined_text: str, combined_ocr_usage: Optional[dict]):
        with app.app_context():
            with user_lock_manager.lock_for_user(user_id):
                try:
                    page = _fetch_page_and_check_quota(page_id, platform_id, "ON_FLUSH")
                    if not page:
                        return

                    handler = get_handler(platform_id, page)
                    handler.send_typing(user_id)

                    incoming_msg = IncomingMessage(
                        sender_id=user_id,
                        page_id=page_id,
                        platform_id=platform_id,
                        platform_name=handler.platform_name,
                        msg_type="text",
                        text=combined_text,
                    )

                    reply, booking_pdf, visit_reference = run_agent(
                        incoming_msg,
                        ocr_usage=combined_ocr_usage,
                        laboratory_id=laboratory_id,
                    )
                    _send_reply(handler, user_id, reply, booking_pdf, visit_reference)

                except Exception as e:
                    logger.exception("[ON_FLUSH] Error processing agent response for user=%s: %s", user_id, e)
                    send_production_alert(
                        subject="Webhook Debounce Agent Execution Failure",
                        body_or_error=e,
                        context={
                            "platform_id": platform_id,
                            "page_id": page_id,
                            "laboratory_id": laboratory_id,
                            "error": str(e),
                        },
                    )
                    try:
                        fresh_page = PageService.get_page_by_page_and_platform(page_id=page_id, platform_id=platform_id)
                        if fresh_page:
                            handler = get_handler(platform_id, fresh_page)
                            handler.send(
                                user_id,
                                "عذرًا، حدث خطأ غير متوقع أثناء معالجة طلبك. يرجى المحاولة مرة أخرى بعد لحظات.",
                            )
                    except Exception:
                        logger.exception(
                            "[ON_FLUSH] Failed to send fallback error message to user=%s", user_id
                        )
                finally:
                    db.session.remove()

    return on_flush


# ── Message Dispatcher ────────────────────────────────────────────────────────

def dispatch_incoming_message(
    message: IncomingMessage,
    page_id: str,
    platform_id: int,
    laboratory_id: int,
    app,
):
    """
    Handle one incoming message:
    - immediate mode: reply right away
    - agent_text mode: queue it so the AI replies once the user stops typing (debounced)
    """
    with app.app_context():
        with user_lock_manager.lock_for_user(message.sender_id):
            try:
                page = _fetch_page_and_check_quota(page_id, platform_id, "DISPATCH")
                if not page:
                    return

                handler = get_handler(platform_id, page)
                prep_result = handler.prepare(message)
                if not prep_result:
                    return

                mode = prep_result[0]

                if mode == "immediate":
                    _, reply, pdf = prep_result
                    handler.send_typing(message.sender_id)
                    _send_reply(handler, message.sender_id, reply, pdf)

                elif mode == "agent_text":
                    _, text, ocr_usage = prep_result
                    handler.send_typing(message.sender_id)
                    flush_cb = _make_flush_callback(
                        platform_id=platform_id,
                        page_id=page_id,
                        laboratory_id=laboratory_id,
                        app=app,
                    )
                    received_at = getattr(message, "received_at", None) or time.time()
                    message_debouncer.add_message(
                        user_id=message.sender_id,
                        text=text,
                        ocr_usage=ocr_usage,
                        on_flush_callback=flush_cb,
                        received_at=received_at,
                    )

            except Exception as e:
                logger.exception("[DISPATCH] Error handling message from user: %s", e)
                send_production_alert(
                    subject="Webhook Message Dispatch Error",
                    body_or_error=e,
                    context={
                        "page_id": page_id,
                        "platform_id": platform_id,
                        "laboratory_id": laboratory_id,
                        "error": str(e),
                    },
                )
            finally:
                db.session.remove()


# ── Platform Webhook Processors ───────────────────────────────────────────────

def _process_facebook_entry(entry: dict, fb_platform_id: int, app):
    """Process one Facebook entry (one Page): its messaging events and its feed changes."""
    page_id = str(entry.get("id", "")).strip()
    if not page_id:
        return

    page = PageService.get_page_by_page_and_platform(page_id=page_id, platform_id=fb_platform_id)
    if not page:
        logger.warning("[FB WEBHOOK] Unknown page_id=%s for platform_id=%s", page_id, fb_platform_id)
        return

    # Read plain values once: dispatch_incoming_message calls db.session.remove(),
    # which can detach `page` on some Flask-SQLAlchemy versions.
    page_id_str = page.page_id
    laboratory_id = page.laboratory_id
    handler = get_handler(fb_platform_id, page)
    platform_name = handler.platform_name

    # 1. Direct user messaging events
    for messaging in entry.get("messaging", []):
        messages = parse_facebook_message(
            messaging=messaging,
            page_id=page_id_str,
            platform_id=fb_platform_id,
            platform_name=platform_name,
        )
        for msg in messages:
            dispatch_incoming_message(
                message=msg,
                page_id=page_id_str,
                platform_id=fb_platform_id,
                laboratory_id=laboratory_id,
                app=app,
            )

    # 2. Page feed changes (Facebook Comments)
    for change in entry.get("changes", []):
        comment_info = parse_facebook_comment(change)
        if comment_info and comment_info.get("comment_id"):
            comment_id = comment_info["comment_id"]
            target_page_id = comment_info.get("page_id") or page_id_str
            logger.debug("[FB WEBHOOK] Processing comment: %s", comment_id)
            handler.handle_comment(comment_id=comment_id, page_id=target_page_id)


def process_facebook_payload(payload: dict, app):
    """Background worker for Facebook webhook events: isolates each entry by Page ID, routes messages and comments."""
    with app.app_context():
        entries = payload.get("entry", [])
        try:
            fb_platform_id = get_platform_id_for_facebook()

            for entry in entries:
                # A failure in one page must not drop the remaining entries in the batch
                try:
                    _process_facebook_entry(entry, fb_platform_id, app)
                except Exception as e:
                    entry_id = entry.get("id") if isinstance(entry, dict) else None
                    logger.exception("[FB WEBHOOK] Entry processing error page_id=%s: %s", entry_id, e)
                    send_production_alert(
                        subject="Facebook Webhook Entry Exception",
                        body_or_error=e,
                        context={
                            "platform": "Facebook",
                            "page_id": entry_id,
                            "error": str(e),
                        },
                    )

        except Exception as e:
            logger.exception("[FB WEBHOOK] Worker processing error: %s", e)
            send_production_alert(
                subject="Facebook Webhook Worker Exception",
                body_or_error=e,
                context={
                    "platform": "Facebook",
                    "entries_count": len(entries),
                    "error": str(e),
                },
            )
        finally:
            db.session.remove()


def process_waha_payload(payload_data: dict, app):
    """
    Background worker for WAHA WhatsApp events. Resolves the receiving tenant strictly via me.lid/me.id
    with exact matching only (no fallback, no fuzzy matching) to keep tenants isolated.
    """
    with app.app_context():
        try:
            me_info = payload_data.get("me") or {}
            receiving_lid = me_info.get("lid") or me_info.get("id")

            if not receiving_lid:
                logger.warning("[WAHA WEBHOOK] Payload received without me.lid or me.id. Dropping message for tenant safety.")
                return

            whatsapp_platform_id = get_platform_id_for_whatsapp()
            receiving_lid_str = str(receiving_lid).strip()
            clean_lid = receiving_lid_str.split("@")[0]

            # Exact matching only: no fuzzy matching, no wildcard LIKE, no arbitrary fallback
            page = PageService.get_page_by_page_and_platform(
                page_id=receiving_lid_str,
                platform_id=whatsapp_platform_id,
            )
            if not page and clean_lid != receiving_lid_str:
                page = PageService.get_page_by_page_and_platform(
                    page_id=clean_lid,
                    platform_id=whatsapp_platform_id,
                )

            if not page:
                logger.warning(
                    "[WAHA WEBHOOK] Unknown receiving_lid=%s. No matching Page registered for WhatsApp platform=%s. "
                    "Halting message processing to ensure strict tenant isolation.",
                    receiving_lid_str, whatsapp_platform_id,
                )
                return

            page_id_str = page.page_id
            laboratory_id = page.laboratory_id
            handler = get_handler(whatsapp_platform_id, page)

            inner_payload = payload_data.get("payload", {})
            if not inner_payload:
                return

            msg = parse_waha_message(
                payload=inner_payload,
                page_id=page_id_str,
                platform_id=whatsapp_platform_id,
                platform_name=handler.platform_name,
            )

            if msg:
                dispatch_incoming_message(
                    message=msg,
                    page_id=page_id_str,
                    platform_id=whatsapp_platform_id,
                    laboratory_id=laboratory_id,
                    app=app,
                )

        except Exception as e:
            logger.exception("[WAHA WEBHOOK] Worker processing error: %s", e)
            send_production_alert(
                subject="WAHA Webhook Worker Exception",
                body_or_error=e,
                context={
                    "platform": "WhatsApp",
                    "event": payload_data.get("event"),
                    "has_payload": bool(payload_data.get("payload")),
                    "error": str(e),
                },
            )
        finally:
            db.session.remove()