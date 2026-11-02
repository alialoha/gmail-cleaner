"""OAuth helpers — tokens live under ~/.gmail-cleaner/tokens/."""

from __future__ import annotations

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build

from gmail_cleaner.accounts.registry import Account
from gmail_cleaner.paths import write_secret_file

SCOPES = {
    "modify": ["https://www.googleapis.com/auth/gmail.modify"],
    # Required for users.messages.batchDelete (permanent). Prefer trash when possible.
    "full": ["https://mail.google.com/"],
}


def get_credentials(account: Account, *, force_consent: bool = False) -> Credentials:
    scopes = SCOPES[account.scope]
    creds: Credentials | None = None

    if account.token_file.exists() and not force_consent:
        creds = Credentials.from_authorized_user_file(str(account.token_file), scopes)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not account.credentials_file.exists():
            raise FileNotFoundError(
                f"OAuth client file not found: {account.credentials_file}\n"
                "Download a Desktop client JSON from Google Cloud Console and place it there."
            )
        flow = InstalledAppFlow.from_client_secrets_file(
            str(account.credentials_file),
            scopes,
        )
        creds = flow.run_local_server(port=0)

    write_secret_file(account.token_file, creds.to_json())
    return creds


def get_gmail_service(account: Account, *, force_consent: bool = False) -> Resource:
    creds = get_credentials(account, force_consent=force_consent)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def verify_account_email(account: Account, service: Resource | None = None) -> str:
    """Return the authenticated profile email; raise if it mismatches the registry."""
    svc = service or get_gmail_service(account)
    profile = svc.users().getProfile(userId="me").execute()
    actual = str(profile.get("emailAddress", "")).lower()
    expected = account.email.lower()
    if actual and expected and actual != expected:
        raise ValueError(
            f"Authenticated mailbox is {actual}, but account '{account.id}' "
            f"is registered as {account.email}. Fix the registry or re-auth."
        )
    return actual or account.email
