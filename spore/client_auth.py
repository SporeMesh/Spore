from __future__ import annotations

from eth_account import Account
from eth_account.messages import encode_defunct

from .client_api import BackendClient
from .client_store import update_config


def login_with_private_key(private_key: str, base_url: str | None = None) -> dict[str, str]:
    normalized = private_key if private_key.startswith("0x") else f"0x{private_key}"
    account = Account.from_key(normalized)
    client = BackendClient(base_url=base_url, api_key="")
    challenge = client.post(
        "/api/v1/auth/wallet/challenge",
        json_body={"wallet_address": account.address},
    )
    message = encode_defunct(text=challenge["message"])
    signature = Account.sign_message(message, private_key=private_key).signature.hex()
    verified = client.post(
        "/api/v1/auth/wallet/verify",
        json_body={
            "wallet_address": account.address,
            "challenge_token": challenge["challenge_token"],
            "signature": signature,
        },
    )
    update_config(
        base_url=client.base_url,
        api_key=verified["api_key"],
        operator_id=verified["operator_id"],
        wallet_address=account.address,
        private_key=normalized,
    )
    return {
        "wallet_address": account.address,
        "operator_id": verified["operator_id"],
        "api_key": verified["api_key"],
    }
