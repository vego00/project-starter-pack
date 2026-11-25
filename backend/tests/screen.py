"""What the screen does with a response before the user sees it, for tests over the HTTP API."""


def prepared(client, response, headers=None):
    """A card shown with its options only is prepared at once, as the screen does."""
    if response.status_code not in (200, 201):
        return response
    view = response.json()
    prompt = view.get("prompt")
    if not (prompt and prompt["type"] == "decision" and prompt["card"]["preparing"]):
        return response
    return client.post(
        f"/api/v1/journeys/{view['journey_id']}/decisions",
        json={"revision": view["revision"], "action": {"action": "prepare"}},
        headers=headers,
    )
