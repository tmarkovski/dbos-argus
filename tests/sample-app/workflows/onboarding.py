"""User signup & onboarding.

`onboard_user` runs on the `onboarding` queue. Demonstrates:
- recv with timeout for "user clicks the email-verify link"
- set_event broadcasting provisioning state
- sub-workflow (`provision_account`)
- branch on timeout (cleanup_unverified vs welcome)
"""

from __future__ import annotations

from dbos import DBOS

from .common import _pause, audit, log_event, maybe_fail

VERIFY_EMAIL_TOPIC = "email-verify"
VERIFY_EMAIL_TIMEOUT_SEC = 90


@DBOS.step()
def create_account(email: str) -> dict:
    _pause()
    user_id = f"u-{abs(hash(email)) % 10_000_000:07d}"
    return {"user_id": user_id, "email": email}


@DBOS.step()
def send_verification_email(email: str) -> str:
    _pause()
    return f"verify-{abs(hash(email)) % 10_000_000:07d}"


@DBOS.step()
def provision_storage(user_id: str) -> dict:
    _pause(2, 5)
    return {"user_id": user_id, "bucket": f"u-{user_id}-files", "quota_gb": 5}


@DBOS.step()
def provision_api_key(user_id: str) -> str:
    _pause()
    return f"sk_demo_{user_id}_{abs(hash(user_id)) % 1_000_000:06d}"


@DBOS.step()
def send_welcome_email(email: str) -> None:
    _pause()


@DBOS.step()
def cleanup_unverified(user_id: str) -> dict:
    _pause()
    return {"user_id": user_id, "deleted": True}


@DBOS.workflow()
def provision_account(user_id: str) -> dict:
    audit(f"provision-start:{user_id}")
    storage = provision_storage(user_id)
    api_key = provision_api_key(user_id)
    DBOS.set_event("provisioning", {"user_id": user_id, "stage": "complete"})
    log_event(f"provisioned:{user_id}")
    maybe_fail(f"provision-{user_id}")
    return {"user_id": user_id, **storage, "api_key": api_key}


@DBOS.workflow()
def onboard_user(email: str) -> dict:
    audit(f"signup:{email}")
    account = create_account(email)
    user_id = account["user_id"]
    DBOS.set_event("status", {"stage": "verify-pending"})
    send_verification_email(email)

    click = DBOS.recv(topic=VERIFY_EMAIL_TOPIC, timeout_seconds=VERIFY_EMAIL_TIMEOUT_SEC)
    if click is None:
        log_event(f"verify-timeout:{user_id}")
        cleanup_unverified(user_id)
        DBOS.set_event("status", {"stage": "abandoned"})
        return {"user_id": user_id, "verified": False}

    DBOS.set_event("status", {"stage": "provisioning"})
    provisioned = provision_account(user_id)
    send_welcome_email(email)
    DBOS.set_event("status", {"stage": "active"})
    return {"user_id": user_id, "verified": True, **provisioned}
