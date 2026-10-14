from dataclasses import dataclass
from typing import Optional, Dict, Any
from src.config import RARITY_RANKS


@dataclass
class Card:
    id: str
    wikipedia_title: str
    rarity: str = "C"
    atk: int = 0
    def_val: int = 0
    image_url: Optional[str] = None
    category: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Card":
        return cls(
            id=data.get("id", ""),
            wikipedia_title=data.get("wikipedia_title") or data.get("name") or "Inconnu",
            rarity=(data.get("rarity") or "C").upper(),
            atk=data.get("atk", 0) or 0,
            def_val=data.get("def", 0) or 0,
            image_url=data.get("image_url"),
            category=data.get("category"),
        )

    @property
    def rarity_rank(self) -> int:
        return RARITY_RANKS.get(self.rarity, 0)


@dataclass
class UserCard:
    id: str
    card_id: str
    user_id: Optional[str] = None
    card: Optional[Card] = None
    starred: bool = False
    is_shiny: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserCard":
        card_obj = None
        if "card" in data and isinstance(data["card"], dict):
            card_obj = Card.from_dict(data["card"])

        return cls(
            id=data.get("id", ""),
            card_id=data.get("card_id") or (card_obj.id if card_obj else ""),
            user_id=data.get("user_id"),
            card=card_obj,
            starred=bool(data.get("starred", False)),
            is_shiny=bool(data.get("is_shiny", False)),
        )

    @property
    def rarity(self) -> str:
        if self.card and self.card.rarity:
            return self.card.rarity.upper()
        return "C"

    @property
    def rarity_rank(self) -> int:
        return RARITY_RANKS.get(self.rarity, 0)

    @property
    def title(self) -> str:
        if self.card and self.card.wikipedia_title:
            return self.card.wikipedia_title
        return "Inconnu"
