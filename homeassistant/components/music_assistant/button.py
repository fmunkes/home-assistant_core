"""Music Assistant Button platform."""

from music_assistant_client.client import MusicAssistantClient
from music_assistant_models.enums import ProviderFeature, ProviderType
from music_assistant_models.provider import ProviderInstance

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MusicAssistantConfigEntry
from .entity import MusicAssistantPlayerEntity, MusicAssistantProviderEntity
from .helpers import catch_musicassistant_error


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MusicAssistantConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Music Assistant MediaPlayer(s) from Config Entry."""
    mass = entry.runtime_data.mass

    def add_player(player_id: str) -> None:
        """Handle add player."""
        async_add_entities(
            [
                # Add button entity to favorite the currently playing item on the player
                MusicAssistantFavoriteButton(mass, player_id)
            ]
        )

    def add_music_provider(provider_instance_id: str) -> None:
        """Handle add provider."""

        def verify_can_sync(provider: ProviderInstance) -> bool:
            return bool(
                {
                    ProviderFeature.LIBRARY_ALBUMS,
                    ProviderFeature.LIBRARY_ARTISTS,
                    ProviderFeature.LIBRARY_AUDIOBOOKS,
                    ProviderFeature.LIBRARY_PLAYLISTS,
                    ProviderFeature.LIBRARY_PODCASTS,
                    ProviderFeature.LIBRARY_RADIOS,
                }.intersection(provider.supported_features)
            )

        if (
            (provider := mass.get_provider(provider_instance_id))
            and provider.type == ProviderType.MUSIC
            and verify_can_sync(provider)
        ):
            async_add_entities([MusicAssistantSyncMusicProviderButton(mass, provider)])

    # register callback to add players when they are discovered
    entry.runtime_data.platform_handlers_player.setdefault(Platform.BUTTON, add_player)

    entry.runtime_data.platform_handlers_provider.setdefault(
        Platform.BUTTON, add_music_provider
    )


class MusicAssistantFavoriteButton(MusicAssistantPlayerEntity, ButtonEntity):
    """Representation of a Button entity to favorite the current item."""

    entity_description = ButtonEntityDescription(
        key="favorite_now_playing",
        translation_key="favorite_now_playing",
    )

    @catch_musicassistant_error
    async def async_press(self) -> None:
        """Handle the button press command."""
        await self.mass.players.add_currently_playing_to_favorites(self.player_id)


class MusicAssistantSyncMusicProviderButton(MusicAssistantProviderEntity, ButtonEntity):
    """Button entity to sync a music provider with Music Assistant."""

    entity_description = ButtonEntityDescription(
        key="sync_music_provider",
        translation_key="sync_music_provider",
    )

    def __init__(self, mass: MusicAssistantClient, provider: ProviderInstance) -> None:
        """Initialize MusicAssistantSyncMusicProviderButton."""
        super().__init__(mass, provider)

        self._attr_translation_placeholders = {"provider_name": self.provider.name}

    @catch_musicassistant_error
    async def async_press(self) -> None:
        """Handle the button press command."""
        await self.mass.music.start_sync(providers=[self.provider.instance_id])
