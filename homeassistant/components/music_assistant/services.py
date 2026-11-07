"""Custom actions (previously known as services) for the Music Assistant integration."""

from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any

from music_assistant_client.exceptions import InvalidServerVersion
from music_assistant_models.enums import MediaType, QueueOption
import probatio

from homeassistant.components.media_player import (
    ATTR_MEDIA_ENQUEUE,
    DOMAIN as MEDIA_PLAYER_DOMAIN,
    MediaPlayerDeviceClass,
)
from homeassistant.components.tts import DOMAIN as TTS_DOMAIN
from homeassistant.const import ATTR_CONFIG_ENTRY_ID
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, service

from .const import (
    ATTR_ALBUM,
    ATTR_ALBUM_ARTISTS_ONLY,
    ATTR_ALBUM_TYPE,
    ATTR_ALBUMS,
    ATTR_ANNOUNCE_VOLUME,
    ATTR_ARTIST,
    ATTR_ARTISTS,
    ATTR_AUDIOBOOKS,
    ATTR_AUTO_PLAY,
    ATTR_FAVORITE,
    ATTR_ITEMS,
    ATTR_LIBRARY_ONLY,
    ATTR_LIMIT,
    ATTR_MEDIA_ID,
    ATTR_MEDIA_TYPE,
    ATTR_MESSAGE,
    ATTR_OFFSET,
    ATTR_ORDER_BY,
    ATTR_PLAYLISTS,
    ATTR_PODCASTS,
    ATTR_POSITION,
    ATTR_PRE_ANNOUNCE_URL,
    ATTR_RADIO,
    ATTR_RADIO_MODE,
    ATTR_SEARCH,
    ATTR_SEARCH_ALBUM,
    ATTR_SEARCH_ARTIST,
    ATTR_SEARCH_NAME,
    ATTR_SOURCE_PLAYER,
    ATTR_START_ITEM,
    ATTR_TRACKS,
    ATTR_TTS_ENTITY_ID,
    ATTR_URL,
    ATTR_USE_PRE_ANNOUNCE,
    ATTR_USERNAME,
    COLLECTION_ITEM_ID_SEPARATOR,
    DOMAIN,
)
from .helpers import (
    acting_user,
    catch_user_not_found,
    get_music_assistant_client,
    user_from_context,
)
from .schemas import (
    ITEM_CONTENTS_SCHEMA,
    LIBRARY_RESULTS_SCHEMA,
    SEARCH_RESULT_SCHEMA,
    media_item_dict_from_mass_item,
)

if TYPE_CHECKING:
    from music_assistant_models.media_items import (
        Album,
        Artist,
        Audiobook,
        MediaCollection,
        MediaItemType,
        Playlist,
        Podcast,
        Radio,
        Track,
    )

SERVICE_SEARCH = "search"
SERVICE_GET_LIBRARY = "get_library"
SERVICE_PLAY_MEDIA_ADVANCED = "play_media"
SERVICE_PLAY_ANNOUNCEMENT = "play_announcement"
SERVICE_TRANSFER_QUEUE = "transfer_queue"
SERVICE_GET_QUEUE = "get_queue"
SERVICE_GET_ITEM_CONTENTS = "get_item_contents"

DEFAULT_OFFSET = 0
DEFAULT_LIMIT = 25
DEFAULT_SORT_ORDER = "name"

