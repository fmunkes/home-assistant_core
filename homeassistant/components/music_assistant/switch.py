"""Music Assistant Switch platform."""

from dataclasses import replace
from typing import TYPE_CHECKING, Any, Final, override

from music_assistant_client.client import MusicAssistantClient
from music_assistant_models.dsp import DSPConfig
from music_assistant_models.enums import EventType, PlayerType
from music_assistant_models.event import MassEvent
from music_assistant_models.player import PlayerOption, PlayerOptionType

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MusicAssistantConfigEntry
from .const import PLAYER_SETTINGS_SCHEMA_VERSION
from .entity import MusicAssistantEntity, MusicAssistantPlayerOptionEntity
from .helpers import catch_musicassistant_error

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
    # older servers drop the preset when DSP is switched, so they get no DSP switch
    dsp_supported = mass.server_info.schema_version >= PLAYER_SETTINGS_SCHEMA_VERSION

    def add_player(player_id: str) -> None:
        """Handle add player."""
        player = mass.players.get(player_id)
        if player is None:
            return
        entities: list[SwitchEntity] = []
        # a group applies the DSP of each member, it has none of its own
        if dsp_supported and player.type is not PlayerType.GROUP:
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
        """Load the player's DSP config and follow its changes."""
        self._dsp_config = await self.mass.config.get_player_dsp_config(self.player_id)
        await super().async_added_to_hass()
        self.async_on_remove(
            self.mass.subscribe(
                self._on_dsp_config_updated,
                EventType.PLAYER_DSP_CONFIG_UPDATED,
                self.player_id,
            )
        )

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
