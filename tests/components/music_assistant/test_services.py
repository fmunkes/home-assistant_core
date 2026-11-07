"""Test Music Assistant actions."""

from unittest.mock import AsyncMock, MagicMock, call

from music_assistant_client.exceptions import InvalidServerVersion
from music_assistant_client.helpers import LinkedUser
from music_assistant_models.auth import AuthProviderType
from music_assistant_models.enums import MediaType
from music_assistant_models.errors import MediaNotFoundError, UserNotFoundError
from music_assistant_models.media_items import (
    Audiobook,
    MediaCollection,
    Playlist,
    SearchResults,
    Track,
)
import pytest
from pytest_homeassistant.common import MockConfigEntry, MockUser
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.music_assistant.const import (
    ATTR_FAVORITE,
    ATTR_LIMIT,
    ATTR_MEDIA_ID,
    ATTR_MEDIA_TYPE,
    ATTR_OFFSET,
    ATTR_SEARCH_NAME,
    ATTR_USERNAME,
    DOMAIN,
)
from homeassistant.components.music_assistant.services import (
    SERVICE_GET_ITEM_CONTENTS,
    SERVICE_GET_LIBRARY,
    SERVICE_SEARCH,
)
from homeassistant.const import ATTR_CONFIG_ENTRY_ID
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .common import create_library_albums_from_fixture, setup_integration_from_fixtures

MOCK_USER_ID = "abc123"


async def test_search_action(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
    snapshot: SnapshotAssertion,
) -> None:
    """Test music assistant search action."""
    entry = await setup_integration_from_fixtures(hass, music_assistant_client)

    music_assistant_client.music.search = AsyncMock(
        return_value=SearchResults(
            albums=create_library_albums_from_fixture(),
        )
    )
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_SEARCH,
        {
            ATTR_CONFIG_ENTRY_ID: entry.entry_id,
            ATTR_SEARCH_NAME: "test",
        },
        blocking=True,
        return_response=True,
    )
    assert response == snapshot


async def test_search_action_with_username(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """Test music assistant search action."""
    entry = await setup_integration_from_fixtures(hass, music_assistant_client)

    # tests for servers supporting the username
    music_assistant_client.server_info.schema_version = 35
    music_assistant_client.music.client.send_command = AsyncMock(
        return_value={"albums": []}
    )

    # valid user ok and forwarded
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEARCH,
        {
            ATTR_CONFIG_ENTRY_ID: entry.entry_id,
            ATTR_SEARCH_NAME: "test",
            ATTR_USERNAME: "user_user",
        },
        blocking=True,
        return_response=True,
    )
    assert music_assistant_client.send_command.call_count == 1
    assert music_assistant_client.send_command.call_args == call(
        "music/search",
        search_query="test",
        media_types=MediaType.ALL,
        limit=5,
        library_only=False,
        user="user_user",
        providers=None,
        require_schema=None,
    )


@pytest.mark.parametrize(
    ("user_id", "extra_data", "expected_user"),
    [
        pytest.param(
            MOCK_USER_ID,
            {},
            LinkedUser(
                provider=AuthProviderType.HOME_ASSISTANT,
                user_id=MOCK_USER_ID,
                required=False,
            ),
            id="calling user",
        ),
        pytest.param(None, {}, None, id="no calling user"),
        pytest.param(
            MOCK_USER_ID,
            {ATTR_USERNAME: "user_user"},
            "user_user",
            id="explicit username wins",
        ),
    ],
)
async def test_search_action_acts_as_calling_user(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
    user_id: str | None,
    extra_data: dict[str, str],
    expected_user: LinkedUser | str | None,
) -> None:
    """Test that the search action defaults to the user that called it."""
    entry = await setup_integration_from_fixtures(hass, music_assistant_client)
    music_assistant_client.music.search = AsyncMock(return_value=SearchResults())

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEARCH,
        {
            ATTR_CONFIG_ENTRY_ID: entry.entry_id,
            ATTR_SEARCH_NAME: "test",
            **extra_data,
        },
        blocking=True,
        return_response=True,
        context=Context(user_id=user_id),
    )

    assert music_assistant_client.music.search.call_args.kwargs["user"] == expected_user


async def test_search_action_with_unknown_username(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """Test that a username the server does not know raises a translated error."""
    entry = await setup_integration_from_fixtures(hass, music_assistant_client)
    music_assistant_client.music.search = AsyncMock(
        side_effect=UserNotFoundError(
            "A user with user id or name nobody is not available."
        )
    )

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SEARCH,
            {
                ATTR_CONFIG_ENTRY_ID: entry.entry_id,
                ATTR_SEARCH_NAME: "test",
                ATTR_USERNAME: "nobody",
            },
            blocking=True,
            return_response=True,
        )
    assert err.value.translation_key == "invalid_username"
    assert err.value.translation_placeholders == {"username": "nobody"}


