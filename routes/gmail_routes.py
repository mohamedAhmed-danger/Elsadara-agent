import os
from flask import Blueprint, redirect, request, session, url_for, jsonify, render_template
from google_auth_oauthlib.flow import Flow
from config import Config
from services.tenant_service import TenantService

gmail_auth_bp = Blueprint("gmail_auth", __name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


@gmail_auth_bp.route("/gmail/settings")
def settings_page():
    return render_template("settings.html")


@gmail_auth_bp.route("/api/gmail/connect")
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
def save_recipient():
    data = request.json
    recipient_email = data.get("email")
    tenant_id = session.get("tenant_id", "default_tenant")
    
    TenantService.save_notification_email(recipient_email, tenant_id=tenant_id)
    
    return jsonify({"success": True, "message": "Email saved successfully"})