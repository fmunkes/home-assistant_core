"""Music Assistant Switch platform."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Final, override

from music_assistant_client.client import MusicAssistantClient
from music_assistant_models.dsp import DSPConfig
from music_assistant_models.enums import EventType, PlayerType
from music_assistant_models.event import MassEvent
from music_assistant_models.player import PlayerOption, PlayerOptionType
from music_assistant_models.player_queue import PlayerQueue

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MusicAssistantConfigEntry
from .entity import MusicAssistantEntity, MusicAssistantPlayerOptionEntity
from .helpers import catch_musicassistant_error


@dataclass(frozen=True, kw_only=True)
class MusicAssistantQueueSwitchDescription(SwitchEntityDescription):
    """Describes a switch for a setting of a player's queue."""

    is_on_fn: Callable[[PlayerQueue], bool]
    set_fn: Callable[[MusicAssistantClient, str, bool], Awaitable[None]]


PLAYER_SETTINGS_SCHEMA_VERSION: Final = 101

QUEUE_SWITCHES: Final = (
    MusicAssistantQueueSwitchDescription(
        key="queue_crossfade",
        translation_key="queue_crossfade",
        is_on_fn=lambda queue: queue.crossfade_enabled,
        set_fn=lambda mass, queue_id, enabled: mass.player_queues.crossfade(
            queue_id, enabled
        ),
    ),
    MusicAssistantQueueSwitchDescription(
        key="queue_autoplay",
        translation_key="queue_autoplay",
        is_on_fn=lambda queue: queue.autoplay_enabled,
        set_fn=lambda mass, queue_id, enabled: mass.player_queues.autoplay(
            queue_id, enabled
        ),
    ),
)