# player-only entity services; dashboard display entities don't implement them
PLAYER_ENTITY_DEVICE_CLASSES = [MediaPlayerDeviceClass.SPEAKER]


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register custom actions."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEARCH,
        handle_search,
        schema=probatio.Schema(
            {
                probatio.Required(ATTR_CONFIG_ENTRY_ID): str,
                probatio.Required(ATTR_SEARCH_NAME): cv.string,
                probatio.Optional(ATTR_MEDIA_TYPE): probatio.All(
                    probatio.EnsureList(), [probatio.Coerce(MediaType)]
                ),
                probatio.Optional(ATTR_SEARCH_ARTIST): cv.string,
                probatio.Optional(ATTR_SEARCH_ALBUM): cv.string,
                probatio.Optional(ATTR_LIMIT, default=5): probatio.Coerce(int),
                probatio.Optional(ATTR_LIBRARY_ONLY, default=False): cv.boolean,
                probatio.Optional(ATTR_USERNAME): cv.string,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_LIBRARY,
        handle_get_library,
        schema=probatio.Schema(
            {
                probatio.Required(ATTR_CONFIG_ENTRY_ID): str,
                probatio.Required(ATTR_MEDIA_TYPE): probatio.Coerce(MediaType),
                probatio.Optional(ATTR_FAVORITE): cv.boolean,
                probatio.Optional(ATTR_SEARCH): cv.string,
                probatio.Optional(ATTR_LIMIT): cv.positive_int,
                probatio.Optional(ATTR_OFFSET): int,
                probatio.Optional(ATTR_ORDER_BY): cv.string,
                probatio.Optional(ATTR_ALBUM_TYPE): list[MediaType],
                probatio.Optional(ATTR_ALBUM_ARTISTS_ONLY): cv.boolean,
                probatio.Optional(ATTR_USERNAME): cv.string,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_ITEM_CONTENTS,
        handle_get_item_contents,
        schema=probatio.Schema(
            {
                probatio.Required(ATTR_CONFIG_ENTRY_ID): str,
                probatio.Required(ATTR_MEDIA_ID): cv.string,
                probatio.Optional(
                    ATTR_MEDIA_TYPE, default=MediaType.ALBUM
                ): probatio.All(
                    probatio.Coerce(MediaType),
                    probatio.In([MediaType.ALBUM, MediaType.TRACK]),
                ),
                probatio.Optional(ATTR_LIMIT, default=DEFAULT_LIMIT): probatio.All(
                    cv.positive_int, probatio.Range(min=1)
                ),
                probatio.Optional(ATTR_OFFSET, default=DEFAULT_OFFSET): cv.positive_int,
                probatio.Optional(ATTR_USERNAME): cv.string,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    # Platform entity services
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_PLAY_MEDIA_ADVANCED,
        entity_domain=MEDIA_PLAYER_DOMAIN,
        entity_device_classes=PLAYER_ENTITY_DEVICE_CLASSES,
        schema={
            probatio.Required(ATTR_MEDIA_ID): probatio.All(
                probatio.EnsureList(), [cv.string]
            ),
            probatio.Optional(ATTR_MEDIA_TYPE): probatio.Coerce(MediaType),
            probatio.Optional(ATTR_MEDIA_ENQUEUE): probatio.Coerce(QueueOption),
            probatio.Optional(ATTR_ARTIST): cv.string,
            probatio.Optional(ATTR_ALBUM): cv.string,
            probatio.Optional(ATTR_RADIO_MODE): probatio.Coerce(bool),
            probatio.Optional(ATTR_START_ITEM): cv.string,
            probatio.Optional(ATTR_USERNAME): cv.string,
        },
        func="_async_handle_play_media",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_PLAY_ANNOUNCEMENT,
        entity_domain=MEDIA_PLAYER_DOMAIN,
        entity_device_classes=PLAYER_ENTITY_DEVICE_CLASSES,
        schema=probatio.All(
            cv.make_entity_service_schema(
                {
                    probatio.Optional(ATTR_URL): cv.string,
                    probatio.Inclusive(ATTR_MESSAGE, "spoken_announcement"): cv.string,
                    probatio.Inclusive(
                        ATTR_TTS_ENTITY_ID, "spoken_announcement"
                    ): probatio.All(cv.entity_id, cv.entity_domain(TTS_DOMAIN)),
                    probatio.Optional(ATTR_USE_PRE_ANNOUNCE): probatio.Coerce(bool),
                    probatio.Optional(ATTR_PRE_ANNOUNCE_URL): cv.string,
                    probatio.Optional(ATTR_ANNOUNCE_VOLUME): probatio.Coerce(int),
                }
            ),
            probatio.AtLeastOne(ATTR_URL, ATTR_MESSAGE),
            probatio.AtMostOne(ATTR_URL, ATTR_MESSAGE),
        ),
        func="_async_handle_play_announcement",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_TRANSFER_QUEUE,
        entity_domain=MEDIA_PLAYER_DOMAIN,
        entity_device_classes=PLAYER_ENTITY_DEVICE_CLASSES,
        schema={
            probatio.Optional(ATTR_SOURCE_PLAYER): cv.entity_id,
            probatio.Optional(ATTR_AUTO_PLAY): probatio.Coerce(bool),
        },
        func="_async_handle_transfer_queue",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_GET_QUEUE,
        entity_domain=MEDIA_PLAYER_DOMAIN,
        entity_device_classes=PLAYER_ENTITY_DEVICE_CLASSES,
        schema={
            probatio.Optional(ATTR_LIMIT, default=0): cv.positive_int,
            probatio.Optional(ATTR_OFFSET, default=DEFAULT_OFFSET): cv.positive_int,
            probatio.Optional(ATTR_USERNAME): cv.string,
        },
        func="_async_handle_get_queue",
        supports_response=SupportsResponse.ONLY,
    )


async def handle_search(call: ServiceCall) -> ServiceResponse:
    """Handle queue_command action."""
    mass = get_music_assistant_client(call.hass, call.data[ATTR_CONFIG_ENTRY_ID])
    search_name = call.data[ATTR_SEARCH_NAME]
    search_artist = call.data.get(ATTR_SEARCH_ARTIST)
    search_album = call.data.get(ATTR_SEARCH_ALBUM)
    search_username = call.data.get(ATTR_USERNAME)
    if search_album and search_artist:
        search_name = f"{search_artist} - {search_album} - {search_name}"
    elif search_album:
        search_name = f"{search_album} - {search_name}"
    elif search_artist:
        search_name = f"{search_artist} - {search_name}"
    with catch_user_not_found(search_username):
        search_results = await mass.music.search(
            search_query=search_name,
            media_types=call.data.get(ATTR_MEDIA_TYPE, MediaType.ALL),
            limit=call.data[ATTR_LIMIT],
            library_only=call.data[ATTR_LIBRARY_ONLY],
            user=search_username
            if search_username is not None
            else user_from_context(call.context),
        )
    response: ServiceResponse = SEARCH_RESULT_SCHEMA(
        {
            ATTR_ARTISTS: [
                media_item_dict_from_mass_item(mass, item)
                for item in search_results.artists
            ],
            ATTR_ALBUMS: [
                media_item_dict_from_mass_item(mass, item)
                for item in search_results.albums
            ],
            ATTR_TRACKS: [
                media_item_dict_from_mass_item(mass, item)
                for item in search_results.tracks
            ],
            ATTR_PLAYLISTS: [
                media_item_dict_from_mass_item(mass, item)
                for item in search_results.playlists
            ],
            ATTR_RADIO: [
                media_item_dict_from_mass_item(mass, item)
                for item in search_results.radio
            ],
            ATTR_AUDIOBOOKS: [
                media_item_dict_from_mass_item(mass, item)
                for item in search_results.audiobooks
            ],
            ATTR_PODCASTS: [
                media_item_dict_from_mass_item(mass, item)
                for item in search_results.podcasts
            ],
        }
    )
    return response


async def handle_get_library(call: ServiceCall) -> ServiceResponse:
    """Handle get_library action."""
    mass = get_music_assistant_client(call.hass, call.data[ATTR_CONFIG_ENTRY_ID])
    media_type = call.data[ATTR_MEDIA_TYPE]
    limit = call.data.get(ATTR_LIMIT, DEFAULT_LIMIT)
    offset = call.data.get(ATTR_OFFSET, DEFAULT_OFFSET)
    order_by = call.data.get(ATTR_ORDER_BY, DEFAULT_SORT_ORDER)
    username = call.data.get(ATTR_USERNAME)
    base_params = {
        "favorite": call.data.get(ATTR_FAVORITE),
        "search": call.data.get(ATTR_SEARCH),
        "limit": limit,
        "offset": offset,
        "order_by": order_by,
        "user": username,
    }
    library_result: (
        list[Album]
        | list[Artist]
        | list[Track]
        | list[Radio]
        | list[Playlist]
        | list[Audiobook]
        | list[Podcast]
    )
    with catch_user_not_found(username):
        if media_type == MediaType.ALBUM:
            library_result = await mass.music.get_library_albums(
                **base_params,
                album_types=call.data.get(ATTR_ALBUM_TYPE),
            )
        elif media_type == MediaType.ARTIST:
            library_result = await mass.music.get_library_artists(
                **base_params,
                album_artists_only=bool(call.data.get(ATTR_ALBUM_ARTISTS_ONLY)),
            )
        elif media_type == MediaType.TRACK:
            library_result = await mass.music.get_library_tracks(
                **base_params,
            )
        elif media_type == MediaType.RADIO:
            library_result = await mass.music.get_library_radios(
                **base_params,
            )
        elif media_type == MediaType.PLAYLIST:
            library_result = await mass.music.get_library_playlists(
                **base_params,
            )
        elif media_type == MediaType.AUDIOBOOK:
            library_result = await mass.music.get_library_audiobooks(
                **base_params,
            )
        elif media_type == MediaType.PODCAST:
            library_result = await mass.music.get_library_podcasts(
                **base_params,
            )
        else:
            raise ServiceValidationError(f"Unsupported media type {media_type}")

    response: ServiceResponse = LIBRARY_RESULTS_SCHEMA(
        {
            ATTR_ITEMS: [
                media_item_dict_from_mass_item(mass, item) for item in library_result
            ],
            ATTR_LIMIT: limit,
            ATTR_OFFSET: offset,
            ATTR_ORDER_BY: order_by,
            ATTR_MEDIA_TYPE: media_type,
        }
    )
    return response


async def handle_get_item_contents(call: ServiceCall) -> ServiceResponse:
    """Handle get_item_contents action."""
    mass = get_music_assistant_client(call.hass, call.data[ATTR_CONFIG_ENTRY_ID])
    username = call.data.get(ATTR_USERNAME)
    limit = call.data[ATTR_LIMIT]
    offset = call.data[ATTR_OFFSET]
    contents: Sequence[MediaItemType]
    with catch_user_not_found(username):
        user = acting_user(mass, username, call.context)
        item = await mass.music.get_item_by_uri(call.data[ATTR_MEDIA_ID], user=user)
        try:
            if item.media_type is MediaType.ALBUM:
                contents = await mass.music.get_album_tracks(
                    item.item_id, item.provider, limit=limit, offset=offset, user=user
                )
            elif item.media_type is MediaType.PLAYLIST:
                contents = await mass.music.get_playlist_tracks(
                    item.item_id, item.provider, limit=limit, offset=offset, user=user
                )
            elif item.media_type is MediaType.ARTIST:
                get_artist_contents = (
                    mass.music.get_artist_tracks
                    if call.data[ATTR_MEDIA_TYPE] is MediaType.TRACK
                    else mass.music.get_artist_albums
                )
                contents = await get_artist_contents(
                    item.item_id, item.provider, limit=limit, offset=offset, user=user
                )
            elif item.media_type is MediaType.PODCAST:
                contents = await mass.music.get_podcast_episodes(
                    item.item_id, item.provider, limit=limit, offset=offset, user=user
                )
            elif item.media_type is MediaType.COLLECTION:
                # the collection's item id starts with the media type of its items
                items_media_type = item.item_id.split(COLLECTION_ITEM_ID_SEPARATOR)[0]
                collection_getters: dict[
                    MediaType, Callable[..., Awaitable[MediaCollection[Any]]]
                ] = {
                    MediaType.ALBUM: mass.music.get_album_collection,
                    MediaType.ARTIST: mass.music.get_artist_collection,
                    MediaType.AUDIOBOOK: mass.music.get_audiobook_collection,
                    MediaType.GENRE: mass.music.get_genre_collection,
                    MediaType.PLAYLIST: mass.music.get_playlist_collection,
                    MediaType.PODCAST: mass.music.get_podcast_collection,
                    MediaType.RADIO: mass.music.get_radio_collection,
                    MediaType.TRACK: mass.music.get_track_collection,
                }
                get_collection = collection_getters[MediaType(items_media_type)]
                collection = await get_collection(
                    item.item_id, limit=limit, offset=offset, user=user
                )
                contents = collection.items
            else:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="item_has_no_contents",
                    translation_placeholders={"media_type": item.media_type.value},
                )
        except InvalidServerVersion as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="server_too_old",
            ) from err
    response: ServiceResponse = ITEM_CONTENTS_SCHEMA(
        {
            ATTR_ITEMS: [
                {
                    **media_item_dict_from_mass_item(mass, entry),
                    ATTR_POSITION: entry.position,
                }
                for entry in contents
            ],
            ATTR_LIMIT: limit,
            ATTR_OFFSET: offset,
        }
    )
    return response
