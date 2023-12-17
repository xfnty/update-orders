import logging
import os
import time
import json
import getpass
from typing import List, Dict
from dateutil import parser as datetime_parser
import datetime
import dataclasses
from requests_ratelimiter import LimiterSession
from dataclass_wizard import JSONWizard as JSONSerializable


MARKET_API_BASE = "https://api.warframe.market/v1"
CREDS_FILE = os.path.join(os.getcwd(), "cached_credentials.json")
session = LimiterSession(per_second=1)


@dataclasses.dataclass
class Credentials(JSONSerializable):
    nickname: str
    auth_token: str

    def __post_init__(self):
        self.request_headers = {
            "Content-Type": "application/json; utf-8",
            "Accept": "application/json",
            "auth_type": "header",
            "platform": "pc",
            "language": "en",
            "Authorization" : self.auth_token
        }


@dataclasses.dataclass
class Item:
    id: str
    name: str
    url_name: str

    def __str__(self) -> str:
        return f"Item(\"{self.name}\")"


@dataclasses.dataclass
class Order:
    id: str
    type: str
    item: Item
    quantity: int
    price: int
    creator: str
    last_update: datetime.datetime

    def __str__(self) -> str:
        return f"Order({self.type}, \"{self.item.name}\", {self.price})"


def get_creds() -> Credentials:
    if os.path.exists(CREDS_FILE):
        try:
            user = Credentials.from_json(open(CREDS_FILE, "r").read())
            assert isinstance(user, Credentials)
            print(f"Loaded credentials from \"{os.path.basename(CREDS_FILE)}\" for user \"{user.nickname}\"")
            return user
        except Exception:
            pass

    print("Please enter authentication credentials for Warframe Market")
    email = input("Email: ")
    passw = getpass.getpass("Password: ")

    headers = {
        "Content-Type": "application/json; utf-8",
        "Accept": "application/json",
        "Authorization": "JWT",
        "platform": "pc",
        "language": "en",
    }
    content = {
        "email": email,
        "password": passw,
        "auth_type": "header",
    }

    print(f"Authenticating \"{email}\" ...")

    response = session.post(MARKET_API_BASE + "/auth/signin", data=json.dumps(content), headers=headers)
    response.raise_for_status()

    creds = Credentials(response.json()["payload"]["user"]["ingame_name"], response.headers["Authorization"])
    open(CREDS_FILE, "w").write(json.dumps(dataclasses.asdict(creds), sort_keys=True, indent=4))

    print(f"Authenticated as \"{creds.nickname}\"")

    return creds


def get_items(creds: Credentials) -> Dict[str, Item]:
    r = session.get(MARKET_API_BASE + "/items", headers=creds.request_headers)
    r.raise_for_status()

    return {i["item_name"]: Item(i["id"], i["item_name"], i["url_name"]) for i in r.json()["payload"]["items"]}


def get_my_orders(creds: Credentials) -> List[Order]:
    r = session.get(MARKET_API_BASE + f"/profile/{creds.nickname}/orders", headers=creds.request_headers)
    r.raise_for_status()

    def order_from_dict(d: dict) -> Order:
        return Order(d["id"], d["order_type"], Item(d["item"]["id"], d["item"]["en"]["item_name"], d["item"]["url_name"]), d["quantity"], d["platinum"], creds.nickname, datetime_parser.parse(d["last_update"]))

    payload = r.json()["payload"]
    return [order_from_dict(o) for o in (payload["sell_orders"] + payload["buy_orders"]) if o["visible"]]


def get_orders_for_item(creds: Credentials, item: Item) -> Dict[str, List[Order]]:
    r = session.get(MARKET_API_BASE + f"/items/{item.url_name}/orders", headers=creds.request_headers)
    r.raise_for_status()

    def order_from_dict(d: dict) -> Order:
        return Order(d["id"], d["order_type"], item, d["quantity"], d["platinum"], d["user"]["ingame_name"], datetime_parser.parse(d["last_update"]))

    orders = list(filter(lambda o: o["platform"] == "pc" and o["user"]["status"] == "ingame", r.json()["payload"]["orders"]))
    orders = {
        "buy": sorted((order_from_dict(e) for e in orders if e["order_type"] == "buy"), key=lambda o: (-o.price, -o.last_update.timestamp())),
        "sell": sorted((order_from_dict(e) for e in orders if e["order_type"] == "sell"), key=lambda o: (o.price, -o.last_update.timestamp()))
    }
    return orders


def update_my_order(creds: Credentials, order: Order):
    contents = {
        "platinum": order.price,
        "quantity": order.quantity,
        "visible": True
    }
    r = session.put(MARKET_API_BASE + f"/profile/orders/{order.id}", json=contents, headers=creds.request_headers)
    r.raise_for_status()


def main():
    creds = get_creds()
    
    while True:
        my_orders = get_my_orders(creds)
        for order in my_orders:
            print(f"Updating {order}, last updated at {order.last_update.strftime("%H:%M:%S")}")
            try:
                update_my_order(creds, order)
            except Exception:
                pass
            time.sleep(5)
        print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
