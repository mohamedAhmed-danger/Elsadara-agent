import logging
import os
import uuid
from typing import Optional, Tuple

from services.ocr_service import analyze_prescription_image
from services.client_service import ClientService
from services.inquiry_service import InquiryService
from utils.usage_calculator import calc_total_usage
from services.subscription_consumer import consume_subscription
from models.models import Status
from notification_center import send_production_alert
from utils.trace_logger import trace_logger

logger = logging.getLogger(__name__)

# ── Image validity check (magic bytes) ──────────────────────────────────────
# بنتأكد إن الـ bytes اللي وصلتنا فعلاً صورة (JPEG/PNG/WEBP/GIF) مش رد خطأ أو صفحة HTML
# كل signature هنا مرتبطة بامتداد الملف الصحيح، عشان نحفظ الملف بامتداده الحقيقي
# بدل ما نفترض .jpg دايمًا (ده كان بيسبب مشكلة تحديد mime type غلط لصور GIF لاحقًا).
_IMAGE_SIGNATURES = (
    (b"\xff\xd8\xff", "jpg"),        # JPEG
    (b"\x89PNG\r\n\x1a\n", "png"),   # PNG
    (b"GIF87a", "gif"),              # GIF
    (b"GIF89a", "gif"),              # GIF
)


def _detect_image_extension(image_bytes: bytes) -> Optional[str]:
    """Return the correct file extension based on magic bytes, or None if unrecognized."""
    for signature, extension in _IMAGE_SIGNATURES:
        if image_bytes.startswith(signature):
            return extension
    # WEBP needs a two-part check: RIFF header AND "WEBP" at bytes 8-16,
    # otherwise any other RIFF-based format (e.g. WAV, AVI) would false-match.
    if image_bytes.startswith(b"RIFF") and len(image_bytes) >= 16 and b"WEBP" in image_bytes[8:16]:
        return "webp"
    return None


def _looks_like_valid_image(image_bytes: bytes) -> bool:
    """Verifies image bytes match a known image magic byte signature."""
    if not image_bytes or len(image_bytes) < 16:
        return False
    return _detect_image_extension(image_bytes) is not None


def _save_prescription_image(image_bytes: bytes, sender_id: str) -> Tuple[str, str]:
    """Writes image bytes to disk with their real extension and returns (filename, absolute_path)."""
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    uploads_dir = os.path.join(project_dir, "static", "uploads")
    os.makedirs(uploads_dir, exist_ok=True)

    extension = _detect_image_extension(image_bytes) or "jpg"
    filename = f"{uuid.uuid4().hex}.{extension}"
    image_path = os.path.join(uploads_dir, filename)
    with open(image_path, "wb") as f:
        f.write(image_bytes)

    logger.info(
        "[PRESCRIPTION INTAKE] Saved Image: %s | sender_id=%s",
        image_path, sender_id,
    )
    trace_logger.step(
        "Prescription Image Ingested",
        input_data={
            "sender_id": sender_id,
            "image_path": image_path,
            "bytes_len": len(image_bytes),
        },
    )
    return filename, image_path


def _handle_non_prescription(message, ocr_usage: dict) -> dict:
    """Handles images classified as non-prescription/spam."""
    spam_reply = "عذراً، يبدو أن الصورة المرفقة ليست روشتة طبية واضحة. يرجى إرسال صورة روشتة صحيحة لطلب التحاليل."
    client_service = ClientService(
        platform_id=message.platform_id,
        page_id=message.page_id,
        sender_id=message.sender_id,
    )
    client_service.save_chat_exchange(
        user_message=message.text or "[صورة مرفقة]",
        bot_reply=spam_reply,
        summary="User sent an image that was classified as not a prescription or spam.",
    )

    if ocr_usage:
        usage = calc_total_usage({}, ocr_usage=ocr_usage)
        consume_subscription(message, usage)

    trace_logger.step(
        "Prescription Decision: Non-Prescription",
        input_data={"is_prescription": False, "reply": spam_reply},
    )
    return {"mode": "immediate", "reply": spam_reply, "pdf": None}


def _determine_prescription_pending(ocr_result) -> bool:
    """Returns True if prescription requires manual doctor review due to low confidence."""
    if not ocr_result.tests:
        return True
    return any(test.confidence < 0.70 for test in ocr_result.tests)


def _save_inquiry_record(message, page, filename: str, ocr_result, pending: bool) -> float:
    """Persists prescription inquiry in DB and returns min_confidence score."""
    inquiry_service = InquiryService()
    min_confidence = min((t.confidence for t in ocr_result.tests), default=0.0)
    services_mentioned = ", ".join(t.name for t in ocr_result.tests) if ocr_result.tests else None

    inquiry_result = inquiry_service.save_inquiry(
        laboratory_id=page.laboratory_id if page else 1,
        phone_number="",
        comes_from=f"{message.platform_name}:{message.sender_id}:{message.page_id}",
        prescription_img=filename,
        ocr_extracted_text=ocr_result.extracted_text,
        confidence_score=min_confidence,
        services_mentioned=services_mentioned,
        status=Status.PENDING if pending else Status.REVIEWED,
    )

    logger.info(
        "[PRESCRIPTION INQUIRY SAVED] Inquiry ID: %s | Status: %s",
        inquiry_result.inquiry.id if inquiry_result and inquiry_result.inquiry else "None",
        Status.PENDING.value if pending else Status.REVIEWED.value,
    )
    trace_logger.log_db_operation(
        "save_inquiry",
        "inquiries",
        success=True,
        extra={"status": Status.PENDING.value if pending else Status.REVIEWED.value, "min_confidence": min_confidence},
    )
    return min_confidence