PLAYER_OPTIONS_SWITCH: Final[dict[str, bool]] = {
    # translation_key: enabled_by_default
    "adaptive_drc": False,
    "bass_extension": False,
    "clear_voice": False,
    "enhancer": True,
    "extra_bass": False,
    "party_mode": False,
    "pure_direct": True,
    "speaker_a": True,
    "speaker_b": True,
    "surround_3d": False,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MusicAssistantConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Music Assistant Switch Entities (Player Options) from Config Entry."""
    mass = entry.runtime_data.mass
    if TYPE_CHECKING:
        assert mass.server_info is not None
    # older servers lack the queue commands and drop the preset when DSP is switched,
    # so their players keep only the option switches
    player_settings_supported = (
        mass.server_info.schema_version >= PLAYER_SETTINGS_SCHEMA_VERSION
    )

    def add_player(player_id: str) -> None:
        """Handle add player."""
        player = mass.players.get(player_id)
        if player is None:
            return
        entities: list[SwitchEntity] = []
        # the queue itself may still be missing, the server adds it after the player
        if player_settings_supported:
            entities.extend(
                MusicAssistantQueueSwitch(mass, player_id, description)
                for description in QUEUE_SWITCHES
            )
        # a group applies the DSP of each member, it has none of its own
        if player_settings_supported and player.type is not PlayerType.GROUP:
            entities.append(MusicAssistantDspSwitch(mass, player_id))
        for player_option in player.options:
            if (
                not player_option.read_only
                and player_option.type == PlayerOptionType.BOOLEAN
            ):
                # we ignore entities with unknown translation keys.
                if player_option.translation_key not in PLAYER_OPTIONS_SWITCH:
                    continue

                entities.append(
                    MusicAssistantPlayerConfigSwitch(
                        mass,
                        player_id,
                        player_option=player_option,
                        entity_description=SwitchEntityDescription(
                            key=player_option.key,
                            translation_key=player_option.translation_key,
                            entity_registry_enabled_default=PLAYER_OPTIONS_SWITCH[
                                player_option.translation_key
                            ],
                        ),
                    )
                )
        async_add_entities(entities)

    # register callback to add players when they are discovered
    entry.runtime_data.platform_handlers.setdefault(Platform.SWITCH, add_player)


class MusicAssistantPlayerConfigSwitch(MusicAssistantPlayerOptionEntity, SwitchEntity):
    """Representation of a Switch entity to control player settings."""

    def __init__(
        self,
        mass: MusicAssistantClient,
        player_id: str,
        player_option: PlayerOption,
        entity_description: SwitchEntityDescription,
    ) -> None:
        """Initialize MusicAssistantPlayerConfigSwitch."""
        super().__init__(mass, player_id, player_option)

        self.entity_description = entity_description

    @catch_musicassistant_error
    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Handle turn on command."""
        await self.mass.players.set_option(self.player_id, self.mass_option_key, True)

    @catch_musicassistant_error
    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Handle turn off command."""
        await self.mass.players.set_option(self.player_id, self.mass_option_key, False)

    @override
    def on_player_option_update(self, player_option: PlayerOption) -> None:
        """Update on player option update."""
        self._attr_is_on = (
            player_option.value if isinstance(player_option.value, bool) else None
        )


class MusicAssistantDspSwitch(MusicAssistantEntity, SwitchEntity):
    """Switch the DSP of a player on or off."""

    entity_description = SwitchEntityDescription(
        key="dsp",
        translation_key="dsp",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    )

    def __init__(self, mass: MusicAssistantClient, player_id: str) -> None:
        """Initialize MusicAssistantDspSwitch."""
        super().__init__(mass, player_id)
        self._dsp_config: DSPConfig | None = None

    @override
    async def async_added_to_hass(self) -> None:
        """Follow the player's DSP config, then load it."""
        # subscribe first, so a change while loading is not missed
        self.async_on_remove(
            self.mass.subscribe(
                self._on_dsp_config_updated,
                EventType.PLAYER_DSP_CONFIG_UPDATED,
                self.player_id,
            )
        )
        config = await self.mass.config.get_player_dsp_config(self.player_id)
        # an update that arrived while loading is newer than the response
        if self._dsp_config is None:
            self._dsp_config = config
        await super().async_added_to_hass()

    @property
    @override
    def is_on(self) -> bool | None:
        """Return if the player's DSP is on."""
        return self._dsp_config.enabled if self._dsp_config else None

    @catch_musicassistant_error
    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the DSP on with its last settings."""
        await self._set_enabled(True)

    @catch_musicassistant_error
    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the DSP off, keeping its settings."""
        await self._set_enabled(False)

    async def _set_enabled(self, enabled: bool) -> None:
        assert self._dsp_config  # loaded when the entity was added
        await self.mass.config.save_player_dsp_config(
            self.player_id, replace(self._dsp_config, enabled=enabled)
        )

    def _on_dsp_config_updated(self, event: MassEvent) -> None:
        self._dsp_config = DSPConfig.from_dict(event.data)
        self.async_write_ha_state()


class MusicAssistantQueueSwitch(MusicAssistantEntity, SwitchEntity):
    """Switch for a setting of the player's own queue."""

    _attr_entity_category = EntityCategory.CONFIG
    entity_description: MusicAssistantQueueSwitchDescription

    def __init__(
        self,
        mass: MusicAssistantClient,
        player_id: str,
        entity_description: MusicAssistantQueueSwitchDescription,
    ) -> None:
        """Initialize MusicAssistantQueueSwitch."""
        super().__init__(mass, player_id)
        self.entity_description = entity_description

    @override
    async def async_added_to_hass(self) -> None:
        """Register callbacks, also for the queue the server adds after the player."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.mass.subscribe(
                self._on_queue_added, EventType.QUEUE_ADDED, self.player_id
            )
        )

    def _on_queue_added(self, event: MassEvent) -> None:
        self.async_write_ha_state()

    @property
    @override
    def available(self) -> bool:
        """Return if the player and its queue are available."""
        return (
            super().available
            and self.mass.player_queues.get(self.player_id) is not None
        )

    @property
    @override
    def is_on(self) -> bool | None:
        """Return if the queue setting is on."""
        if (queue := self.mass.player_queues.get(self.player_id)) is None:
            return None
        return self.entity_description.is_on_fn(queue)

    @catch_musicassistant_error
    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the queue setting on."""
        await self.entity_description.set_fn(self.mass, self.player_id, True)

    @catch_musicassistant_error
    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the queue setting off."""
        await self.entity_description.set_fn(self.mass, self.player_id, False)
