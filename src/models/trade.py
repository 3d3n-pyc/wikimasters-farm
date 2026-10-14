from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from src.models.card import Card


@dataclass
class TradeItem:
    user_card_id: str
    card_id: str
    offered_by: str
    card: Optional[Card] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TradeItem":
        card_obj = None
        if "card" in data and isinstance(data["card"], dict):
            card_obj = Card.from_dict(data["card"])

        return cls(
            user_card_id=data.get("user_card_id", ""),
            card_id=data.get("card_id", ""),
            offered_by=data.get("offered_by", ""),
            card=card_obj,
        )

    def to_dict(self) -> Dict[str, str]:
        return {
            "user_card_id": self.user_card_id,
            "card_id": self.card_id,
            "offered_by": self.offered_by,
        }


@dataclass
class Trade:
    id: str
    initiator_id: str
    recipient_id: str
    status: str
    initiator_wikibidous: int = 0
    recipient_wikibidous: int = 0
    items: List[TradeItem] = field(default_factory=list)
    initiator_username: Optional[str] = None
    recipient_username: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Trade":
        items = [
            TradeItem.from_dict(item)
            for item in data.get("items", [])
            if isinstance(item, dict)
        ]
        initiator = data.get("initiator") or {}
        recipient = data.get("recipient") or {}

        return cls(
            id=data.get("id", ""),
            initiator_id=data.get("initiator_id") or initiator.get("id", ""),
            recipient_id=data.get("recipient_id") or recipient.get("id", ""),
            status=data.get("status", "pending"),
            initiator_wikibidous=data.get("initiator_wikibidous", 0) or 0,
            recipient_wikibidous=data.get("recipient_wikibidous", 0) or 0,
            items=items,
            initiator_username=initiator.get("username"),
            recipient_username=recipient.get("username"),
        )


@dataclass
class TradeResult:
    trades_sent: int = 0
    cards_sent: int = 0
    wb_sent: int = 0
    status: str = "ok"
    error_message: Optional[str] = None