def _handle_pending_review(message, ocr_usage: dict, min_confidence: float) -> dict:
    """Handles low-confidence flow with static doctor review reply."""
    static_reply = "لقد استلمنا صورتك وسيقوم الطبيب بمراجعتها والرد عليك ."
    client_service = ClientService(
        platform_id=message.platform_id,
        page_id=message.page_id,
        sender_id=message.sender_id,
    )
    client_service.save_chat_exchange(
        user_message=message.text or "[صورة روشتة]",
        bot_reply=static_reply,
        summary="User uploaded a prescription image. Waiting for manual doctor review on dashboard.",
    )

    if ocr_usage:
        usage = calc_total_usage({}, ocr_usage=ocr_usage)
        consume_subscription(message, usage)

    trace_logger.step(
        "Prescription Decision: Pending Review",
        input_data={"status": "PENDING", "min_confidence": min_confidence, "reply": static_reply},
    )
    return {"mode": "immediate", "reply": static_reply, "pdf": None}


def _handle_reviewed_prescription(ocr_result, ocr_usage: dict) -> dict:
    """Builds agent query text for high-confidence prescription tests."""
    extracted_tests = [t.name for t in ocr_result.tests if t.name]
    tests_list = ", ".join(extracted_tests)
    agent_text = (
        f"[Prescription OCR Extracted Tests]: {tests_list}\n"
        f"Please provide full details, preparations needed, and prices for these tests."
    )
    trace_logger.step(
        "Prescription Decision: Routed to Agent",
        input_data={"status": "REVIEWED", "tests_count": len(extracted_tests), "tests": extracted_tests},
    )
    return {"mode": "agent", "text": agent_text, "ocr_usage": ocr_usage}


def extract_prescription_payload(image_bytes: bytes, message, page) -> dict:
    """
    Ingests prescription image bytes, performs OCR analysis, and routes to either:
    - {"mode": "agent", "text": "...", "ocr_usage": {...}} -> debounce buffer
    - {"mode": "immediate", "reply": "...", "pdf": None} -> immediate response
    """
    try:
        if not _looks_like_valid_image(image_bytes):
            logger.error(
                "[PRESCRIPTION INTAKE] Received invalid/corrupt image bytes (len=%s) | sender_id=%s",
                len(image_bytes) if image_bytes else 0, message.sender_id,
            )
            trace_logger.step(
                "Prescription Intake Rejected: Invalid Image Bytes",
                input_data={"sender_id": message.sender_id, "bytes_len": len(image_bytes) if image_bytes else 0},
            )
            send_production_alert(
                subject="Prescription Intake: Corrupt/Empty Image Received",
                body_or_error="Downloaded media did not match any known image signature.",
                context={
                    "sender_id": message.sender_id,
                    "page_id": message.page_id,
                    "platform": message.platform_name,
                    "bytes_len": len(image_bytes) if image_bytes else 0,
                },
            )
            error_reply = "عذرًا، لم نتمكن من استقبال الصورة بشكل صحيح. يرجى محاولة إرسالها مرة أخرى."
            return {"mode": "immediate", "reply": error_reply, "pdf": None}

        filename, image_path = _save_prescription_image(image_bytes, message.sender_id)
        ocr_result, ocr_usage = analyze_prescription_image(image_path)

        logger.info(
            "[PRESCRIPTION OCR RESULT]\n"
            "   Sender ID:        %s\n"
            "   Is Prescription:  %s\n"
            "   Tests Found:      %s\n"
            "   Tokens Used:      %s",
            message.sender_id,
            ocr_result.is_prescription,
            [f"{t.name} ({t.confidence:.2f})" for t in ocr_result.tests],
            ocr_usage.get("total_tokens", 0) if ocr_usage else 0,
        )

        # Step A: Classification check (not a prescription / spam)
        if not ocr_result.is_prescription:
            return _handle_non_prescription(message, ocr_usage)

        # Step B: Confidence check & persistence
        pending = _determine_prescription_pending(ocr_result)
        min_confidence = _save_inquiry_record(message, page, filename, ocr_result, pending)

        if pending:
            return _handle_pending_review(message, ocr_usage, min_confidence)

        # Step C: Reviewed flow -> ALL tests >= 0.70
        return _handle_reviewed_prescription(ocr_result, ocr_usage)

    except Exception as e:
        logger.exception(
            "[extract_prescription_payload] Error | sender_id=%s", message.sender_id,
        )
        trace_logger.error(f"extract_prescription_payload error: {e}")
        send_production_alert(
            subject="Prescription Intake / OCR Failure",
            body_or_error=e,
            context={
                "sender_id": message.sender_id,
                "page_id": message.page_id,
                "platform": message.platform_name,
            },
        )
        return {"mode": "immediate", "reply": "عذرًا، حدث خطأ أثناء معالجة الصورة المرفقة. يرجى المحاولة مرة أخرى.", "pdf": None}