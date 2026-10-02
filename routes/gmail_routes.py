import json
import os
from flask import Blueprint, redirect, request, session, url_for, jsonify, render_template
from flask_login import login_required
from google_auth_oauthlib.flow import Flow
from config import Config
from services.domain.tenant_service import TenantService

gmail_auth_bp = Blueprint("gmail_auth", __name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


@gmail_auth_bp.route("/gmail/settings")
@login_required
def settings_page():
    settings = TenantService.get_tenant_settings("default_tenant")

    # Gmail connection status
    gmail_connected = bool(settings and settings.gmail_token_json)

    # Parse existing notification emails (stored as comma-separated string)
    emails = []
    if settings and settings.notification_email:
        emails = [e.strip() for e in settings.notification_email.split(",") if e.strip()]

    # Check for status query param (post-OAuth redirect)
    status = request.args.get("status")

    return render_template(
        "settings.html",
        gmail_connected=gmail_connected,
        emails_json=json.dumps(emails, ensure_ascii=False),
        status=status,
    )


@gmail_auth_bp.route("/api/gmail/connect")
@login_required
def connect_gmail():
    flow = Flow.from_client_secrets_file(
        Config.GMAIL_CREDENTIALS_PATH,
        scopes=SCOPES,
        redirect_uri=url_for("gmail_auth.gmail_callback", _external=True)
    )
    
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )
    
    # 🔴 حفظ الـ state والـ code_verifier الخاص بالـ PKCE في الـ Session
    session["oauth_state"] = state
    if hasattr(flow, "code_verifier") and flow.code_verifier:
        session["code_verifier"] = flow.code_verifier
    
    return redirect(authorization_url)

@gmail_auth_bp.route("/api/gmail/callback")
def gmail_callback():
    code_verifier = session.get("code_verifier")
    
    flow = Flow.from_client_secrets_file(
        Config.GMAIL_CREDENTIALS_PATH,
        scopes=SCOPES,
        state=session.get("oauth_state"),
        redirect_uri=url_for("gmail_auth.gmail_callback", _external=True),
        code_verifier=code_verifier
    )
    
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials
    
    # حفظ التوكن في default_tenant عبر TenantService
    TenantService.save_gmail_credentials(credentials.to_json(), tenant_id="default_tenant")
        
    return redirect(url_for("gmail_auth.settings_page", status="gmail_success"))


@gmail_auth_bp.route("/api/gmail/save-recipient", methods=["POST"])
@login_required
def save_recipient():
    data = request.json
    tenant_id = session.get("tenant_id", "default_tenant")

    # Support both new multi-email format and legacy single-email format
    emails = data.get("emails")
    if emails and isinstance(emails, list):
        # Validate: max 3 emails
        if len(emails) > 3:
            return jsonify({"success": False, "message": "يمكن إضافة 3 إيميلات بحد أقصى."})
        # Join as comma-separated string for storage
        recipient_email = ", ".join(e.strip() for e in emails if e.strip())
    else:
        # Legacy single email support
        recipient_email = data.get("email", "").strip()

    if not recipient_email:
        return jsonify({"success": False, "message": "برجاء إدخال إيميل واحد على الأقل."})

    TenantService.save_notification_email(recipient_email, tenant_id=tenant_id)
    
    return jsonify({"success": True, "message": "تم حفظ إيميلات الاستقبال بنجاح."})