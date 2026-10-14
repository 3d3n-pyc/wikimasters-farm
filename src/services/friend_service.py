import logging
from typing import Optional, Tuple
from src.api.client import WikiMastersClient

logger = logging.getLogger(__name__)


class FriendService:
    def resolve_target_info(
        self, client: WikiMastersClient, target_username: str
    ) -> Tuple[Optional[str], Optional[str]]:
        friends_data = client.get_friends()
        for f in friends_data.get("friendships", []):
            req = f.get("requester") or {}
            add = f.get("addressee") or {}
            if req.get("username", "").lower() == target_username.lower():
                return req.get("id"), req.get("username")
            if add.get("username", "").lower() == target_username.lower():
                return add.get("id"), add.get("username")

        users = client.search_friends(target_username)
        for u in users:
            if u.get("username", "").lower() == target_username.lower():
                return u.get("id"), u.get("username")

        return None, None

    def ensure_friendship(
        self,
        farm_client: WikiMastersClient,
        target_username: str,
        target_id: Optional[str] = None,
    ) -> bool:
        friends_data = farm_client.get_friends()
        my_id = friends_data.get("user_id")
        if my_id:
            farm_client.account.user_id = my_id

        for f in friends_data.get("friendships", []):
            req = f.get("requester") or {}
            add = f.get("addressee") or {}
            if (
                req.get("username", "").lower() == target_username.lower()
                or add.get("username", "").lower() == target_username.lower()
                or (target_id and (req.get("id") == target_id or add.get("id") == target_id))
            ):
                return True

        if not target_id:
            target_id, _ = self.resolve_target_info(farm_client, target_username)

        if target_id:
            logger.info(f"{farm_client.account.prefix} Sending friend request to {target_username} ({target_id})...")
            return farm_client.send_friend_request(target_id)
        else:
            logger.warning(f"{farm_client.account.prefix} Could not resolve target user ID for {target_username}.")
            return False

    def accept_all_on_target(self, target_client: WikiMastersClient) -> bool:
        logger.info(f"{target_client.account.prefix} Accepting all pending friend requests...")
        return target_client.accept_all_friends()
