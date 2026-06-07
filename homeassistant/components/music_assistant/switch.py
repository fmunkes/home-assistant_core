"""Music Assistant Switch platform."""

from typing import Any, Final

from music_assistant_client.client import MusicAssistantClient
from music_assistant_models.config_entries import ConfigEntry
from music_assistant_models.player import PlayerOption, PlayerOptionType

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import MusicAssistantConfigEntry
from .entity import MusicAssistantPlayerConfigEntity, MusicAssistantPlayerOptionEntity
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

PLAYER_CONFIGS_SWITCH: Final[dict[str, bool]] = {
    # translation_key: enabled_by_default
    "tts_pre_announce": True,
    "volume_normalization": True,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MusicAssistantConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Music Assistant Switch Entities (Player Options) from Config Entry."""
    mass = entry.runtime_data.mass

    def add_player(player_id: str) -> None:
        """Handle add player."""
        player = mass.players.get(player_id)
        if player is None:
            return
        # Player Options
        entities: list[
            MusicAssistantPlayerOptionSwitch | MusicAssistantPlayerConfigSwitch
        ] = []
        for player_option in player.options:
            if (
                not player_option.read_only
                and player_option.type == PlayerOptionType.BOOLEAN
            ):
                # we ignore entities with unknown translation keys.
                if player_option.translation_key not in PLAYER_OPTIONS_SWITCH:
                    continue

                entities.append(
                    MusicAssistantPlayerOptionSwitch(
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
        if player_configs := mass.players.get_player_configs(player_id):
            entities.extend(
                MusicAssistantPlayerConfigSwitch(
                    mass,
                    player_id,
                    player_config.key,
                    SwitchEntityDescription(
                        key=f"{player_id}_{player_config.key}",
                        translation_key=player_config.key,
                        entity_registry_enabled_default=PLAYER_CONFIGS_SWITCH[
                            player_config.key
                        ],
                    ),
                )
                for player_config in player_configs
                if player_config.key in PLAYER_CONFIGS_SWITCH
            )
        async_add_entities(entities)

    # register callback to add players when they are discovered
    entry.runtime_data.platform_handlers.setdefault(Platform.SWITCH, add_player)


class MusicAssistantPlayerConfigSwitch(MusicAssistantPlayerConfigEntity, SwitchEntity):
    """Representation of a switch entity to control player configs."""

    def __init__(
        self,
        mass: MusicAssistantClient,
        player_id: str,
        config_key: str,
        entity_description: SwitchEntityDescription,
    ) -> None:
        """Initialize MusicAssistantPlayerConfigSwitch."""
        super().__init__(mass, player_id, config_key)

        self.entity_description = entity_description

    @catch_musicassistant_error
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Handle turn on command."""
        await self.mass.config.save_player_config(
            self.player_id, {self.mass_config_key: True}
        )

    @catch_musicassistant_error
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Handle turn off command."""
        await self.mass.config.save_player_config(
            self.player_id, {self.mass_config_key: False}
        )

    def on_player_config_update(self, player_config_entry: ConfigEntry) -> None:
        """Update on player config update."""
        self._attr_is_on = (
            player_config_entry.value
            if isinstance(player_config_entry.value, bool)
            else player_config_entry.default_value
            if isinstance(player_config_entry.default_value, bool)
            else None
        )


class MusicAssistantPlayerOptionSwitch(MusicAssistantPlayerOptionEntity, SwitchEntity):
    """Representation of a Switch entity to control player options."""

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
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Handle turn on command."""
        await self.mass.players.set_option(self.player_id, self.mass_option_key, True)

    @catch_musicassistant_error
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Handle turn off command."""
        await self.mass.players.set_option(self.player_id, self.mass_option_key, False)

    def on_player_option_update(self, player_option: PlayerOption) -> None:
        """Update on player option update."""
        self._attr_is_on = (
            player_option.value if isinstance(player_option.value, bool) else None
        )