@pytest.mark.parametrize(
    ("other_entry_domain", "config_entry_id", "translation_key"),
    [
        pytest.param(
            "other", "nonexistent", "service_config_entry_not_found", id="not_found"
        ),
        pytest.param(
            "other",
            "other_entry",
            "service_config_entry_wrong_domain",
            id="wrong_domain",
        ),
        pytest.param(
            DOMAIN,
            "other_entry",
            "service_config_entry_not_loaded",
            id="not_loaded",
        ),
    ],
)
async def test_search_action_invalid_config_entry(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
    other_entry_domain: str,
    config_entry_id: str,
    translation_key: str,
) -> None:
    """Test the search action with a config entry that can't be used."""
    await setup_integration_from_fixtures(hass, music_assistant_client)
    # Added but not set up
    MockConfigEntry(domain=other_entry_domain, entry_id="other_entry").add_to_hass(hass)

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SEARCH,
            {
                ATTR_CONFIG_ENTRY_ID: config_entry_id,
                ATTR_SEARCH_NAME: "test",
            },
            blocking=True,
            return_response=True,
        )
    assert err.value.translation_key == translation_key


@pytest.mark.parametrize(
    "media_type",
    [
        "artist",
        "album",
        "track",
        "playlist",
        "audiobook",
        "podcast",
        "radio",
    ],
)
async def test_get_library_action(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
    media_type: str,
    snapshot: SnapshotAssertion,
) -> None:
    """Test music assistant get_library action."""
    entry = await setup_integration_from_fixtures(hass, music_assistant_client)
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_LIBRARY,
        {
            ATTR_CONFIG_ENTRY_ID: entry.entry_id,
            ATTR_MEDIA_TYPE: media_type,
        },
        blocking=True,
        return_response=True,
    )
    assert response == snapshot


@pytest.mark.parametrize(
    ("favorite", "expected"),
    [(True, True), (False, False), (None, None)],
)
async def test_get_library_action_favorite_filter(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
    favorite: bool | None,
    expected: bool | None,
) -> None:
    """Test the favorite filter is forwarded as given: a like, a dislike or absent."""
    entry = await setup_integration_from_fixtures(hass, music_assistant_client)
    data = {ATTR_CONFIG_ENTRY_ID: entry.entry_id, ATTR_MEDIA_TYPE: "album"}
    if favorite is not None:
        data[ATTR_FAVORITE] = favorite

    await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_LIBRARY,
        data,
        blocking=True,
        return_response=True,
    )

    assert (
        music_assistant_client.music.get_library_albums.call_args.kwargs["favorite"]
        is expected
    )


@pytest.mark.parametrize(
    "media_type",
    [
        "artist",
        "album",
        "track",
        "playlist",
        "audiobook",
        "podcast",
        "radio",
    ],
)
async def test_get_library_action_with_username(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
    media_type: str,
) -> None:
    """Test music assistant get_library action with username."""
    entry = await setup_integration_from_fixtures(hass, music_assistant_client)
    # username supported from schema 35 and above
    music_assistant_client.server_info.schema_version = 35

    # an explicit username is forwarded to the server (which validates it)
    await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_LIBRARY,
        {
            ATTR_CONFIG_ENTRY_ID: entry.entry_id,
            ATTR_MEDIA_TYPE: media_type,
            ATTR_USERNAME: "user_user",
        },
        blocking=True,
        return_response=True,
    )


async def test_get_library_action_with_unknown_username(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """Test that a username the server does not know raises a translated error."""
    entry = await setup_integration_from_fixtures(hass, music_assistant_client)
    music_assistant_client.music.get_library_tracks = AsyncMock(
        side_effect=UserNotFoundError(
            "A user with user id or name nobody is not available."
        )
    )

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_LIBRARY,
            {
                ATTR_CONFIG_ENTRY_ID: entry.entry_id,
                ATTR_MEDIA_TYPE: "track",
                ATTR_USERNAME: "nobody",
            },
            blocking=True,
            return_response=True,
        )
    assert err.value.translation_key == "invalid_username"
    assert err.value.translation_placeholders == {"username": "nobody"}


