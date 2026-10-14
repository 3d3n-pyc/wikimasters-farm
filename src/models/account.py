from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class Account:
    email: str
    password: str
    is_target: bool = False
    user_id: Optional[str] = None
    username: Optional[str] = None
    wikibidous_balance: int = 0
    packs_remaining: int = 0
    total_cards: int = 0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Account":
        return cls(
            email=data["email"],
            password=data["password"],
            is_target=bool(data.get("is_target", False)),
            user_id=data.get("user_id"),
            username=data.get("username"),
            wikibidous_balance=data.get("wikibidous_balance", 0),
            packs_remaining=data.get("packs_remaining", 0),
            total_cards=data.get("total_cards", 0),
        )

    @property
    def display_name(self) -> str:
        if self.username:
            return self.username
        return self.email.split("@")[0]

    @property
    def prefix(self) -> str:
        role = "[Target]" if self.is_target else "[Bot]"
        return f"{role} [{self.display_name}]"
