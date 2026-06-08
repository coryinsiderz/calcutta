from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def _get_increment(price: int, bands: list[dict]) -> int:
    inc = 1
    for band in sorted(bands, key=lambda b: b["min_price"]):
        if price >= band["min_price"]:
            inc = band["increment"]
    return inc


def get_next_bid_amounts(current_bid: int, bands: list[dict], count: int = 4) -> list[int]:
    """Return `count` suggested next bid amounts at increasing step sizes."""
    # Generate enough increments to build spread-out suggestions
    skips = {1, 3, 7, 12}  # take at these step-offsets
    amounts = []
    price = current_bid
    for step in range(1, max(skips) + 1):
        price += _get_increment(price, bands)
        if step in skips:
            amounts.append(price)
    return amounts[:count]


def build_bid_keyboard(current_bid: int, team_id: int, bands: list[dict]) -> InlineKeyboardMarkup:
    next_bids = get_next_bid_amounts(current_bid, bands)
    row1 = [
        InlineKeyboardButton(f"${amt:,}", callback_data=f"bid:{team_id}:{amt}")
        for amt in next_bids[:2]
    ]
    row2 = [
        InlineKeyboardButton(f"${amt:,}", callback_data=f"bid:{team_id}:{amt}")
        for amt in next_bids[2:]
    ]
    buttons = [r for r in [row1, row2] if r]
    return InlineKeyboardMarkup(buttons)