async def test_get_item_contents_action(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
    snapshot: SnapshotAssertion,
) -> None:
    """Test get_item_contents lists a playlist with positions as the calling user."""
    music_assistant_client.server_info.schema_version = 101
    entry = await setup_integration_from_fixtures(hass, music_assistant_client)
    music = music_assistant_client.music
    music.get_item_by_uri = AsyncMock(
        return_value=Playlist(
            item_id="12", provider="library", name="Party mix", provider_mappings=set()
        )
    )
    music.get_playlist_tracks = AsyncMock(
        return_value=[
            Track(
                item_id="track_1",
                provider="library",
                name="Track 1",
                provider_mappings=set(),
                position=3,
            )
        ]
    )
    user = MockUser(is_owner=True).add_to_hass(hass)
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_ITEM_CONTENTS,
        {
            ATTR_CONFIG_ENTRY_ID: entry.entry_id,
            ATTR_MEDIA_ID: "library://playlist/12",
            ATTR_LIMIT: 10,
            ATTR_OFFSET: 20,
        },
        blocking=True,
        return_response=True,
        context=Context(user_id=user.id),
    )
    calling_user = {"provider": "homeassistant", "user_id": user.id, "required": False}
    assert music.get_playlist_tracks.call_args == call(
        "12", "library", limit=10, offset=20, user=calling_user
    )
    # the position is what remove actions need to address a playlist item
    assert response["items"][0]["position"] == 3
    assert response == snapshot


async def test_get_item_contents_action_collection(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """Test get_item_contents lists a collection through its items' media type."""
    entry = await setup_integration_from_fixtures(hass, music_assistant_client)
    music = music_assistant_client.music
    collection_id = "audiobook___Book series"
    music.get_audiobook_collection = AsyncMock(
        return_value=MediaCollection[Audiobook](
            item_id=collection_id,
            provider="library",
            name="Book series",
            provider_mappings=set(),
            items=[
                Audiobook(
                    item_id="book_1",
                    provider="library",
                    name="Book 1",
                    provider_mappings=set(),
                )
            ],
        )
    )
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_ITEM_CONTENTS,
        {
            ATTR_CONFIG_ENTRY_ID: entry.entry_id,
            ATTR_MEDIA_ID: f"library://collection/{collection_id}",
        },
        blocking=True,
        return_response=True,
    )
    assert music.get_audiobook_collection.call_args == call(
        collection_id, limit=25, offset=0, user=None
    )
    # the collection item would carry all of its items, so it isn't fetched
    music.get_item_by_uri.assert_not_called()
    assert [item["name"] for item in response["items"]] == ["Book 1"]


@pytest.mark.parametrize(
    ("item", "contents_error", "expected_error"),
    [
        pytest.param(
            Track(
                item_id="track_1",
                provider="library",
                name="Track 1",
                provider_mappings=set(),
            ),
            None,
            "item_has_no_contents",
            id="track",
        ),
        pytest.param(
            Playlist(
                item_id="12",
                provider="library",
                name="Party mix",
                provider_mappings=set(),
            ),
            InvalidServerVersion("Paging needs schema 93"),
            "server_too_old",
            id="older_server",
        ),
        pytest.param(
            MediaCollection[Track](
                item_id="unknown___Mix",
                provider="library",
                name="Mix",
                provider_mappings=set(),
            ),
            None,
            "item_has_no_contents",
            id="unknown_collection",
        ),
    ],
)
async def test_get_item_contents_action_errors(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
    item: Track | Playlist | MediaCollection[Track],
    contents_error: Exception | None,
    expected_error: str,
) -> None:
    """Test get_item_contents refuses items without contents and too old servers."""
    entry = await setup_integration_from_fixtures(hass, music_assistant_client)
    music_assistant_client.music.get_item_by_uri = AsyncMock(return_value=item)
    music_assistant_client.music.get_playlist_tracks = AsyncMock(
        side_effect=contents_error
    )
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_ITEM_CONTENTS,
            {ATTR_CONFIG_ENTRY_ID: entry.entry_id, ATTR_MEDIA_ID: item.uri},
            blocking=True,
            return_response=True,
        )
    assert err.value.translation_key == expected_error


async def test_get_item_contents_action_older_server_error(
    hass: HomeAssistant,
    music_assistant_client: MagicMock,
) -> None:
    """Test get_item_contents sends no user to an older server and converts errors."""
    music_assistant_client.server_info.schema_version = 100
    entry = await setup_integration_from_fixtures(hass, music_assistant_client)
    music_assistant_client.music.get_item_by_uri = AsyncMock(
        side_effect=MediaNotFoundError("Album 999 not found")
    )
    with pytest.raises(HomeAssistantError, match="Album 999 not found"):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_ITEM_CONTENTS,
            {
                ATTR_CONFIG_ENTRY_ID: entry.entry_id,
                ATTR_MEDIA_ID: "library://album/999",
            },
            blocking=True,
            return_response=True,
        )
    assert music_assistant_client.music.get_item_by_uri.call_args == call(
        "library://album/999", user=None
    )
